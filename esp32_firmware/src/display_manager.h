/*
 * 桌面电子宠物 - 显示管理模块（完整版）
 * 包含：像素风格表情动画 + 天气图标 + 状态指示
 * 硬件: 微雪 ESP32-S3 1.54inch LCD (240x240, ST7789V)
 */

#ifndef DISPLAY_MANAGER_H
#define DISPLAY_MANAGER_H

#include <LovyanGFX.hpp>
#include "config.h"
#include "types.h"
#include "pixel_player.h"

// ============ 屏幕驱动配置 ============

class LGFX : public lgfx::LGFX_Device {
    lgfx::Panel_ST7789 _panel;
    lgfx::Bus_SPI _bus;
    lgfx::Light_PWM _light;

public:
    LGFX(void) {
        auto cfg = _bus.config();
        cfg.spi_host = SPI2_HOST;
        cfg.spi_mode = 0;
        cfg.freq_write = 80000000;
        cfg.freq_read = 16000000;
        cfg.pin_sclk = LCD_SCLK;
        cfg.pin_mosi = LCD_MOSI;
        cfg.pin_miso = LCD_MISO;
        cfg.pin_dc = LCD_DC;
        cfg.dma_channel = SPI_DMA_CH_AUTO;  // 启用DMA异步传输
        _bus.config(cfg);
        _panel.setBus(&_bus);

        auto pcfg = _panel.config();
        pcfg.pin_cs = LCD_CS;
        pcfg.pin_rst = LCD_RST;
        pcfg.pin_busy = -1;
        pcfg.memory_width = SCREEN_WIDTH;
        pcfg.memory_height = SCREEN_HEIGHT;
        pcfg.panel_width = SCREEN_WIDTH;
        pcfg.panel_height = SCREEN_HEIGHT;
        pcfg.offset_x = 0;
        pcfg.offset_y = 0;
        pcfg.offset_rotation = SCREEN_ROTATION;
        pcfg.rgb_order = false;
        pcfg.invert = true;
        pcfg.readable = false;
        pcfg.bus_shared = false;
        _panel.config(pcfg);

        auto lcfg = _light.config();
        lcfg.pin_bl = LCD_BL;
        lcfg.invert = false;
        lcfg.freq = 44100;
        lcfg.pwm_channel = 7;
        _light.config(lcfg);
        _panel.setLight(&_light);

        setPanel(&_panel);
    }
};

// ============ 动画帧定义 ============

// 每个表情 4 帧动画
#define ANIM_FRAMES 4
// 表情尺寸 32x32
#define FACE_SIZE 32
// 天气图标尺寸 20x20
#define WEATHER_ICON_SIZE 20
// 动画帧间隔 (ms)
#define FACE_FRAME_INTERVAL 200

// 表情类型枚举
enum FaceType {
    FACE_HAPPY = 0,     // 😊 空闲 - 开心放松
    FACE_WORKING = 1,   // 😤 工作中 - 专注认真
    FACE_AUTH = 2,      // 😰 需授权 - 紧张等待
    FACE_OFFLINE = 3,   // 😴 离线 - 睡眠状态
    FACE_COUNT = 4
};

// 显示模式
enum DisplayMode {
    MODE_NORMAL = 0,    // 正常状态显示
    MODE_PIXEL,         // 自定义像素显示
};

// ============ 显示管理器 ============

class DisplayManager {
public:
    DisplayManager();
    void begin();
    void update(const DisplayData& data);
    void updateAnimation();
    void showBootScreen(String message);

    // 屏幕休眠控制
    void dim();      // 降低亮度（数据超时）
    void sleep();    // 关闭背光（深度休眠）
    void wakeup();   // 恢复全亮

    // 像素模式控制
    void setPixelMode(PixelPlayer* player);   // 进入自定义像素模式
    void setNormalMode();                       // 返回正常模式
    bool isPixelMode() const { return _displayMode == MODE_PIXEL; }
    DisplayMode getDisplayMode() const { return _displayMode; }
    PixelPlayer* getPixelPlayer() const { return _pixelPlayer; }

    // 离线模式公共接口（由renderTask调用）
    void drawClock();        // 离线模式：显示实时时钟
    void drawBlinkAnim();    // 眨眼动画

private:
    LGFX _lcd;
    LGFX_Sprite _sprite;  // 双缓冲：离屏画布，消除闪烁
    uint8_t _currentStatus;
    uint8_t _animFrame;
    unsigned long _lastAnimTime;
    unsigned long _lastPartialUpdate;
    FaceType _currentFace;
    uint16_t _blinkCounter;

    // 像素模式
    DisplayMode _displayMode;
    PixelPlayer* _pixelPlayer;

    // 主绘制方法
    void drawHeader();
    void drawStatusBar(const AgentState& agent);
    void drawWeatherPanel(const WeatherInfo& weather);
    void drawTokenPanel(const TokenStats& tokens);
    void drawFaceAnimation();

    // 像素帧绘制
    void drawPixelFrame();

    // 表情绘制 (32x32 像素风格)
    void drawFace(int x, int y, FaceType type, uint8_t frame);
    void drawFaceHappy(int x, int y, uint8_t frame);
    void drawFaceWorking(int x, int y, uint8_t frame);
    void drawFaceAuth(int x, int y, uint8_t frame);
    void drawFaceOffline(int x, int y, uint8_t frame);

    // 天气图标绘制 (20x20)
    void drawWeatherIcon(String icon, int x, int y);
    void drawIconSun(int x, int y, uint8_t frame);
    void drawIconMoon(int x, int y);
    void drawIconCloud(int x, int y);
    void drawIconClouds(int x, int y);
    void drawIconRainLight(int x, int y, uint8_t frame);
    void drawIconRain(int x, int y, uint8_t frame);
    void drawIconThunder(int x, int y, uint8_t frame);
    void drawIconSnow(int x, int y, uint8_t frame);
    void drawIconFog(int x, int y);
    void drawIconCloudSun(int x, int y, uint8_t frame);
    void drawIconCloudMoon(int x, int y);

    // 辅助绘制
    void drawEyes(int x, int y, int size, uint16_t color, bool blink);
    void drawMouth(int x, int y, int type, uint16_t color);
    void drawStatusDot(int x, int y, int r, uint8_t status, uint8_t frame);

    // ============ 颜色定义 ============
    // 背景色
    static const uint16_t COLOR_BG       = 0x0000;  // 黑色
    static const uint16_t COLOR_PANEL    = 0x18E3;  // 深灰蓝 #303848
    static const uint16_t COLOR_PANEL_LT = 0x2945;  // 浅灰蓝 #505868
    static const uint16_t COLOR_HEADER   = 0x10A2;  // 标题栏深色

    // 状态色
    static const uint16_t COLOR_IDLE     = 0x07E0;  // 绿色 #00FF00
    static const uint16_t COLOR_WORKING  = 0xFFE0;  // 黄色 #FFFF00
    static const uint16_t COLOR_AUTH     = 0xF800;  // 红色 #FF0000
    static const uint16_t COLOR_OFFLINE  = 0x8410;  // 灰色 #808080

    // 表情色
    static const uint16_t FACE_YELLOW    = 0xFFE0;  // 脸部黄色 #FFFF00
    static const uint16_t FACE_ORANGE    = 0xFD20;  // 橙色 #FF8C00
    static const uint16_t FACE_PINK      = 0xF810;  // 腮红粉 #FF8080
    static const uint16_t FACE_WHITE     = 0xFFFF;  // 白色
    static const uint16_t FACE_BLACK     = 0x0000;  // 黑色(眼睛/嘴巴)
    static const uint16_t FACE_RED       = 0xF800;  // 红色
    static const uint16_t FACE_BLUE      = 0x001F;  // 蓝色
    static const uint16_t FACE_GRAY      = 0xC618;  // 灰色

    // 文字色
    static const uint16_t COLOR_TEXT     = 0xFFFF;  // 白色
    static const uint16_t COLOR_TEXT_DIM = 0xC618;  // 暗灰
};

#endif // DISPLAY_MANAGER_H
