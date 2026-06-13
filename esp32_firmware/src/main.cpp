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
#include "ble_config.h"
#include "sound_manager.h"
#include "touch_handler.h"
#include <esp_ota_ops.h>
#include <esp_sleep.h>
#include "driver/rtc_io.h"

// ============ 共享数据 (双缓冲+atomic指针交换，无mutex阻塞) ============
DisplayData g_displayBuf[2];           // 双缓冲：front=read, back=write
std::atomic<int> g_frontIdx{0};        // 原子索引：0或1，标识当前front buffer
std::atomic<bool> g_forceWake{false};  // 原子标志：通信收到数据时强制唤醒

// 像素缓冲区（通信任务写入，渲染任务读取）
// PSRAM静态预分配池：32x32x2x64 = 128KB，避免运行时malloc碎片化
__attribute__((section(".psram"))) static uint8_t g_pxlPool[32 * 32 * 2 * 64];
static constexpr size_t PXL_POOL_SIZE = sizeof(g_pxlPool);

uint8_t* g_pxlBuffer = g_pxlPool;
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
unsigned long g_screenSleepStart = 0;  // 进入屏幕休眠的时间（用于Light Sleep计时）
bool g_screenDimmed = false;
bool g_screenSleeping = false;
// g_forceWake 已移至上方atomic声明
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
            
            // [Step 5] 双缓冲写入：更新连接状态
            {
                int backIdx = 1 - g_frontIdx.load(std::memory_order_acquire);
                g_displayBuf[backIdx] = g_displayBuf[g_frontIdx.load(std::memory_order_acquire)];
                g_displayBuf[backIdx].connected = true;
                g_displayBuf[backIdx].lastUpdate = now;
                g_lastDataReceived = now;
                isOffline = false;
                g_forceWake.store(true, std::memory_order_release);  // 通知渲染任务唤醒屏幕
                g_frontIdx.store(backIdx, std::memory_order_release);
            }
        }

        // 离线检测：45秒无数据 → OFFLINE
        if (!isOffline && (now - g_lastDataReceived > OFFLINE_TIMEOUT_MS)) {
            // [Step 5] 双缓冲：标记离线
            {
                int backIdx = 1 - g_frontIdx.load(std::memory_order_acquire);
                g_displayBuf[backIdx] = g_displayBuf[g_frontIdx.load(std::memory_order_acquire)];
                g_displayBuf[backIdx].connected = false;
                g_displayBuf[backIdx].agent.status = STATUS_OFFLINE;
                isOffline = true;
                g_frontIdx.store(backIdx, std::memory_order_release);
            }
            Serial.println("[CommTask] 45s无数据，进入OFFLINE模式");
        }

        // BOOT键(GPIO0)：短按停止像素播放，切回普通模式；休眠中按下则唤醒屏幕
        if (digitalRead(0) == LOW) {
            delay(50);  // 消抖
            if (digitalRead(0) == LOW) {
                // 休眠状态下：唤醒屏幕显示15秒
                if (g_screenSleeping) {
                    g_forceWake.store(true, std::memory_order_release);
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
            // 断连时重置像素池状态（无需free，静态池常驻）
            g_pxlBuffer = g_pxlPool;
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

    else if (type == "thinking_status") {
        // 思考链状态 (from OTLP ThinkingChainTracker)
        StaticJsonDocument<256> filter;
        filter["type"] = true;
        filter["data"]["state"] = true;
        filter["data"]["name"] = true;
        filter["data"]["tool"] = true;
        filter["data"]["step_count"] = true;
        
        StaticJsonDocument<256> doc;
        DeserializationError error = deserializeJson(doc, json, DeserializationOption::Filter(filter));
        if (error) { Serial.printf("[JSON] thinking parse error: %s\n", error.c_str()); return; }
        
        JsonObject data = doc["data"];
        String state = data["state"] | "idle";
        
        ThinkingState ts = THINK_IDLE;
        if (state == "thinking") ts = THINK_THINKING;
        else if (state == "tool_call") ts = THINK_TOOL_CALL;
        else if (state == "responding") ts = THINK_RESPONDING;
        else if (state == "error") ts = THINK_ERROR;
        else if (state == "done") ts = THINK_DONE;
        
        {
            int backIdx = 1 - g_frontIdx.load(std::memory_order_acquire);
            g_displayBuf[backIdx] = g_displayBuf[g_frontIdx.load(std::memory_order_acquire)];
            g_displayBuf[backIdx].thinkingState = ts;
            g_frontIdx.store(backIdx, std::memory_order_release);
        }
        
        Serial.printf("[Thinking] state=%s tool=%s step=%d\n",
            state.c_str(), (data["tool"] | "").as<const char*>(), data["step_count"] | 0);
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
        
        // [Step 5] 原子指针交换：读front buffer，无需mutex
        int frontIdx = g_frontIdx.load(std::memory_order_acquire);
        localData = g_displayBuf[frontIdx];
        needWake = g_forceWake.exchange(false, std::memory_order_acq_rel);
        
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
            g_screenSleepStart = now;
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
            // Light Sleep: 屏幕休眠5分钟后进入ESP32 Light Sleep（超低功耗）
            static constexpr uint32_t LIGHT_SLEEP_TIMEOUT = 300000;  // 5min
            if (now - g_screenSleepStart >= LIGHT_SLEEP_TIMEOUT) {
                Serial.println("[Power] Entering Light Sleep (touch+wifi beacon wakeup)");
                display.sleep();
                esp_sleep_enable_touchpad_wakeup();
                esp_sleep_enable_wifi_beacon_wakeup();
                // RTC IO状态保持：锁定关键引脚电平，防止Light Sleep期间漂移
                gpio_hold_en((gpio_num_t)LCD_BL);       // 背光保持低电平
                gpio_hold_en((gpio_num_t)BUZZER_PIN);   // 蜂鸣器保持低电平（静音）
                gpio_hold_en((gpio_num_t)LCD_CS);       // SPI片选保持高电平（未选中）
                esp_light_sleep_start();
                // === 唤醒 ===
                gpio_hold_dis((gpio_num_t)LCD_BL);
                gpio_hold_dis((gpio_num_t)BUZZER_PIN);
                gpio_hold_dis((gpio_num_t)LCD_CS);
                setCpuFrequencyMhz(240);
                g_screenSleeping = false;
                g_screenDimmed = false;
                g_forceWake.store(true, std::memory_order_release);
                Serial.println("[Power] Woke from Light Sleep, CPU 240MHz");
            }
            vTaskDelay(pdMS_TO_TICKS(500));  // 未达Light Sleep阈值时低频轮询
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
            // 静态PSRAM池无需free（Core 1加载后数据已复制到PixelPlayer内部）
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
        
        // ===== 温控自适应（每10秒检测，避免CPU过热） =====
        static unsigned long lastThermalCheck = 0;
        if (!g_screenSleeping && now - lastThermalCheck >= 10000) {
            lastThermalCheck = now;
            float cpuTemp = temperatureRead();
            if (cpuTemp > 65.0f) {
                setCpuFrequencyMhz(80);
                display.setBrightness(80);  // 降低背光减轻发热
                Serial.printf("[Render] THERMAL CRITICAL %.1f°C → CPU 80MHz + dim\n", cpuTemp);
            } else if (cpuTemp > 55.0f) {
                setCpuFrequencyMhz(160);
                Serial.printf("[Render] THERMAL WARNING %.1f°C → CPU 160MHz\n", cpuTemp);
            } else if (cpuTemp < 50.0f && getCpuFrequencyMhz() < 240) {
                setCpuFrequencyMhz(240);
                Serial.printf("[Render] THERMAL OK %.1f°C → CPU 240MHz\n", cpuTemp);
            }
        }
        
        // ===== [Step 7] 堆监控（每5秒打印PSRAM+Internal堆水位） =====
        static unsigned long lastHeapLog = 0;
        if (!g_screenSleeping && now - lastHeapLog >= 5000) {
            lastHeapLog = now;
            log_i("[Heap] Internal Free=%d B, MaxAlloc=%d B | PSRAM Free=%d B, MaxAlloc=%d B",
                  ESP.getFreeHeap(), ESP.getMaxAllocHeap(),
                  ESP.getFreePsram(), ESP.getMaxAllocPsram());
        }
        
        // ===== [Step 8] FPS计数器（每秒输出实际渲染帧率） =====
        static uint32_t fpsFrameCount = 0;
        static unsigned long lastFpsReport = 0;
        fpsFrameCount++;
        if (now - lastFpsReport >= 1000) {
            uint32_t elapsed = now - lastFpsReport;
            float fps = fpsFrameCount * 1000.0f / elapsed;
            log_i("[FPS] %.1f fps (%u frames in %lu ms)", fps, fpsFrameCount, elapsed);
            fpsFrameCount = 0;
            lastFpsReport = now;
        }
        
        // VRR动态帧率：根据屏幕状态+Agent状态调整（OTLP联动）
        uint32_t frameDelay = 20;  // ACTIVE: 50fps
        if (g_screenSleeping) {
            frameDelay = 500;       // SLEEP: 2fps
        } else if (g_screenDimmed) {
            frameDelay = 1000;      // DIM: 1fps
        } else if (millis() - g_lastDataReceived > SCREEN_DIM_TIMEOUT / 2) {
            frameDelay = 200;       // IDLE: 5fps (数据静默>15秒)
        } else {
            // OTLP联动：根据Agent状态微调帧率
            int backIdx = 1 - g_frontIdx.load(std::memory_order_acquire);
            uint8_t agentStatus = g_displayBuf[backIdx].agent.status;
            if (agentStatus == STATUS_WORKING) {
                frameDelay = 16;    // Agent工作中: 60fps (流畅思考动画)
            } else if (agentStatus == STATUS_AUTH) {
                frameDelay = 33;    // 认证/交互: 30fps
            }
            // STATUS_IDLE/STATUS_OFFLINE: 保持默认50fps
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
    
    // [Step 5] 双缓冲模式，无需互斥锁
    Serial.println("[INIT] Double-buffer mode (no mutex needed)");
    
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
    
    // 初始化数据（双缓冲：初始化front buffer）
    int idx = g_frontIdx.load(std::memory_order_acquire);
    g_displayBuf[idx].agent.status = STATUS_OFFLINE;
    g_displayBuf[idx].connected = false;
    g_displayBuf[idx].lastUpdate = 0;
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
        // [Step 5] 双缓冲写入：copy front→back, 写back, atomic swap
        {
            int backIdx = 1 - g_frontIdx.load(std::memory_order_acquire);
            g_displayBuf[backIdx] = g_displayBuf[g_frontIdx.load(std::memory_order_acquire)];
            g_displayBuf[backIdx].agent.status = parseStatus(data["status"] | "offline");
            g_displayBuf[backIdx].agent.processName = data["process"] | "";
            g_displayBuf[backIdx].agent.cpuPercent = data["cpu"] | 0.0;
            g_displayBuf[backIdx].agent.memoryMB = data["memory"] | 0.0;
            g_displayBuf[backIdx].agent.uptimeSeconds = data["uptime"] | 0;
            g_frontIdx.store(backIdx, std::memory_order_release);
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
        // [Step 5] 双缓冲写入
        {
            int backIdx = 1 - g_frontIdx.load(std::memory_order_acquire);
            g_displayBuf[backIdx] = g_displayBuf[g_frontIdx.load(std::memory_order_acquire)];
            g_displayBuf[backIdx].tokens.inputTokens = data["input"] | 0;
            g_displayBuf[backIdx].tokens.outputTokens = data["output"] | 0;
            g_displayBuf[backIdx].tokens.totalRequests = data["requests"] | 0;
            g_displayBuf[backIdx].tokens.hourTokens = data["hour"] | 0;
            g_displayBuf[backIdx].tokens.costUSD = data["cost"] | 0.0;
            g_frontIdx.store(backIdx, std::memory_order_release);
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
        // [Step 5] 双缓冲写入
        {
            int backIdx = 1 - g_frontIdx.load(std::memory_order_acquire);
            g_displayBuf[backIdx] = g_displayBuf[g_frontIdx.load(std::memory_order_acquire)];
            g_displayBuf[backIdx].weather.city = data["city"] | "";
            g_displayBuf[backIdx].weather.temperature = data["temp"] | 0.0;
            g_displayBuf[backIdx].weather.feelsLike = data["feels_like"] | 0.0;
            g_displayBuf[backIdx].weather.humidity = data["humidity"] | 0;
            g_displayBuf[backIdx].weather.description = data["desc"] | "";
            g_displayBuf[backIdx].weather.iconCode = data["icon"] | "";
            g_displayBuf[backIdx].weather.windSpeed = data["wind"] | 0.0;
            g_frontIdx.store(backIdx, std::memory_order_release);
        }
    }
    else if (type == "pixel_data") {
        // 流式解析：兼容两种协议格式
        // 格式A (pxl_sender): {"type":"pixel_data","data":{"packet_index":0,"total_packets":N,"chunk_base64":"..."},"ts":...}
        // 格式B (legacy): {"type":"pixel_data","data":"base64","chunk":0,"last":false,"ts":...}
        
        // 用完整JSON解析，兼容嵌套对象和简单字符串
        StaticJsonDocument<1536> pixelDoc;
        DeserializationError err = deserializeJson(pixelDoc, json);
        if (err) { Serial.printf("[Main] Pixel JSON parse error: %s\n", err.c_str()); return; }
        
        JsonObject dataObj = pixelDoc["data"];
        int chunkIndex = 0;
        bool isLastChunk = false;
        const char* b64Data = nullptr;
        size_t b64Len = 0;
        
        if (dataObj.containsKey("packet_index")) {
            // 格式A: data是嵌套对象（pxl_sender发送）
            chunkIndex = dataObj["packet_index"] | 0;
            int totalPackets = dataObj["total_packets"] | 1;
            isLastChunk = (chunkIndex == totalPackets - 1);
            b64Data = dataObj["chunk_base64"] | "";
            b64Len = strlen(b64Data);
        } else if (dataObj.is<const char*>()) {
            // 格式B: data直接是base64字符串（legacy格式）
            chunkIndex = pixelDoc["chunk"] | 0;
            isLastChunk = pixelDoc["last"] | false;
            b64Data = dataObj.as<const char*>();
            b64Len = strlen(b64Data);
        } else {
            Serial.println("[Main] Pixel: unknown data format");
            return;
        }
        
        if (!b64Data || b64Len == 0) { Serial.println("[Main] Pixel: empty base64 data"); return; }

        if (chunkIndex == 0) {
            g_pxlBuffer = g_pxlPool;
            g_pxlCapacity = PXL_POOL_SIZE;
            g_pxlOffset = 0;
        }
        if (!g_pxlBuffer) { Serial.println("[Main] Pixel: buffer alloc failed"); return; }

        // 预估解码后大小（base64: 每4字节→3字节二进制）
        size_t estimatedDecoded = b64Len * 3 / 4;
        if (g_pxlOffset + estimatedDecoded > g_pxlCapacity) {
            Serial.printf("[Main] Pixel: overflow! offset=%d est_decoded=%d cap=%d\n",
                          g_pxlOffset, estimatedDecoded, (int)g_pxlCapacity);
            return;
        }

        // 直接解码到PSRAM池（mbedtls自报告实际写入字节数）
        size_t written = 0;
        int ret = mbedtls_base64_decode(g_pxlBuffer + g_pxlOffset,
                                        g_pxlCapacity - g_pxlOffset,
                                        &written,
                                        (const unsigned char*)b64Data,
                                        b64Len);
        if (ret != 0) {
            Serial.printf("[Main] Pixel: base64 decode error %d (chunk %d)\n", ret, chunkIndex);
            return;
        }
        g_pxlOffset += written;
        Serial.printf("[Main] Pixel chunk %d decoded: %d bytes, total %d\n", chunkIndex, written, g_pxlOffset);

        if (isLastChunk && g_pxlBuffer) {
            // 将缓冲区指针传递给 Core 1，由它在自己的时间片内加载
            g_pendingPixelBufferPtr = g_pxlPool;
            g_pendingPixelSize = g_pxlOffset;
            g_pendingPixelBufferLoad.store(true);
            Serial.printf("[Main] Pixel pool ready (%d bytes), pending load on Core 1\n", g_pxlOffset);
            // 重置池指针（Core 1加载后数据已复制到PixelPlayer内部）
            g_pxlBuffer = g_pxlPool;
            g_pxlOffset = 0;
            g_pxlCapacity = PXL_POOL_SIZE;
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
