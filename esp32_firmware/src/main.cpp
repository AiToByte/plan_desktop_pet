/*
 * 桌面电子宠物 - ESP32-S3 主程序 (v2: FreeRTOS双核架构)
 * Core 0: 通信任务 (WiFi/TCP/JSON解析)
 * Core 1: 渲染任务 (显示更新/动画/休眠管理)
 * 硬件: 微雪 ESP32-S3 1.54inch LCD
 */

#include <Arduino.h>
#include "config.h"
#include "types.h"
#include "display_manager.h"
#include "pixel_player.h"
#include "wifi_manager.h"
#include "comm_manager.h"

// ============ 共享数据 (mutex保护) ============
DisplayData g_displayData;
SemaphoreHandle_t g_dataMutex;

// 像素缓冲区（通信任务写入，渲染任务读取）
uint8_t* g_pxlBuffer = nullptr;
size_t g_pxlOffset = 0;
size_t g_pxlCapacity = 0;

// 模块实例
DisplayManager display;
WiFiManager wifi;
CommManager comm;
PixelPlayer pixelPlayer;

// 任务句柄
TaskHandle_t g_commTaskHandle = NULL;
TaskHandle_t g_renderTaskHandle = NULL;

// 休眠状态
unsigned long g_lastDataReceived = 0;  // 最后收到有效数据的时间
bool g_screenDimmed = false;
bool g_screenSleeping = false;
bool g_forceWake = false;  // 通信收到数据时强制唤醒

// Core 0 → Core 1 显示操作待处理标志（避免跨核直接调LCD/SPI）
volatile bool g_pendingNormalMode = false;
volatile bool g_pendingPixelPlay = false;
volatile bool g_pendingPixelStop = false;
PixelPlayer* g_pendingPixelPtr = nullptr;

// ============ 前向声明 ============
void parseServerData(String json);
uint8_t parseStatus(String status);
void commTask(void* pvParameters);
void renderTask(void* pvParameters);

// ============ 通信任务 (Core 0) ============
void commTask(void* pvParameters) {
    Serial.println("[CommTask] Started on Core 0");
    unsigned long lastHeartbeat = 0;
    
    while (true) {
        unsigned long now = millis();
        
        // 处理Web配网请求
        if (wifi.isConfiguring()) {
            wifi.handleConfig();
            vTaskDelay(pdMS_TO_TICKS(10));
            continue;
        }
        
        // 处理通信
        comm.update();
        
        // 检查是否有新数据
        if (comm.hasNewData()) {
            String json = comm.getData();
            parseServerData(json);
            
            // 更新连接状态（mutex保护）
            if (xSemaphoreTake(g_dataMutex, pdMS_TO_TICKS(10)) == pdTRUE) {
                g_displayData.connected = true;
                g_displayData.lastUpdate = now;
                g_lastDataReceived = now;
                g_forceWake = true;  // 通知渲染任务唤醒屏幕
                xSemaphoreGive(g_dataMutex);
            }
        }
        
        // 检查连接状态
        if (!comm.isConnected() && wifi.isConnected()) {
            // 断连时清理像素状态
            if (g_pxlBuffer) {
                free(g_pxlBuffer);
                g_pxlBuffer = nullptr;
            }
            g_pxlCapacity = 0;
            g_pxlOffset = 0;
            g_pendingNormalMode = true;  // Core 1将执行display.setNormalMode()
            comm.reconnect();
        }
        
        // 定时心跳
        if (now - lastHeartbeat >= 10000) {
            lastHeartbeat = now;
            if (comm.isConnected()) {
                comm.sendHeartbeat();
            }
        }
        
        vTaskDelay(pdMS_TO_TICKS(10));  // 让出CPU，避免看门狗超时
    }
}

// ============ 渲染任务 (Core 1) ============
void renderTask(void* pvParameters) {
    Serial.println("[RenderTask] Started on Core 1");
    unsigned long lastDisplayUpdate = 0;
    unsigned long lastAnimationUpdate = 0;
    
    DisplayData localData;  // 本地副本，减少mutex持有时间
    
    while (true) {
        unsigned long now = millis();
        bool needWake = false;
        
        // 从共享数据复制到本地（快速mutex操作）
        if (xSemaphoreTake(g_dataMutex, pdMS_TO_TICKS(5)) == pdTRUE) {
            localData = g_displayData;
            needWake = g_forceWake;
            g_forceWake = false;
            xSemaphoreGive(g_dataMutex);
        }
        
        // ===== 屏幕休眠管理 =====
        unsigned long timeSinceData = now - g_lastDataReceived;
        
        if (needWake && (g_screenDimmed || g_screenSleeping)) {
            // 数据到达 → 唤醒屏幕
            display.wakeup();
            g_screenDimmed = false;
            g_screenSleeping = false;
            Serial.println("[Render] Screen wake (data received)");
        } else if (!g_screenSleeping && timeSinceData > SCREEN_SLEEP_TIMEOUT) {
            // 超时 → 进入休眠
            display.sleep();
            g_screenSleeping = true;
            g_screenDimmed = true;
            Serial.println("[Render] Screen sleep (timeout)");
            vTaskDelay(pdMS_TO_TICKS(1000));  // 休眠后降低刷新率
            continue;
        } else if (!g_screenDimmed && timeSinceData > SCREEN_DIM_TIMEOUT) {
            // 变暗
            display.dim();
            g_screenDimmed = true;
            Serial.println("[Render] Screen dim (timeout)");
        }
        
        if (g_screenSleeping) {
            vTaskDelay(pdMS_TO_TICKS(500));  // 休眠时低频轮询
            continue;
        }
        
        // ===== 处理来自Core 0的待执行显示操作 =====
        if (g_pendingNormalMode) {
            display.setNormalMode();
            g_pendingNormalMode = false;
            Serial.println("[Render] setNormalMode executed (pending)");
        }
        if (g_pendingPixelPlay && g_pendingPixelPtr) {
            display.setPixelMode(g_pendingPixelPtr);
            g_pendingPixelPtr->play();
            g_pendingPixelPlay = false;
            g_pendingPixelPtr = nullptr;
            Serial.println("[Render] Pixel play executed (pending)");
        }
        if (g_pendingPixelStop) {
            pixelPlayer.stop();
            g_pendingPixelStop = false;
            Serial.println("[Render] Pixel stop executed (pending)");
        }
        
        // ===== 显示更新 =====
        if (now - lastDisplayUpdate >= UPDATE_INTERVAL) {
            lastDisplayUpdate = now;
            display.update(localData);
        }
        
        // ===== 动画更新 =====
        if (now - lastAnimationUpdate >= ANIMATION_INTERVAL) {
            lastAnimationUpdate = now;
            display.updateAnimation();
        }
        
        vTaskDelay(pdMS_TO_TICKS(20));  // ~50fps上限
    }
}

// ============ 初始化 ============
void setup() {
    Serial.begin(115200);
    delay(1000);
    
    Serial.println("================================");
    Serial.println("桌面电子宠物 - ESP32-S3 (v2 Dual-Core)");
    Serial.println("================================");
    
    // 创建互斥锁
    g_dataMutex = xSemaphoreCreateMutex();
    if (g_dataMutex == NULL) {
        Serial.println("[INIT] FATAL: Mutex creation failed!");
        while (1) delay(1000);  // 停机
    }
    
    // 初始化显示
    Serial.println("[INIT] 初始化显示...");
    display.begin();
    pixelPlayer.begin();
    display.showBootScreen("Initializing...");
    
    // 初始化WiFi
    Serial.println("[INIT] 连接WiFi...");
    display.showBootScreen("Connecting WiFi...");
    wifi.begin();
    
    if (wifi.connect()) {
        Serial.println("[WiFi] Connected: " + wifi.getIP());
        display.showBootScreen("WiFi: " + wifi.getIP());
        
        // 设置通信服务器地址
        String serverHost = wifi.getServerHost();
        int serverPort = wifi.getServerPort();
        if (serverHost.length() > 0) {
            comm.setServer(serverHost, serverPort);
            Serial.println("[INIT] Server: " + serverHost + ":" + String(serverPort));
        }
    } else {
        Serial.println("[WiFi] Connection failed!");
        display.showBootScreen("WiFi Failed!");
    }
    
    // 初始化通信
    Serial.println("[INIT] 初始化通信...");
    comm.begin();
    
    // 初始化数据
    g_displayData.agent.status = STATUS_OFFLINE;
    g_displayData.connected = false;
    g_displayData.lastUpdate = 0;
    g_lastDataReceived = millis();
    
    delay(1000);
    Serial.println("[INIT] 启动FreeRTOS双核任务...");
    
    // 创建通信任务 (Core 0)
    xTaskCreatePinnedToCore(
        commTask,           // 任务函数
        "CommTask",         // 任务名
        COMM_TASK_STACK,    // 栈大小
        NULL,               // 参数
        2,                  // 优先级(高于渲染)
        &g_commTaskHandle,  // 任务句柄
        COMM_TASK_CORE      // 绑定Core 0
    );
    
    // 创建渲染任务 (Core 1)
    xTaskCreatePinnedToCore(
        renderTask,         // 任务函数
        "RenderTask",       // 任务名
        RENDER_TASK_STACK,  // 栈大小
        NULL,               // 参数
        1,                  // 优先级
        &g_renderTaskHandle,// 任务句柄
        RENDER_TASK_CORE    // 绑定Core 1
    );
    
    Serial.println("[INIT] 双核任务启动完成!");
    Serial.printf("[INIT] CommTask@Core%d, RenderTask@Core%d\n", COMM_TASK_CORE, RENDER_TASK_CORE);
}

// Arduino loop() - FreeRTOS任务模式下不再使用，保持最小
void loop() {
    vTaskDelay(pdMS_TO_TICKS(1000));  // 空闲循环，让出CPU
}

// ============ 数据解析 ============
void parseServerData(String json) {
    DynamicJsonDocument doc(1024);
    DeserializationError error = deserializeJson(doc, json);
    
    if (error) {
        Serial.print("[JSON] Parse error: ");
        Serial.println(error.c_str());
        return;
    }
    
    String type = doc["type"] | "unknown";
    
    if (type == "status") {
        JsonObject data = doc["data"];
        if (xSemaphoreTake(g_dataMutex, pdMS_TO_TICKS(10)) == pdTRUE) {
            g_displayData.agent.status = parseStatus(data["status"] | "offline");
            g_displayData.agent.processName = data["process"] | "";
            g_displayData.agent.cpuPercent = data["cpu"] | 0.0;
            g_displayData.agent.memoryMB = data["memory"] | 0.0;
            g_displayData.agent.uptimeSeconds = data["uptime"] | 0;
            xSemaphoreGive(g_dataMutex);
        }
    }
    else if (type == "token") {
        JsonObject data = doc["data"];
        if (xSemaphoreTake(g_dataMutex, pdMS_TO_TICKS(10)) == pdTRUE) {
            g_displayData.tokens.inputTokens = data["input"] | 0;
            g_displayData.tokens.outputTokens = data["output"] | 0;
            g_displayData.tokens.totalRequests = data["requests"] | 0;
            g_displayData.tokens.hourTokens = data["hour"] | 0;
            g_displayData.tokens.costUSD = data["cost"] | 0.0;
            xSemaphoreGive(g_dataMutex);
        }
    }
    else if (type == "weather") {
        JsonObject data = doc["data"];
        if (xSemaphoreTake(g_dataMutex, pdMS_TO_TICKS(10)) == pdTRUE) {
            g_displayData.weather.city = data["city"] | "";
            g_displayData.weather.temperature = data["temp"] | 0.0;
            g_displayData.weather.feelsLike = data["feels_like"] | 0.0;
            g_displayData.weather.humidity = data["humidity"] | 0;
            g_displayData.weather.description = data["desc"] | "";
            g_displayData.weather.iconCode = data["icon"] | "";
            g_displayData.weather.windSpeed = data["wind"] | 0.0;
            xSemaphoreGive(g_dataMutex);
        }
    }
    else if (type == "pixel_data") {
        String pxlBase64 = doc["data"] | "";
        int chunkIndex = doc["chunk"] | 0;
        bool isLastChunk = doc["last"] | false;

        // 第一包：初始化缓冲区
        if (chunkIndex == 0) {
            if (g_pxlBuffer) { free(g_pxlBuffer); g_pxlBuffer = nullptr; }
            g_pxlCapacity = 4096;
            g_pxlBuffer = (uint8_t*)ps_malloc(g_pxlCapacity);
            g_pxlOffset = 0;
        }

        if (!g_pxlBuffer) {
            Serial.println("[Main] Pixel: buffer alloc failed");
            return;
        }

        // Base64解码
        size_t decodedLen = pxlBase64.length() * 3 / 4 + 3;
        while (g_pxlOffset + decodedLen > g_pxlCapacity) {
            g_pxlCapacity *= 2;
            uint8_t* newBuf = (uint8_t*)ps_realloc(g_pxlBuffer, g_pxlCapacity);
            if (!newBuf) {
                Serial.println("[Main] Pixel: realloc failed");
                free(g_pxlBuffer); g_pxlBuffer = nullptr;
                return;
            }
            g_pxlBuffer = newBuf;
        }

        size_t written = base64_decode(g_pxlBuffer + g_pxlOffset, pxlBase64.c_str(), pxlBase64.length());
        g_pxlOffset += written;
        Serial.printf("[Main] Pixel chunk %d decoded: %d bytes, total %d\n", chunkIndex, written, g_pxlOffset);

        if (isLastChunk && g_pxlBuffer) {
            if (pixelPlayer.loadFromBuffer(g_pxlBuffer, g_pxlOffset)) {
                g_pendingPixelPlay = true;
                g_pendingPixelPtr = &pixelPlayer;
                Serial.printf("[Main] Pixel loaded: %d bytes, pending play\n", g_pxlOffset);
            } else {
                Serial.println("[Main] Pixel load failed");
            }
            free(g_pxlBuffer); g_pxlBuffer = nullptr;
            g_pxlOffset = 0;
        }
    }
    else if (type == "pixel_cmd") {
        String action = doc["action"] | "";
        if (action == "play") {
            if (pixelPlayer.isLoaded()) {
                g_pendingPixelPlay = true;
                g_pendingPixelPtr = &pixelPlayer;
                Serial.println("[Main] Pixel play requested");
            }
        }
        else if (action == "stop") {
            g_pendingPixelStop = true;
            g_pendingNormalMode = true;
            Serial.println("[Main] Pixel stop -> normal mode");
        }
        else if (action == "pause") {
            pixelPlayer.pause();
            Serial.println("[Main] Pixel paused");
        }
    }
}

uint8_t parseStatus(String status) {
    if (status == "idle") return STATUS_IDLE;
    if (status == "working") return STATUS_WORKING;
    if (status == "auth") return STATUS_AUTH;
    return STATUS_OFFLINE;
}
