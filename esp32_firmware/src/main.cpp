/*
 * 桌面电子宠物 - ESP32-S3 主程序
 * 硬件: 微雪 ESP32-S3 1.54inch LCD
 */

#include <Arduino.h>
#include "config.h"
#include "types.h"
#include "display_manager.h"
#include "pixel_player.h"
#include "wifi_manager.h"
#include "comm_manager.h"

// 全局数据
DisplayData g_displayData;

// 模块实例
DisplayManager display;
WiFiManager wifi;
CommManager comm;
PixelPlayer pixelPlayer;

// 定时器
unsigned long lastDisplayUpdate = 0;
unsigned long lastHeartbeat = 0;

void setup() {
    Serial.begin(115200);
    delay(1000);
    
    Serial.println("================================");
    Serial.println("桌面电子宠物 - ESP32-S3");
    Serial.println("================================");
    
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
        
        // 设置通信服务器地址（来自Web配网配置）
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
    
    delay(1000);
    Serial.println("[INIT] 启动完成!");
}

void loop() {
    unsigned long now = millis();
    
    // 处理Web配网请求（配网模式下）
    if (wifi.isConfiguring()) {
        wifi.handleConfig();
        delay(10);
        return;  // 配网模式下不执行其他逻辑
    }
    
    // 处理通信
    comm.update();
    
    // 检查是否有新数据
    if (comm.hasNewData()) {
        String json = comm.getData();
        parseServerData(json);
        g_displayData.connected = true;
        g_displayData.lastUpdate = now;
    }
    
    // 检查连接状态
    if (!comm.isConnected() && wifi.isConnected()) {
        comm.reconnect();
    }
    
    // 定时更新显示
    if (now - lastDisplayUpdate >= UPDATE_INTERVAL) {
        lastDisplayUpdate = now;
        display.update(g_displayData);
    }
    
    // 定时心跳
    if (now - lastHeartbeat >= 10000) {
        lastHeartbeat = now;
        if (comm.isConnected()) {
            comm.sendHeartbeat();
        }
    }
    
    // 动画更新
    display.updateAnimation();
    
    delay(10);
}

void parseServerData(String json) {
    // 使用ArduinoJson解析
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
        g_displayData.agent.status = parseStatus(data["status"] | "offline");
        g_displayData.agent.processName = data["process"] | "";
        g_displayData.agent.cpuPercent = data["cpu"] | 0.0;
        g_displayData.agent.memoryMB = data["memory"] | 0.0;
        g_displayData.agent.uptimeSeconds = data["uptime"] | 0;
    }
    else if (type == "token") {
        JsonObject data = doc["data"];
        g_displayData.tokens.inputTokens = data["input"] | 0;
        g_displayData.tokens.outputTokens = data["output"] | 0;
        g_displayData.tokens.totalRequests = data["requests"] | 0;
        g_displayData.tokens.hourTokens = data["hour"] | 0;
        g_displayData.tokens.costUSD = data["cost"] | 0.0;
    }
    else if (type == "weather") {
        JsonObject data = doc["data"];
        g_displayData.weather.city = data["city"] | "";
        g_displayData.weather.temperature = data["temp"] | 0.0;
        g_displayData.weather.feelsLike = data["feels_like"] | 0.0;
        g_displayData.weather.humidity = data["humidity"] | 0;
        g_displayData.weather.description = data["desc"] | "";
        g_displayData.weather.iconCode = data["icon"] | "";
        g_displayData.weather.windSpeed = data["wind"] | 0.0;
    }
    else if (type == "pixel_data") {
        // 接收PXL像素数据（Base64编码的分包）
        static uint8_t* pxlBuffer = nullptr;
        static size_t pxlOffset = 0;
        static size_t pxlCapacity = 0;

        String pxlBase64 = doc["data"] | "";
        int chunkIndex = doc["chunk"] | 0;
        bool isLastChunk = doc["last"] | false;

        // 第一包：初始化缓冲区
        if (chunkIndex == 0) {
            if (pxlBuffer) { free(pxlBuffer); pxlBuffer = nullptr; }
            pxlCapacity = 4096;  // 初始4KB
            pxlBuffer = (uint8_t*)ps_malloc(pxlCapacity);
            pxlOffset = 0;
        }

        if (!pxlBuffer) {
            Serial.println("[Main] Pixel: buffer alloc failed");
            return;
        }

        // Base64解码
        size_t decodedLen = pxlBase64.length() * 3 / 4 + 3;
        // 扩容检查
        while (pxlOffset + decodedLen > pxlCapacity) {
            pxlCapacity *= 2;
            uint8_t* newBuf = (uint8_t*)ps_realloc(pxlBuffer, pxlCapacity);
            if (!newBuf) {
                Serial.println("[Main] Pixel: realloc failed");
                free(pxlBuffer); pxlBuffer = nullptr;
                return;
            }
            pxlBuffer = newBuf;
        }

        // 手动Base64解码（ESP32 Arduino自带base64库）
        size_t written = base64_decode(pxlBuffer + pxlOffset, pxlBase64.c_str(), pxlBase64.length());
        pxlOffset += written;
        Serial.printf("[Main] Pixel chunk %d decoded: %d bytes, total %d\n", chunkIndex, written, pxlOffset);

        // 最后一包：加载到PixelPlayer
        if (isLastChunk && pxlBuffer) {
            if (pixelPlayer.loadFromBuffer(pxlBuffer, pxlOffset)) {
                display.setPixelMode(&pixelPlayer);
                pixelPlayer.play();
                Serial.printf("[Main] Pixel loaded: %d bytes, playing\n", pxlOffset);
            } else {
                Serial.println("[Main] Pixel load failed");
            }
            free(pxlBuffer); pxlBuffer = nullptr;
            pxlOffset = 0;
        }
    }
    else if (type == "pixel_cmd") {
        // 像素模式控制命令
        String action = doc["action"] | "";

        if (action == "play") {
            if (pixelPlayer.isLoaded()) {
                display.setPixelMode(&pixelPlayer);
                pixelPlayer.play();
                Serial.println("[Main] Pixel play");
            }
        }
        else if (action == "stop") {
            pixelPlayer.stop();
            display.setNormalMode();
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
