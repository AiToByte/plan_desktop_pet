#ifndef CONFIG_H
#define CONFIG_H

// WiFi配置 - 已改为Web配网模式，无需硬编码
// #define WIFI_SSID "YOUR_WIFI_SSID"
// #define WIFI_PASSWORD "YOUR_WIFI_PASSWORD"
#define WIFI_TIMEOUT 10000

// Web配网配置
#define AP_SSID "Pet-Setup"
#define AP_PASSWORD "12345678"
#define CONFIG_PORT 80
#define CONFIG_TIMEOUT 120000  // 配网超时2分钟

// 服务器配置 (PC端) - 通过Web配网设置
// #define SERVER_HOST "192.168.1.100"
#define SERVER_PORT 19876
#define RECONNECT_INTERVAL 5000

// TCP连接配置
#define CLIENT_TCP_TIMEOUT      10     // 秒，WiFiClient::setTimeout
#define CLIENT_TCP_KEEPIDLE     5      // 秒，空闲后发第一个keepalive探测
#define CLIENT_TCP_KEEPINTVL    5      // 秒，探测间隔
#define CLIENT_TCP_KEEPCNT      3      // 探测失败次数后断开
#define CLIENT_READ_BUF_SIZE    512    // TCP批量读取缓冲区大小

// 屏幕引脚定义 (微雪ESP32-S3 1.54inch LCD)
#define LCD_CS    5
#define LCD_RST   4
#define LCD_DC    2
#define LCD_MOSI  11
#define LCD_SCLK  12
#define LCD_BL    48
// V-Sync TE引脚 (ST7789V Tearing Effect Output)
// 硬件接线: ESP32 GPIO → ST7789V TE引脚 (需要确认硬件原理图)
// 目前使用软件帧率控制，TE引脚就绪后切换到硬件V-Sync
#define LCD_TE_PIN          -1     // -1=禁用(软件帧率), 接线后改为实际GPIO
#define TE_ACTIVE_HIGH      true   // TE信号极性: true=上升沿有效
#define VSYNC_TIMEOUT_MS    20     // 等待V-Sync超时(ms)

#define LCD_MISO  13

// 屏幕参数
#define SCREEN_WIDTH  240
#define SCREEN_HEIGHT 240
#define SCREEN_ROTATION 0

// 显示更新间隔 (ms)
#define UPDATE_INTERVAL 1000
#define ANIMATION_INTERVAL 500

// FreeRTOS双核配置
#define COMM_TASK_CORE    0    // 通信任务运行在Core 0
#define RENDER_TASK_CORE  1    // 渲染任务运行在Core 1
#define COMM_TASK_STACK   8192 // 通信任务栈大小
#define RENDER_TASK_STACK 16384 // 渲染任务栈较大(含sprite操作)

// 屏幕休眠配置
#define SCREEN_DIM_TIMEOUT   30000  // 30秒无数据→变暗
#define SCREEN_SLEEP_TIMEOUT 60000  // 60秒无数据→休眠(关背光)

// 离线检测配置
#define OFFLINE_TIMEOUT_MS   45000  // 45秒无数据→状态切为OFFLINE

// 状态定义
#define STATUS_IDLE      0
#define STATUS_WORKING   1
#define STATUS_AUTH      2
#define STATUS_OFFLINE   3

// 调试
#define DEBUG_SERIAL 1

// 蜂鸣器引脚 (无源蜂鸣器)
#define BUZZER_PIN 18          // GPIO18

// 电容触摸引脚
#define TOUCH_PIN 1            // GPIO1 (Touch1)
#define TOUCH_THRESHOLD 40     // 触摸阈值（需校准）
#define TOUCH_LONG_PRESS_MS 1000

#endif // CONFIG_H
