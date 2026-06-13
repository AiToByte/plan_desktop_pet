#ifndef TYPES_H
#define TYPES_H

#include <Arduino.h>

// Agent状态
struct AgentState {
    uint8_t status;
    ThinkingState thinkingState = THINK_IDLE;  // 思考链状态         // STATUS_IDLE/WORKING/AUTH/OFFLINE
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


// ============ 思考链状态 (OTLP可视化) ============
enum ThinkingState : uint8_t {
    THINK_IDLE = 0,
    THINK_THINKING,
    THINK_TOOL_CALL,
    THINK_RESPONDING,
    THINK_ERROR,
    THINK_DONE
};

#endif // TYPES_H
