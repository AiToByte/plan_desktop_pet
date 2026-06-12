/*
 * 桌面电子宠物 - ESP32-S3 主程序 (v2: FreeRTOS双核架构)
 * Core 0: 通信任务 (WiFi/TCP/JSON解析)
 * Core 1: 渲染任务 (显示更新/动画/休眠管理)
 * 硬件: 微雪 ESP32-S3 1.54inch LCD
 */

#include <Arduino.h>
#include <atomic>
#include <mbedtls/base64.h>
#include "config.h"
#include "types.h"
#include "display_manager.h"
#include "pixel_player.h"
#include "wifi_manager.h"
#include "comm_manager.h"
#include "sound_manager.h"
#include "touch_handler.h"
#include <esp_ota_ops.h>

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
SoundManager sound;
TouchHandler touch;

// 任务句柄
TaskHandle_t g_commTaskHandle = NULL;
TaskHandle_t g_renderTaskHandle = NULL;

// 休眠状态
unsigned long g_lastDataReceived = 0;  // 最后收到有效数据的时间
bool g_screenDimmed = false;
bool g_screenSleeping = false;
bool g_forceWake = false;  // 通信收到数据时强制唤醒
// Core 0 → Core 1 显示操作待处理标志（避免跨核直接调LCD/SPI）
// 使用std::atomic确保双核SMP架构下的内存强一致性
std::atomic<bool> g_pendingNormalMode{false};
std::atomic<bool> g_pendingPixelPlay{false};
std::atomic<bool> g_pendingPixelStop{false};
std::atomic<bool> g_pendingPixelBufferLoad{false};
std::atomic<uint8_t*> g_pendingPixelBufferPtr{nullptr};
std::atomic<PixelPlayer*> g_pendingPixelPtr{nullptr};
std::atomic<size_t> g_pendingPixelSize{0};

// ============ 前向声明 ============
void parseServerData(String json);
uint8_t parseStatus(String status);
void commTask(void* pvParameters);
void renderTask(void* pvParameters);

// ============ 通信任务 (Core 0) ============
void commTask(void* pvParameters) {
    Serial.println("[CommTask] Started on Core 0");
    unsigned long lastHeartbeat = 0;
    bool isOffline = false;
    
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
                isOffline = false;
                g_forceWake = true;  // 通知渲染任务唤醒屏幕
                xSemaphoreGive(g_dataMutex);
            }
        }

        // 离线检测：45秒无数据 → OFFLINE
        if (!isOffline && (now - g_lastDataReceived > OFFLINE_TIMEOUT_MS)) {
            if (xSemaphoreTake(g_dataMutex, pdMS_TO_TICKS(10)) == pdTRUE) {
                g_displayData.connected = false;
                g_displayData.agent.status = STATUS_OFFLINE;
                isOffline = true;
                xSemaphoreGive(g_dataMutex);
            }
            Serial.println("[CommTask] 45s无数据，进入OFFLINE模式");
        }

        // BOOT键(GPIO0)：短按停止像素播放，切回普通模式；休眠中按下则唤醒屏幕
        if (digitalRead(0) == LOW) {
            delay(50);  // 消抖
            if (digitalRead(0) == LOW) {
                // 休眠状态下：唤醒屏幕显示15秒
                if (g_screenSleeping) {
                    g_forceWake = true;
                    Serial.println("[CommTask] BOOT键：唤醒屏幕(15s)");
                }
                // 普通状态下：停止像素播放
                else if (pixelPlayer.isLoaded()) {
                    pixelPlayer.stop();
                    g_pendingNormalMode.store(true);
                    Serial.println("[CommTask] BOOT键：停止像素播放");
                }
                while (digitalRead(0) == LOW) vTaskDelay(pdMS_TO_TICKS(10));  // 等释放
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
            // 数据到达 → 唤醒屏幕 + 恢复全速CPU + WiFi活跃
            setCpuFrequencyMhz(240);
            WiFi.setSleep(false);
            display.wakeup();
            g_screenDimmed = false;
            g_screenSleeping = false;
            Serial.println("[Render] Screen wake (data received), CPU 240MHz, WiFi active");
        } else if (!g_screenSleeping && timeSinceData > SCREEN_SLEEP_TIMEOUT) {
            // 超时 → 进入休眠 + 降频CPU + WiFi节能
            setCpuFrequencyMhz(80);
            WiFi.setSleep(true);
            display.sleep();
            g_screenSleeping = true;
            g_screenDimmed = true;
            Serial.println("[Render] Screen sleep (timeout), CPU 80MHz, WiFi sleep");
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
            display.setPixelMode(g_pendingPixelPtr.load());
            g_pendingPixelPtr.load()->play();
            g_pendingPixelPlay = false;
            g_pendingPixelPtr = nullptr;
            Serial.println("[Render] Pixel play executed (pending)");
        }
        if (g_pendingPixelStop) {
            pixelPlayer.stop();
            g_pendingPixelStop = false;
            Serial.println("[Render] Pixel stop executed (pending)");
        }
        if (g_pendingPixelBufferLoad && g_pendingPixelBufferPtr) {
            // Core 0 传来的像素缓冲区，在 Core 1 自己的时间片内加载
            uint8_t* buf = g_pendingPixelBufferPtr;
            g_pendingPixelBufferPtr = nullptr;
            size_t sz = g_pendingPixelSize;
            if (pixelPlayer.loadFromBuffer(buf, sz)) {
                g_pendingPixelPlay = true;
                g_pendingPixelPtr = &pixelPlayer;
                Serial.printf("[Render] Pixel loaded on Core 1: %d bytes, pending play\n", sz);
            } else {
                Serial.println("[Render] Pixel load failed on Core 1");
            }
            free(buf);
            g_pendingPixelBufferLoad = false;
        }
        
        // ===== 显示更新 =====
        if (now - lastDisplayUpdate >= UPDATE_INTERVAL) {
            lastDisplayUpdate = now;
            if (!localData.connected && !pixelPlayer.isLoaded()) {
                // 离线模式：显示时钟+眨眼动画
                display.drawClock();
            } else {
                display.update(localData);
            }
        }
        
        // ===== 动画更新 =====
        if (now - lastAnimationUpdate >= ANIMATION_INTERVAL) {
            lastAnimationUpdate = now;
            if (!localData.connected && !pixelPlayer.isLoaded()) {
                display.drawBlinkAnim();
            } else {
                display.updateAnimation();
            }
        }
        
        // VRR动态帧率：根据状态调整延迟
        uint32_t frameDelay = 20;  // ACTIVE: 50fps
        if (g_screenSleeping) {
            frameDelay = 500;       // SLEEP: 2fps
        } else if (g_screenDimmed) {
            frameDelay = 1000;      // DIM: 1fps
        } else if (millis() - g_lastDataReceived > SCREEN_DIM_TIMEOUT / 2) {
            frameDelay = 200;       // IDLE: 5fps (数据静默>15秒)
        }
        
        // 触摸检测
        touch.update();
        
        vTaskDelay(pdMS_TO_TICKS(frameDelay));
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
    // PixelPlayer 构造函数已自动初始化，无需 begin()
    display.showBootScreen("Initializing...");
    
    // 初始化蜂鸣器
    Serial.println("[INIT] 初始化蜂鸣器...");
    sound.begin();
    // 触摸反馈：任何触摸事件触发短促蜂鸣
    touch.setCallback([](TouchEvent event) {
        sound.beep(4500, 15);
    });
    sound.playStartup();
    
    // 初始化触摸
    Serial.println("[INIT] 初始化触摸...");
    touch.begin();
    touch.setCallback([](TouchEvent e) {
        if (e == TOUCH_SINGLE_TAP) {
            sound.playNotification();
            Serial.println("[Touch] Single tap");
        } else if (e == TOUCH_DOUBLE_TAP) {
            sound.playNotification();
            Serial.println("[Touch] Double tap");
        } else if (e == TOUCH_LONG_PRESS) {
            sound.playAlert();
            Serial.println("[Touch] Long press");
        }
    });
    
    // 初始化WiFi
    Serial.println("[INIT] 连接WiFi...");
    display.showBootScreen("Connecting WiFi...");
    wifi.begin();
    
    if (wifi.connect()) {
        Serial.println("[WiFi] Connected: " + wifi.getIP());
        display.showBootScreen("WiFi: " + wifi.getIP());
        
        // 同步NTP时间（东八区）
        configTime(8 * 3600, 0, "ntp.aliyun.com", "ntp1.aliyun.com");
        Serial.println("[INIT] NTP sync started");
        
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
    // --- Phase 1: 快速提取type字段（最小64字节分配）---
    StaticJsonDocument<64> typeDoc;
    deserializeJson(typeDoc, json);
    String type = typeDoc["type"] | "unknown";
    
    // --- Phase 2: 按类型过滤解析 ---
    if (type == "status") {
        StaticJsonDocument<256> filter;
        filter["type"] = true;
        filter["data"]["status"] = true;
        filter["data"]["process"] = true;
        filter["data"]["cpu"] = true;
        filter["data"]["memory"] = true;
        filter["data"]["uptime"] = true;
        
        StaticJsonDocument<256> doc;
        DeserializationError error = deserializeJson(doc, json, DeserializationOption::Filter(filter));
        if (error) { Serial.printf("[JSON] status parse error: %s\n", error.c_str()); return; }
        
        JsonObject data = doc["data"];
        if (xSemaphoreTake(g_dataMutex, pdMS_TO_TICKS(10)) == pdTRUE) {
            g_displayData.agent.status = parseStatus(data["status"] | "offline");
            g_displayData.agent.processName = data["process"] | "";
            g_displayData.agent.cpuPercent = data["cpu"] | 0.0;
            g_displayData.agent.memoryMB = data["memory"] | 0.0;
            g_displayData.agent.uptimeSeconds = data["uptime"] | 0;
            xSemaphoreGive(g_dataMutex);
        }
        
        // 首次成功解析status包 → 新固件健康，取消OTA回滚
        static bool isOtaValidated = false;
        if (!isOtaValidated) {
            esp_ota_mark_app_valid_cancel_rollback();
            isOtaValidated = true;
            Serial.println("[OTA] New app validated successfully by server packet!");
        }
    }
    else if (type == "token") {
        StaticJsonDocument<256> filter;
        filter["type"] = true;
        filter["data"]["input"] = true;
        filter["data"]["output"] = true;
        filter["data"]["requests"] = true;
        filter["data"]["hour"] = true;
        filter["data"]["cost"] = true;
        
        StaticJsonDocument<256> doc;
        DeserializationError error = deserializeJson(doc, json, DeserializationOption::Filter(filter));
        if (error) { Serial.printf("[JSON] token parse error: %s\n", error.c_str()); return; }
        
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
        StaticJsonDocument<384> filter;
        filter["type"] = true;
        filter["data"]["city"] = true;
        filter["data"]["temp"] = true;
        filter["data"]["feels_like"] = true;
        filter["data"]["humidity"] = true;
        filter["data"]["desc"] = true;
        filter["data"]["icon"] = true;
        filter["data"]["wind"] = true;
        
        StaticJsonDocument<384> doc;
        DeserializationError error = deserializeJson(doc, json, DeserializationOption::Filter(filter));
        if (error) { Serial.printf("[JSON] weather parse error: %s\n", error.c_str()); return; }
        
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
        // pixel_data包含二进制Base64，用DynamicJsonDocument无法过滤，保持原分配
        DynamicJsonDocument doc(1024);
        DeserializationError error = deserializeJson(doc, json);
        if (error) { Serial.printf("[JSON] pixel_data parse error: %s\n", error.c_str()); return; }
        
        String pxlBase64 = doc["data"] | "";
        int chunkIndex = doc["chunk"] | 0;
        bool isLastChunk = doc["last"] | false;

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

        // 使用mbedtls进行base64解码（ESP32 Arduino内置）
        size_t written = 0;
        mbedtls_base64_decode(g_pxlBuffer + g_pxlOffset,
                              (size_t)(g_pxlCapacity - g_pxlOffset),
                              &written,
                              (const unsigned char*)pxlBase64.c_str(),
                              pxlBase64.length());
        g_pxlOffset += written;
        Serial.printf("[Main] Pixel chunk %d decoded: %d bytes, total %d\n", chunkIndex, written, g_pxlOffset);

        if (isLastChunk && g_pxlBuffer) {
            // 不在 Core 0 直接 loadFromBuffer —— Core 1 渲染循环可能正在访问 pixelPlayer
            // 将缓冲区指针传递给 Core 1，由它在自己的时间片内加载，加载后释放
            g_pendingPixelBufferPtr = g_pxlBuffer;
            g_pendingPixelSize = g_pxlOffset;
            g_pendingPixelBufferLoad.store(true);
            Serial.printf("[Main] Pixel buffer ready (%d bytes), pending load on Core 1\n", g_pxlOffset);
            // 不释放 g_pxlBuffer —— Core 1 load 完成后负责 free
            g_pxlBuffer = nullptr;
            g_pxlOffset = 0;
            g_pxlCapacity = 0;
        }
    }
    else if (type == "pixel_cmd") {
        // pixel_cmd字段少且固定，用StaticJsonDocument即可
        StaticJsonDocument<128> doc;
        DeserializationError error = deserializeJson(doc, json);
        if (error) { Serial.printf("[JSON] pixel_cmd parse error: %s\n", error.c_str()); return; }
        
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
