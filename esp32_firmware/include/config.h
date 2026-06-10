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

// 屏幕引脚定义 (微雪ESP32-S3 1.54inch LCD)
#define LCD_CS    5
#define LCD_RST   4
#define LCD_DC    2
#define LCD_MOSI  11
#define LCD_SCLK  12
#define LCD_BL    48
#define LCD_MISO  13

// 屏幕参数
#define SCREEN_WIDTH  240
#define SCREEN_HEIGHT 240
#define SCREEN_ROTATION 0

// 显示更新间隔 (ms)
#define UPDATE_INTERVAL 1000
#define ANIMATION_INTERVAL 500

// 状态定义
#define STATUS_IDLE      0
#define STATUS_WORKING   1
#define STATUS_AUTH      2
#define STATUS_OFFLINE   3

// 调试
#define DEBUG_SERIAL 1

#endif // CONFIG_H
