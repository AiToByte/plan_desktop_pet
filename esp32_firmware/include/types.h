#ifndef TYPES_H
#define TYPES_H

#include <Arduino.h>

// ============ 思考链状态 (OTLP可视化) ============
enum ThinkingState : uint8_t {
    THINK_IDLE = 0,
    THINK_THINKING,
    THINK_TOOL_CALL,
    THINK_RESPONDING,
    THINK_ERROR,
    THINK_DONE
};

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

    // 思考链历史滚动展示 (PSRAM环形缓冲)
    ThinkingStepCache* thinkingHistory = nullptr;  // 在setup()中分配到PSRAM
    float scrollOffset = 0.0f;                     // 当前滚动偏移 (0.0~1.0)
    bool needsScroll = false;                      // 是否需要滚动动画
    unsigned long scrollStartTime = 0;             // 滚动动画开始时间
};

#endif // TYPES_H
