#ifndef TYPES_H
#define TYPES_H

#include <Arduino.h>

// Agent状态
struct AgentState {
    uint8_t status;         // STATUS_IDLE/WORKING/AUTH/OFFLINE
    String processName;
    float cpuPercent;
    float memoryMB;
    uint32_t uptimeSeconds;
};

// Token统计
struct TokenStats {
    uint32_t inputTokens;
    uint32_t outputTokens;
    uint32_t totalRequests;
    uint32_t hourTokens;
    float costUSD;
};

// 天气信息
struct WeatherInfo {
    String city;
    float temperature;
    float feelsLike;
    uint8_t humidity;
    String description;
    String iconCode;
    float windSpeed;
};

// 显示数据
struct DisplayData {
    AgentState agent;
    TokenStats tokens;
    WeatherInfo weather;
    uint32_t lastUpdate;
    bool connected;
};

#endif // TYPES_H
