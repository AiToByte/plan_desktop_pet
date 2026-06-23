#ifndef CONFIG_H
#define CONFIG_H

// WiFi配置 - 已改为Web配网模式，无需硬编码
// #define WIFI_SSID "YOUR_WIFI_SSID"
// #define WIFI_PASSWORD "YOUR_WIFI_PASSWORD"
#define WIFI_TIMEOUT 10000

// Web配网配置
#define AP_SSID "Pet-Setup"
#define AP_PASSWORD "pet"  // [FIX-SEC1] 临时默认值，启动时根据MAC生成唯一密码并覆盖(见web_config init)
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
#define LCD_BRIGHTNESS  200    // LCD背光亮度 (0-255)

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

// 接近感应配置（基于电容微量差分检测）
#define PROX_EMA_FAST_ALPHA     0.3f    // 快速EMA系数（响应快）
#define PROX_EMA_SLOW_ALPHA     0.05f   // 慢速EMA系数（基线跟踪）
#define PROX_RISING_THRESHOLD   8       // 上升差分阈值（接近检测）
#define PROX_FALLING_THRESHOLD  4       // 下降差分阈值（远离检测）
#define PROX_COOLDOWN_MS        2000    // 接近事件冷却时间（防抖）
#define PROX_WAKE_DURATION_MS   15000   // 接近唤醒后亮屏时长

// ============ BH1750光照传感器配置 ============
#define BH1750_SDA_PIN          41      // I2C SDA引脚
#define BH1750_SCL_PIN          42      // I2C SCL引脚
#define BH1750_READ_INTERVAL    2000    // 光照读取间隔(ms)

// ============ DRV2605L触觉反馈配置 ============
#define HAPTIC_SDA_PIN          41      // 与BH1750共享I2C总线
#define HAPTIC_SCL_PIN          42

// ============ 思考链历史展示配置 ============
#define THINKING_HISTORY_MAX      40    // PSRAM环形缓冲最大步数
#define THINKING_VISIBLE_COUNT    5     // 同时可见的最近步骤数
#define SCROLL_DURATION_MS        800   // 滚动动画时长(ms)
#define THINKING_STEP_TEXT_MAX    64    // 单步文本最大长度

// ============ .pxl 差分帧协议 ============
#define DELTA_FULL                0x01  // 完整帧标记
#define DELTA_DIFF                0x02  // 差分帧标记
#define RLE_COPY                  0x00  // 复制操作
#define RLE_REPEAT                0x01  // 重复操作
#define RLE_LITERAL               0x02  // 字面操作
#define RLE_MAX_RUN               127   // RLE最大游程
#define LITERAL_MAX_LEN           127   // 字面最大长度

// ============ WiFi省电配置 ============
#define IDLE_POWER_MODE           2     // 空闲省电模式(0=ACTIVE,1=MODEM_SLEEP_AUTO,2=LIGHT_SLEEP)
#define DTIM_ACTIVE               1     // 活跃态DTIM间隔
#define DTIM_IDLE                 10    // 空闲态DTIM间隔
#define IDLE_TIMEOUT_MS           30000 // 进入省电模式的空闲超时(ms)
#define WAKE_CHECK_INTERVAL_MS    500   // 唤醒检查间隔(ms)
#define BSS_MAX_IDLE_SEC          300   // BSS最大空闲时间(秒)

#endif // CONFIG_H
