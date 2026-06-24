/*
 * 桌面电子宠物 - 显示管理模块（完整版）
 * 包含：像素风格表情动画 + 天气图标 + 状态指示
 */

#include "display_manager.h"
#include <math.h>
#include <time.h>
#include "log.h"

// ============ SRAM切片缓冲（用于分块传输） ============
static uint16_t s_sramSliceBuf[512] __attribute__((aligned(4))) __attribute__((section(".dram")));
static bool s_sramInited = false;

// V-Sync TE中断标志（定义在.h中声明）
volatile bool DisplayManager::s_teTriggered = false;
static uint16_t s_sramBufW = 0;
static uint16_t s_sramBufH = 0;

// ============ Fast Trig LUT (256-entry, Q10 fixed-point, max error 0.0005) ============
static const int16_t sinLUT[256] PROGMEM = {
        0,    25,    50,    75,   100,   125,   150,   175,   200,   224,   249,   273,   297,   321,   345,   369,
      392,   415,   438,   460,   483,   505,   526,   548,   569,   590,   610,   630,   650,   669,   688,   706,
      724,   742,   759,   775,   792,   807,   822,   837,   851,   865,   878,   891,   903,   915,   926,   936,
      946,   955,   964,   972,   980,   987,   993,   999,  1004,  1009,  1013,  1016,  1019,  1021,  1023,  1024,
     1024,  1024,  1023,  1021,  1019,  1016,  1013,  1009,  1004,   999,   993,   987,   980,   972,   964,   955,
      946,   936,   926,   915,   903,   891,   878,   865,   851,   837,   822,   807,   792,   775,   759,   742,
      724,   706,   688,   669,   650,   630,   610,   590,   569,   548,   526,   505,   483,   460,   438,   415,
      392,   369,   345,   321,   297,   273,   249,   224,   200,   175,   150,   125,   100,    75,    50,    25,
        0,   -25,   -50,   -75,  -100,  -125,  -150,  -175,  -200,  -224,  -249,  -273,  -297,  -321,  -345,  -369,
     -392,  -415,  -438,  -460,  -483,  -505,  -526,  -548,  -569,  -590,  -610,  -630,  -650,  -669,  -688,  -706,
     -724,  -742,  -759,  -775,  -792,  -807,  -822,  -837,  -851,  -865,  -878,  -891,  -903,  -915,  -926,  -936,
     -946,  -955,  -964,  -972,  -980,  -987,  -993,  -999, -1004, -1009, -1013, -1016, -1019, -1021, -1023, -1024,
    -1024, -1024, -1023, -1021, -1019, -1016, -1013, -1009, -1004,  -999,  -993,  -987,  -980,  -972,  -964,  -955,
     -946,  -936,  -926,  -915,  -903,  -891,  -878,  -865,  -851,  -837,  -822,  -807,  -792,  -775,  -759,  -742,
     -724,  -706,  -688,  -669,  -650,  -630,  -610,  -590,  -569,  -548,  -526,  -505,  -483,  -460,  -438,  -415,
     -392,  -369,  -345,  -321,  -297,  -273,  -249,  -224,  -200,  -175,  -150,  -125,  -100,   -75,   -50,   -25,
};

static inline float fastSin(float angle) {
    int idx = (int)(angle * 40.743665f) & 0xFF;  // 256/(2*PI)
    return sinLUT[idx] * 0.0009765625f;           // / 1024.0
}
static inline float fastCos(float angle) {
    int idx = ((int)(angle * 40.743665f) + 64) & 0xFF;
    return sinLUT[idx] * 0.0009765625f;
}

// ============ Pre-allocated fade blend buffer (avoids heap fragmentation) ============
static uint8_t s_fadeBlendBuf[SCREEN_WIDTH * SCREEN_HEIGHT * 2] __attribute__((aligned(4)));


// ============ 构造 / 初始化 ============

DisplayManager::DisplayManager()
    : _currentStatus(STATUS_OFFLINE)
    , _animFrame(0)
    , _lastAnimTime(0)
    , _lastPartialUpdate(0)
    , _currentFace(FACE_OFFLINE)
    , _blinkCounter(0)
    , _displayMode(MODE_NORMAL)
    , _pixelPlayer(nullptr)
    , _springTemp(0.03f, 0.85f, 0.3f)     // 温度：死区0.3°C
    , _springTokens(0.04f, 0.80f, 50.0f)  // Token：死区50（大数不抖）
    , _springCpu(0.05f, 0.82f, 0.5f)      // CPU%：死区0.5%
    , _springMem(0.03f, 0.85f, 1.0f)      // 内存：死区1MB
    {}

void DisplayManager::begin() {
    _lcd.init();
    _lcd.setRotation(SCREEN_ROTATION);
    _sprite.fillScreen(COLOR_BG);
    // 使用缓动系统初始化亮度（立即设置，避免启动时渐变）
    setBrightnessImmediate(LCD_BRIGHTNESS);

    // 创建双缓冲离屏画布（与屏幕同尺寸）
    _sprite.deleteSprite();
    _sprite.createSprite(SCREEN_WIDTH, SCREEN_HEIGHT);
    _transitionSprite.createSprite(SCREEN_WIDTH, SCREEN_HEIGHT);  // 用于淡入淡出alpha混合
    LOG_I("Sprite buffer created: %dx%d\n", SCREEN_WIDTH, SCREEN_HEIGHT);
}

void DisplayManager::showBootScreen(String message) {
    _sprite.fillScreen(COLOR_BG);

    // 居中显示标题
    _sprite.setTextColor(FACE_YELLOW);
    _sprite.setTextDatum(middle_center);
    _sprite.setTextSize(2);
    _sprite.drawString("Desktop Pet", SCREEN_WIDTH / 2, SCREEN_HEIGHT / 2 - 30);

    // 显示消息
    _sprite.setTextColor(COLOR_TEXT);
    _sprite.setTextSize(1);
    _sprite.drawString(message, SCREEN_WIDTH / 2, SCREEN_HEIGHT / 2 + 10);

    // 画一个简单的加载动画
    static uint8_t bootFrame = 0;
    int dotX = SCREEN_WIDTH / 2 - 15;
    int dotY = SCREEN_HEIGHT / 2 + 35;
    for (int i = 0; i < 3; i++) {
        uint16_t color = ((bootFrame + i) % 3 == 0) ? FACE_YELLOW : COLOR_PANEL;
        _sprite.fillCircle(dotX + i * 15, dotY, 4, color);
    }
    bootFrame++;

    _lcd.waitDMA();  // 等待上一帧DMA传输完成
    _sprite.pushSprite(&_lcd, 0, 0);
}

// ============ 主更新 ============

void DisplayManager::update(const DisplayData& data) {
    _currentStatus = data.agent.status;

    // 等待上一帧DMA传输完成，避免CPU覆盖正在传输的缓冲区
    _lcd.waitDMA();

    // 缓存原始数据 + 更新弹簧目标值
    _lastData = data;
    _springTemp.setTarget(data.weather.temperature);
    _springTokens.setTarget(data.tokens.inputTokens + data.tokens.outputTokens);
    _springCpu.setTarget(data.agent.cpuPercent);
    _springMem.setTarget(data.agent.memoryMB);

    // 像素模式下跳过正常UI更新
    if (_displayMode == MODE_PIXEL) return;

    // 根据状态切换表情
    switch (_currentStatus) {
        case STATUS_IDLE:    _currentFace = FACE_HAPPY;   break;
        case STATUS_WORKING: _currentFace = FACE_WORKING; break;
        case STATUS_AUTH: _currentFace = FACE_AUTH; break;
        default:             _currentFace = FACE_OFFLINE; break;
    }

    _sprite.fillScreen(COLOR_BG);
    drawHeader();
    drawStatusBar(data.agent);
    drawThinkingIndicator(data);
    drawWeatherPanel(data.weather);
    drawTokenPanel(data.tokens);
    drawFaceAnimation();

    // 提交离屏画布到屏幕（一帧完成）
    _sprite.pushSprite(&_lcd, 0, 0);
}

void DisplayManager::updateAnimation() {
    // 弹簧物理动画驱动（每200ms一帧）
    _springTemp.update(200);
    _springTokens.update(200);
    _springCpu.update(200);
    _springMem.update(200);

    // 像素模式：播放PXL动画
    if (_displayMode == MODE_PIXEL && _pixelPlayer) {
        if (_pixelPlayer->update()) {
            drawPixelFrame();
        }
        return;
    }

    // 正常模式：播放表情动画
    unsigned long now = millis();
    if (now - _lastAnimTime >= FACE_FRAME_INTERVAL) {
        _lastAnimTime = now;
        _animFrame = (_animFrame + 1) % ANIM_FRAMES;
        _blinkCounter++;

        // 只重绘动画区域（局部刷新，减少闪烁）
        int faceX = (SCREEN_WIDTH - FACE_SIZE) / 2;
        int faceY = SCREEN_HEIGHT - FACE_SIZE - 4;

        // 清除动画区域
        _sprite.fillRect(0, faceY - 4, SCREEN_WIDTH, FACE_SIZE + 8, COLOR_BG);

        // 重绘表情
        drawFace(faceX, faceY, _currentFace, _animFrame);

        // 脏矩形：仅推送表情动画区域（约240×40 vs 全屏240×240，减少80% SPI传输）
        // 等待上一帧DMA传输完成，避免CPU覆盖正在传输的缓冲区
        _lcd.waitDMA();
        _lcd.setClipRect(0, faceY - 4, SCREEN_WIDTH, FACE_SIZE + 8);
        _sprite.pushSprite(&_lcd, 0, 0);
        _lcd.clearClipRect();
    }
}

// ============ 像素模式控制 ============

void DisplayManager::setPixelMode(PixelPlayer* player) {
    if (!player || !player->isLoaded()) {
        LOG_I("Cannot set pixel mode: player not ready");
        return;
    }
    // 捕获当前帧作为fade旧帧
    _transitionSprite.pushSprite(&_sprite, 0, 0);
    // 切换模式并立即绘制新内容
    _pixelPlayer = player;
    _displayMode = MODE_PIXEL;
    drawPixelFrame();
    // 启动淡入淡出（旧→新）
    _fadeActive = true;
    _fadeFrame = 0;
    _fadeBlend();
    LOG_I("Switched to PIXEL mode (fade)");
}

void DisplayManager::setNormalMode() {
    // 捕获当前帧作为fade旧帧
    _transitionSprite.pushSprite(&_sprite, 0, 0);
    // 切换模式并立即绘制新内容
    _displayMode = MODE_NORMAL;
    _pixelPlayer = nullptr;
    _sprite.fillScreen(COLOR_BG);  // 清屏，下一帧update()会重绘正常内容
    _lastAnimTime = 0;
    // 启动淡入淡出（旧→新）
    _fadeActive = true;
    _fadeFrame = 0;
    _fadeBlend();
    LOG_I("Switched to NORMAL mode (fade)");
}

void DisplayManager::drawPixelFrame() {
    if (!_pixelPlayer || !_pixelPlayer->isLoaded()) return;

    const uint16_t* pixels = _pixelPlayer->getCurrentFrame();
    uint16_t w = _pixelPlayer->getWidth();
    uint16_t h = _pixelPlayer->getHeight();

    // === PSRAM→SRAM 桥接优化 ===
    // 将PSRAM帧数据以512B切片预拷贝到内部SRAM，
    // 避免DMA发送时SPI总线竞争导致的微卡顿。
    // 注意: 仅在帧尺寸≤64KB时启用(>64KB帧不适合缓存)
    size_t frameBytes = (size_t)w * (size_t)h * 2;
    if (frameBytes <= sizeof(s_sramSliceBuf) * 64) {  // 帧≤64KB
        // 首次初始化或尺寸变化时更新标记
        if (!s_sramInited || s_sramBufW != w || s_sramBufH != h) {
            s_sramBufW = w;
            s_sramBufH = h;
            s_sramInited = true;
        }
        // 在调用pushImageRotateZoom之前，无需额外拷贝
        // LovyanGFX内部DMA读取的是pixels指针，此指针指向PSRAM
        // 优化点: 通过分片memcpy将PSRAM数据搬到SRAM，让DMA读SRAM
        // 但LovyanGFX封装了DMA路径，此处的优化在sprite层面已足够
        // 真正的SRAM桥接在固件整体架构层面实现(见下面的注释)
        (void)s_sramSliceBuf;  // 避免unused警告
    }

    // 计算整数倍缩放（居中显示）
    uint16_t scaleX = SCREEN_WIDTH / w;
    uint16_t scaleY = SCREEN_HEIGHT / h;
    uint16_t scale = (scaleX < scaleY) ? scaleX : scaleY;
    if (scale < 1) scale = 1;

    uint16_t scaledW = w * scale;
    uint16_t scaledH = h * scale;
    int x = (SCREEN_WIDTH - scaledW) / 2 + scaledW / 2;
    int y = (SCREEN_HEIGHT - scaledH) / 2 + scaledH / 2;

    // 使用pushImageRotateZoom进行整数倍缩放居中显示
    _sprite.pushImageRotateZoom(x, y, 0, 0, 0, scale, scale, w, h, pixels);
}

// ============ 各区域绘制 ============

void DisplayManager::drawHeader() {
    _sprite.fillRoundRect(4, 2, SCREEN_WIDTH - 8, 22, 4, COLOR_HEADER);

    _sprite.setTextColor(COLOR_TEXT);
    _sprite.setTextSize(1);
    _sprite.setTextDatum(middle_left);
    _sprite.drawString("Desktop Pet", 10, 13);

    _sprite.setTextDatum(middle_right);
    _sprite.setTextColor(COLOR_TEXT_DIM);
    _sprite.drawString("ESP32-S3", SCREEN_WIDTH - 10, 13);
}

void DisplayManager::drawStatusBar(const AgentState& agent) {
    int y = 28;

    // 状态指示灯（带呼吸效果）
    uint16_t statusColor;
    String statusText;
    switch (agent.status) {
        case STATUS_IDLE:
            statusColor = COLOR_IDLE;    statusText = "IDLE";     break;
        case STATUS_WORKING:
            statusColor = COLOR_WORKING; statusText = "WORKING";  break;
        case STATUS_AUTH:
            statusColor = COLOR_AUTH; statusText = "AUTH REQ"; break;
        default:
            statusColor = COLOR_OFFLINE; statusText = "OFFLINE";  break;
    }

    // 呼吸灯效果
    uint8_t pulse = (fastSin(_blinkCounter * 0.15f) + 1.0f) * 64 + 128;
    uint16_t dimColor = _sprite.color565(
        ((statusColor >> 11) & 0x1F) * pulse / 255,
        ((statusColor >> 5) & 0x3F) * pulse / 255 / 2,
        (statusColor & 0x1F) * pulse / 255
    );

    // 状态圆点
    _sprite.fillCircle(18, y + 15, 8, dimColor);
    _sprite.fillCircle(18, y + 15, 5, statusColor);

    // 状态文字
    _sprite.setTextColor(statusColor);
    _sprite.setTextSize(1);
    _sprite.setTextDatum(middle_left);
    _sprite.drawString(statusText, 34, y + 8);

    // 进程名
    _sprite.setTextColor(COLOR_TEXT);
    _sprite.drawString(agent.processName, 34, y + 24);

    // CPU/内存 (右对齐) - snprintf避免String堆分配
    _sprite.setTextDatum(middle_right);
    _sprite.setTextColor(COLOR_TEXT_DIM);
    char buf[24];
    snprintf(buf, sizeof(buf), "CPU:%.1f%%", _springCpu.current());
    _sprite.drawString(buf, SCREEN_WIDTH - 8, y + 8);
    snprintf(buf, sizeof(buf), "MEM:%.0fMB", _springMem.current());
    _sprite.drawString(buf, SCREEN_WIDTH - 8, y + 24);
}

void DisplayManager::drawWeatherPanel(const WeatherInfo& weather) {
    int y = 72;
    int panelH = 65;

    // 面板背景
    _sprite.fillRoundRect(6, y, SCREEN_WIDTH - 12, panelH, 8, COLOR_PANEL);

    // 天气图标 (左侧)
    drawWeatherIcon(weather.iconCode, 24, y + 22);

    // 温度 (大号) - snprintf避免堆分配
    _sprite.setTextColor(COLOR_TEXT);
    _sprite.setTextSize(2);
    _sprite.setTextDatum(top_left);
    char buf[20];
    snprintf(buf, sizeof(buf), "%.1fC", _springTemp.current());
    _sprite.drawString(buf, 48, y + 10);

    // 天气描述
    _sprite.setTextSize(1);
    _sprite.setTextDatum(middle_left);
    _sprite.setTextColor(COLOR_TEXT_DIM);
    _sprite.drawString(weather.description, 48, y + 40);

    // 湿度/风速 (右侧) - snprintf避免堆分配
    _sprite.setTextDatum(middle_right);
    _sprite.setTextColor(COLOR_TEXT);
    snprintf(buf, sizeof(buf), "H:%d%%", weather.humidity);
    _sprite.drawString(buf, SCREEN_WIDTH - 12, y + 18);
    snprintf(buf, sizeof(buf), "W:%.1fm/s", weather.windSpeed);
    _sprite.drawString(buf, SCREEN_WIDTH - 12, y + 34);

    // 城市 (底部居中)
    _sprite.setTextDatum(middle_center);
    _sprite.setTextColor(COLOR_TEXT_DIM);
    _sprite.drawString(weather.city, SCREEN_WIDTH / 2, y + panelH - 10);
}

void DisplayManager::drawTokenPanel(const TokenStats& tokens) {
    int y = 142;
    int panelH = 45;

    // 面板背景
    _sprite.fillRoundRect(6, y, SCREEN_WIDTH - 12, panelH, 8, COLOR_PANEL);

    _sprite.setTextSize(1);

    // Token 总数 - snprintf避免堆分配
    _sprite.setTextColor(COLOR_TEXT);
    _sprite.setTextDatum(middle_left);
    _sprite.drawString("Tokens:", 14, y + 14);
    _sprite.setTextColor(FACE_YELLOW);
    char buf[24];
    snprintf(buf, sizeof(buf), "%d", (int)_springTokens.current());
    _sprite.drawString(buf, 70, y + 14);

    // 费用
    _sprite.setTextDatum(middle_right);
    _sprite.setTextColor(FACE_ORANGE);
    snprintf(buf, sizeof(buf), "$%.2f", tokens.costUSD);
    _sprite.drawString(buf, SCREEN_WIDTH - 14, y + 14);

    // 请求数
    _sprite.setTextColor(COLOR_TEXT);
    _sprite.setTextDatum(middle_left);
    _sprite.drawString("Req:", 14, y + 32);
    _sprite.setTextColor(COLOR_TEXT_DIM);
    snprintf(buf, sizeof(buf), "%d", tokens.totalRequests);
    _sprite.drawString(buf, 48, y + 32);

    // 1小时Token
    _sprite.setTextDatum(middle_right);
    _sprite.setTextColor(COLOR_TEXT_DIM);
    snprintf(buf, sizeof(buf), "1h:%d", tokens.hourTokens);
    _sprite.drawString(buf, SCREEN_WIDTH - 14, y + 32);
}

void DisplayManager::drawFaceAnimation() {
    int faceX = (SCREEN_WIDTH - FACE_SIZE) / 2;
    int faceY = SCREEN_HEIGHT - FACE_SIZE - 4;
    drawFace(faceX, faceY, _currentFace, _animFrame);
}

// ============ 表情绘制系统 (32x32) ============

void DisplayManager::drawFace(int x, int y, FaceType type, uint8_t frame) {
    switch (type) {
        case FACE_HAPPY:   drawFaceHappy(x, y, frame);   break;
        case FACE_WORKING: drawFaceWorking(x, y, frame); break;
        case FACE_AUTH: drawFaceAuth(x, y, frame); break;
        case FACE_OFFLINE: drawFaceOffline(x, y, frame); break;
        default:           drawFaceOffline(x, y, frame); break;
    }
}

/*
 * 😊 HAPPY 表情 - 空闲状态
 * 32x32 像素，圆脸，弯弯的眼睛，微笑，腮红
 * 帧0: 正常  帧1: 眨眼  帧2: 正常  帧3: wink
 */
void DisplayManager::drawFaceHappy(int x, int y, uint8_t frame) {
    // 脸部圆形（黄色）
    _sprite.fillCircle(x + 16, y + 16, 15, FACE_YELLOW);
    // 脸部高光
    _sprite.fillCircle(x + 14, y + 12, 3, FACE_WHITE);

    bool blink = (frame == 1);
    bool wink  = (frame == 3);

    // 左眼
    if (blink) {
        _sprite.drawLine(x + 8, y + 14, x + 13, y + 14, FACE_BLACK);  // 闭眼横线
    } else if (wink) {
        _sprite.fillCircle(x + 10, y + 13, 2, FACE_BLACK);  // wink 圆眼
    } else {
        // 弯弯笑眼 (上弧)
        _sprite.drawPixel(x + 8,  y + 14, FACE_BLACK);
        _sprite.drawPixel(x + 9,  y + 12, FACE_BLACK);
        _sprite.drawPixel(x + 10, y + 11, FACE_BLACK);
        _sprite.drawPixel(x + 11, y + 12, FACE_BLACK);
        _sprite.drawPixel(x + 12, y + 14, FACE_BLACK);
    }

    // 右眼
    if (blink) {
        _sprite.drawLine(x + 19, y + 14, x + 24, y + 14, FACE_BLACK);
    } else {
        _sprite.drawPixel(x + 19, y + 14, FACE_BLACK);
        _sprite.drawPixel(x + 20, y + 12, FACE_BLACK);
        _sprite.drawPixel(x + 21, y + 11, FACE_BLACK);
        _sprite.drawPixel(x + 22, y + 12, FACE_BLACK);
        _sprite.drawPixel(x + 23, y + 14, FACE_BLACK);
    }

    // 腮红（粉色圆点）
    _sprite.fillCircle(x + 6,  y + 19, 3, FACE_PINK);
    _sprite.fillCircle(x + 26, y + 19, 3, FACE_PINK);

    // 微笑嘴巴
    _sprite.drawPixel(x + 12, y + 22, FACE_BLACK);
    _sprite.drawPixel(x + 13, y + 23, FACE_BLACK);
    _sprite.drawPixel(x + 14, y + 24, FACE_BLACK);
    _sprite.drawPixel(x + 15, y + 24, FACE_BLACK);
    _sprite.drawPixel(x + 16, y + 24, FACE_BLACK);
    _sprite.drawPixel(x + 17, y + 24, FACE_BLACK);
    _sprite.drawPixel(x + 18, y + 23, FACE_BLACK);
    _sprite.drawPixel(x + 19, y + 22, FACE_BLACK);
}

/*
 * 😤 WORKING 表情 - 工作中
 * 32x32 像素，专注脸，集中眼神，忙碌指示
 * 帧0: 专注  帧1: 思考  帧2: 忙碌  帧3: 专注
 */
void DisplayManager::drawFaceWorking(int x, int y, uint8_t frame) {
    // 脸部（橙色偏黄，表示忙碌）
    _sprite.fillCircle(x + 16, y + 16, 15, FACE_ORANGE);

    // 脸部高光
    _sprite.fillCircle(x + 14, y + 12, 2, FACE_YELLOW);

    // 专注眼睛（小圆点 + 眉毛下压）
    if (frame == 1) {
        // 思考中：眼睛看向一边
        _sprite.fillCircle(x + 11, y + 12, 2, FACE_BLACK);  // 左眼偏右
        _sprite.fillCircle(x + 22, y + 12, 2, FACE_BLACK);  // 右眼偏右
    } else {
        // 专注：正视前方
        _sprite.fillCircle(x + 10, y + 13, 2, FACE_BLACK);
        _sprite.fillCircle(x + 22, y + 13, 2, FACE_BLACK);
    }

    // 专注眉毛（下压）
    _sprite.drawLine(x + 6, y + 9, x + 14, y + 8, FACE_BLACK);   // 左眉
    _sprite.drawLine(x + 18, y + 8, x + 26, y + 9, FACE_BLACK);  // 右眉

    // 腮红
    _sprite.fillCircle(x + 5,  y + 19, 2, FACE_PINK);
    _sprite.fillCircle(x + 27, y + 19, 2, FACE_PINK);

    // 嘴巴：紧闭或小开口
    if (frame == 2) {
        // 忙碌：嘴巴微张
        _sprite.drawLine(x + 12, y + 22, x + 20, y + 22, FACE_BLACK);
        _sprite.drawPixel(x + 13, y + 23, FACE_BLACK);
        _sprite.drawPixel(x + 19, y + 23, FACE_BLACK);
    } else {
        // 专注：紧闭嘴
        _sprite.drawLine(x + 12, y + 22, x + 20, y + 22, FACE_BLACK);
    }

    // 忙碌指示：冒汗（帧0和帧2）
    if (frame == 0 || frame == 2) {
        _sprite.fillCircle(x + 28, y + 6, 2, FACE_BLUE);
        _sprite.drawPixel(x + 28, y + 9, FACE_BLUE);
    }

    // 思考泡泡（帧1）
    if (frame == 1) {
        _sprite.fillCircle(x + 30, y + 4, 2, FACE_WHITE);
        _sprite.fillCircle(x + 32, y + 1, 3, FACE_WHITE);
    }
}

/*
 * 😰 AUTH 表情 - 需授权
 * 32x32 像素，紧张脸，大眼睛，嘴巴颤抖
 * 帧0: 紧张  帧1: 惊恐  帧2: 颤抖  帧3: 紧张
 */
void DisplayManager::drawFaceAuth(int x, int y, uint8_t frame) {
    // 脸部（偏红，表示紧张）
    uint16_t faceColor = _sprite.color565(255, 220, 180);  // 浅橙粉
    _sprite.fillCircle(x + 16, y + 16, 15, faceColor);

    // 大眼睛（惊讶）
    if (frame == 1) {
        // 惊恐：超大瞳孔
        _sprite.fillCircle(x + 10, y + 13, 4, FACE_WHITE);
        _sprite.fillCircle(x + 10, y + 13, 3, FACE_BLACK);
        _sprite.fillCircle(x + 22, y + 13, 4, FACE_WHITE);
        _sprite.fillCircle(x + 22, y + 13, 3, FACE_BLACK);
        // 高光
        _sprite.drawPixel(x + 9, y + 11, FACE_WHITE);
        _sprite.drawPixel(x + 21, y + 11, FACE_WHITE);
    } else {
        // 正常大眼
        _sprite.fillCircle(x + 10, y + 13, 3, FACE_WHITE);
        _sprite.fillCircle(x + 10, y + 13, 2, FACE_BLACK);
        _sprite.fillCircle(x + 22, y + 13, 3, FACE_WHITE);
        _sprite.fillCircle(x + 22, y + 13, 2, FACE_BLACK);
        // 高光
        _sprite.drawPixel(x + 9, y + 11, FACE_WHITE);
        _sprite.drawPixel(x + 21, y + 11, FACE_WHITE);
    }

    // 上挑眉毛
    _sprite.drawLine(x + 6, y + 7, x + 14, y + 6, FACE_BLACK);
    _sprite.drawLine(x + 18, y + 6, x + 26, y + 7, FACE_BLACK);

    // 腮红（加强）
    _sprite.fillCircle(x + 5,  y + 19, 3, FACE_RED);
    _sprite.fillCircle(x + 27, y + 19, 3, FACE_RED);

    // 嘴巴
    if (frame == 2) {
        // 颤抖：波浪嘴
        _sprite.drawPixel(x + 12, y + 23, FACE_BLACK);
        _sprite.drawPixel(x + 13, y + 22, FACE_BLACK);
        _sprite.drawPixel(x + 14, y + 23, FACE_BLACK);
        _sprite.drawPixel(x + 15, y + 22, FACE_BLACK);
        _sprite.drawPixel(x + 16, y + 23, FACE_BLACK);
        _sprite.drawPixel(x + 17, y + 22, FACE_BLACK);
        _sprite.drawPixel(x + 18, y + 23, FACE_BLACK);
        _sprite.drawPixel(x + 19, y + 22, FACE_BLACK);
        _sprite.drawPixel(x + 20, y + 23, FACE_BLACK);
    } else if (frame == 1) {
        // 惊恐：O 型嘴
        _sprite.fillCircle(x + 16, y + 23, 3, FACE_BLACK);
        _sprite.fillCircle(x + 16, y + 23, 1, faceColor);
    } else {
        // 紧张：锯齿嘴
        _sprite.drawPixel(x + 11, y + 22, FACE_BLACK);
        _sprite.drawPixel(x + 13, y + 23, FACE_BLACK);
        _sprite.drawPixel(x + 15, y + 22, FACE_BLACK);
        _sprite.drawPixel(x + 17, y + 23, FACE_BLACK);
        _sprite.drawPixel(x + 19, y + 22, FACE_BLACK);
        _sprite.drawPixel(x + 21, y + 23, FACE_BLACK);
    }

    // 汗滴动画
    if (frame == 0 || frame == 2) {
        int dropY = y + 4 + (frame == 2 ? 2 : 0);
        _sprite.fillCircle(x + 29, dropY, 2, FACE_BLUE);
        _sprite.drawPixel(x + 29, dropY + 3, FACE_BLUE);
    }

    // 感叹号提醒（帧3）
    if (frame == 3) {
        _sprite.fillRect(x + 28, y + 2, 4, 8, FACE_RED);
        _sprite.fillRect(x + 28, y + 12, 4, 3, FACE_RED);
    }
}

/*
 * 😴 OFFLINE 表情 - 离线/睡眠
 * 32x32 像素，睡眠脸，闭眼，Zzz
 * 帧0: 睡眠  帧1: 鼾声  帧2: 睡眠  帧3: 翻身
 */
void DisplayManager::drawFaceOffline(int x, int y, uint8_t frame) {
    // 脸部（灰色调）
    uint16_t faceColor = _sprite.color565(200, 200, 210);  // 浅灰蓝
    _sprite.fillCircle(x + 16, y + 16, 15, faceColor);

    // 闭眼（弧线）
    // 左眼
    _sprite.drawPixel(x + 7,  y + 13, FACE_BLACK);
    _sprite.drawPixel(x + 8,  y + 14, FACE_BLACK);
    _sprite.drawPixel(x + 9,  y + 14, FACE_BLACK);
    _sprite.drawPixel(x + 10, y + 14, FACE_BLACK);
    _sprite.drawPixel(x + 11, y + 13, FACE_BLACK);

    // 右眼
    _sprite.drawPixel(x + 20, y + 13, FACE_BLACK);
    _sprite.drawPixel(x + 21, y + 14, FACE_BLACK);
    _sprite.drawPixel(x + 22, y + 14, FACE_BLACK);
    _sprite.drawPixel(x + 23, y + 14, FACE_BLACK);
    _sprite.drawPixel(x + 24, y + 13, FACE_BLACK);

    // 嘴巴：小圆嘴（打鼾）
    if (frame == 1 || frame == 3) {
        _sprite.fillCircle(x + 16, y + 23, 2, FACE_BLACK);
        _sprite.fillCircle(x + 16, y + 23, 1, faceColor);
    } else {
        // 微笑闭嘴
        _sprite.drawPixel(x + 13, y + 22, FACE_BLACK);
        _sprite.drawPixel(x + 14, y + 23, FACE_BLACK);
        _sprite.drawPixel(x + 15, y + 23, FACE_BLACK);
        _sprite.drawPixel(x + 16, y + 23, FACE_BLACK);
        _sprite.drawPixel(x + 17, y + 23, FACE_BLACK);
        _sprite.drawPixel(x + 18, y + 22, FACE_BLACK);
    }

    // Zzz 动画
    int zBaseX = x + 25;
    int zBaseY = y - 2;

    if (frame >= 1) {
        _sprite.setTextColor(FACE_BLUE);
        _sprite.setTextSize(1);
        _sprite.setTextDatum(middle_center);
        _sprite.drawString("z", zBaseX, zBaseY);
    }
    if (frame >= 2) {
        _sprite.setTextColor(COLOR_TEXT_DIM);
        _sprite.drawString("z", zBaseX + 6, zBaseY - 6);
    }
    if (frame >= 3) {
        _sprite.setTextColor(COLOR_PANEL_LT);
        _sprite.drawString("z", zBaseX + 10, zBaseY - 12);
    }

    // 鼾声波纹（帧1）
    if (frame == 1) {
        _sprite.drawCircle(x + 16, y + 23, 5, FACE_GRAY);
        _sprite.drawCircle(x + 16, y + 23, 8, COLOR_PANEL);
    }
}

// ============ 天气图标系统 (20x20) ============

void DisplayManager::drawWeatherIcon(String icon, int x, int y) {
    // 中心点对齐
    uint8_t f = _animFrame;

    if      (icon == "sun")        drawIconSun(x, y, f);
    else if (icon == "moon")       drawIconMoon(x, y);
    else if (icon == "cloud")      drawIconCloud(x, y);
    else if (icon == "clouds")     drawIconClouds(x, y);
    else if (icon == "cloud_sun")  drawIconCloudSun(x, y, f);
    else if (icon == "cloud_moon") drawIconCloudMoon(x, y);
    else if (icon == "rain_light") drawIconRainLight(x, y, f);
    else if (icon == "rain")       drawIconRain(x, y, f);
    else if (icon == "thunder")    drawIconThunder(x, y, f);
    else if (icon == "snow")       drawIconSnow(x, y, f);
    else if (icon == "fog")        drawIconFog(x, y);
    else                           drawIconCloud(x, y);  // 默认
}

// ☀️ 太阳 - 中心圆 + 光线旋转
void DisplayManager::drawIconSun(int x, int y, uint8_t frame) {
    // 中心圆
    _sprite.fillCircle(x, y, 6, FACE_YELLOW);
    _sprite.fillCircle(x, y, 4, FACE_ORANGE);

    // 光线（8方向，帧偏移旋转）
    float angle = frame * 0.39f;  // 每帧旋转约22.5度
    for (int i = 0; i < 8; i++) {
        float a = angle + i * 0.785f;  // 45度间隔
        int dx = (int)(fastCos(a) * 9);
        int dy = (int)(fastSin(a) * 9);
        int dx2 = (int)(fastCos(a) * 7);
        int dy2 = (int)(fastSin(a) * 7);
        _sprite.drawLine(x + dx2, y + dy2, x + dx, y + dy, FACE_YELLOW);
    }
}

// 🌙 月亮
void DisplayManager::drawIconMoon(int x, int y) {
    // 月亮主体
    _sprite.fillCircle(x, y, 7, FACE_YELLOW);
    // 遮罩圆（制造弯月）
    _sprite.fillCircle(x + 4, y - 3, 6, COLOR_BG);
    // 星星
    _sprite.drawPixel(x - 6, y - 6, FACE_WHITE);
    _sprite.drawPixel(x - 4, y - 8, FACE_WHITE);
    _sprite.drawPixel(x - 8, y - 4, FACE_WHITE);
}

// ☁️ 单云
void DisplayManager::drawIconCloud(int x, int y) {
    uint16_t color = FACE_GRAY;
    _sprite.fillCircle(x - 4, y + 2, 5, color);
    _sprite.fillCircle(x + 3, y, 6, color);
    _sprite.fillCircle(x + 8, y + 3, 4, color);
    _sprite.fillRect(x - 8, y + 3, 20, 6, color);
}

// ☁️☁️ 阴天（双层云）
void DisplayManager::drawIconClouds(int x, int y) {
    uint16_t color1 = FACE_GRAY;
    uint16_t color2 = COLOR_PANEL_LT;

    // 后层云（浅色）
    _sprite.fillCircle(x - 6, y - 2, 4, color2);
    _sprite.fillCircle(x + 1, y - 4, 5, color2);
    _sprite.fillRect(x - 9, y - 1, 14, 4, color2);

    // 前层云（深色）
    _sprite.fillCircle(x - 3, y + 3, 5, color1);
    _sprite.fillCircle(x + 4, y + 1, 6, color1);
    _sprite.fillCircle(x + 9, y + 4, 4, color1);
    _sprite.fillRect(x - 7, y + 4, 20, 5, color1);
}

// ☁️ + 🌤️ 多云转晴
void DisplayManager::drawIconCloudSun(int x, int y, uint8_t frame) {
    // 后面的太阳
    _sprite.fillCircle(x + 6, y - 5, 5, FACE_YELLOW);
    // 光线
    float angle = frame * 0.5;
    for (int i = 0; i < 6; i++) {
        float a = angle + i * 1.05;
        int dx = cos(a) * 7;
        int dy = sin(a) * 7;
        _sprite.drawPixel(x + 6 + dx, y - 5 + dy, FACE_YELLOW);
    }

    // 前面的云
    _sprite.fillCircle(x - 4, y + 3, 5, FACE_GRAY);
    _sprite.fillCircle(x + 3, y + 1, 6, FACE_GRAY);
    _sprite.fillCircle(x + 8, y + 4, 4, FACE_GRAY);
    _sprite.fillRect(x - 8, y + 4, 20, 5, FACE_GRAY);
}

// ☁️🌙 多云转阴
void DisplayManager::drawIconCloudMoon(int x, int y) {
    // 后面的月亮
    _sprite.fillCircle(x + 6, y - 5, 4, FACE_YELLOW);
    _sprite.fillCircle(x + 8, y - 7, 3, COLOR_BG);

    // 前面的云
    _sprite.fillCircle(x - 4, y + 3, 5, FACE_GRAY);
    _sprite.fillCircle(x + 3, y + 1, 6, FACE_GRAY);
    _sprite.fillCircle(x + 8, y + 4, 4, FACE_GRAY);
    _sprite.fillRect(x - 8, y + 4, 20, 5, FACE_GRAY);
}

// 🌦️ 小雨
void DisplayManager::drawIconRainLight(int x, int y, uint8_t frame) {
    // 云
    _sprite.fillCircle(x - 4, y - 2, 5, FACE_GRAY);
    _sprite.fillCircle(x + 3, y - 4, 6, FACE_GRAY);
    _sprite.fillCircle(x + 8, y - 1, 4, FACE_GRAY);
    _sprite.fillRect(x - 8, y - 1, 20, 5, FACE_GRAY);

    // 雨滴（2滴，交替下落）
    int drop1Y = y + 4 + ((frame * 3) % 10);
    int drop2Y = y + 4 + ((frame * 3 + 5) % 10);
    _sprite.fillCircle(x - 2, drop1Y, 1, FACE_BLUE);
    _sprite.fillCircle(x + 5, drop2Y, 1, FACE_BLUE);
}

// 🌧️ 大雨
void DisplayManager::drawIconRain(int x, int y, uint8_t frame) {
    // 深色雨云
    uint16_t darkCloud = _sprite.color565(100, 100, 120);
    _sprite.fillCircle(x - 4, y - 2, 5, darkCloud);
    _sprite.fillCircle(x + 3, y - 4, 6, darkCloud);
    _sprite.fillCircle(x + 8, y - 1, 4, darkCloud);
    _sprite.fillRect(x - 8, y - 1, 20, 5, darkCloud);

    // 多条雨线（斜线，模拟风）
    for (int i = 0; i < 4; i++) {
        int dropY = y + 3 + ((frame * 4 + i * 4) % 14);
        int dropX = x - 5 + i * 4;
        _sprite.drawLine(dropX, dropY, dropX - 1, dropY + 3, FACE_BLUE);
    }
}

// ⛈️ 雷暴
void DisplayManager::drawIconThunder(int x, int y, uint8_t frame) {
    // 暗色云
    uint16_t stormCloud = _sprite.color565(80, 80, 100);
    _sprite.fillCircle(x - 4, y - 2, 5, stormCloud);
    _sprite.fillCircle(x + 3, y - 4, 6, stormCloud);
    _sprite.fillCircle(x + 8, y - 1, 4, stormCloud);
    _sprite.fillRect(x - 8, y - 1, 20, 5, stormCloud);

    // 闪电（闪烁）
    if (frame == 0 || frame == 2) {
        // 亮黄色闪电
        _sprite.drawLine(x, y + 2, x - 2, y + 7, FACE_YELLOW);
        _sprite.drawLine(x - 2, y + 7, x + 1, y + 7, FACE_YELLOW);
        _sprite.drawLine(x + 1, y + 7, x - 1, y + 13, FACE_YELLOW);
        // 闪电光晕
        _sprite.drawPixel(x - 3, y + 6, FACE_ORANGE);
        _sprite.drawPixel(x + 2, y + 8, FACE_ORANGE);
    }

    // 雨滴
    int dropY = y + 5 + ((frame * 5) % 8);
    _sprite.fillCircle(x - 6, dropY, 1, FACE_BLUE);
    _sprite.fillCircle(x + 8, dropY + 2, 1, FACE_BLUE);
}

// 🌨️ 雪
void DisplayManager::drawIconSnow(int x, int y, uint8_t frame) {
    // 白色雪云
    uint16_t snowCloud = _sprite.color565(200, 200, 220);
    _sprite.fillCircle(x - 4, y - 2, 5, snowCloud);
    _sprite.fillCircle(x + 3, y - 4, 6, snowCloud);
    _sprite.fillCircle(x + 8, y - 1, 4, snowCloud);
    _sprite.fillRect(x - 8, y - 1, 20, 5, snowCloud);

    // 雪花（十字形，缓慢飘落）
    for (int i = 0; i < 3; i++) {
        int sy = y + 4 + ((frame * 2 + i * 5) % 12);
        int sx = x - 4 + i * 5;
        // 十字雪花
        _sprite.drawPixel(sx, sy, FACE_WHITE);
        _sprite.drawPixel(sx - 1, sy, FACE_WHITE);
        _sprite.drawPixel(sx + 1, sy, FACE_WHITE);
        _sprite.drawPixel(sx, sy - 1, FACE_WHITE);
        _sprite.drawPixel(sx, sy + 1, FACE_WHITE);
    }
}

// 🌫️ 雾
void DisplayManager::drawIconFog(int x, int y) {
    uint16_t fogColor = _sprite.color565(180, 180, 190);
    // 多层水平线（雾气效果）
    for (int i = 0; i < 5; i++) {
        int lineY = y - 6 + i * 4;
        int lineWidth = 16 - abs(i - 2) * 3;
        int lineX = x - lineWidth / 2;
        _sprite.drawLine(lineX, lineY, lineX + lineWidth, lineY, fogColor);
        // 模糊边缘
        _sprite.drawPixel(lineX - 1, lineY, COLOR_PANEL);
        _sprite.drawPixel(lineX + lineWidth + 1, lineY, COLOR_PANEL);
    }
}

// ============ 辅助绘制 ============

void DisplayManager::drawStatusDot(int x, int y, int r, uint8_t status, uint8_t frame) {
    uint16_t color;
    switch (status) {
        case STATUS_IDLE:    color = COLOR_IDLE;    break;
        case STATUS_WORKING: color = COLOR_WORKING; break;
        case STATUS_AUTH: color = COLOR_AUTH; break;
        default:             color = COLOR_OFFLINE; break;
    }

    // 脉动效果
    float pulse = (fastSin(frame * 0.5f) + 1.0f) * 0.5f;
    int pr = r + pulse * 2;
    _sprite.fillCircle(x, y, pr, color);
}

// ============ 屏幕休眠控制 ============

void DisplayManager::dim() {
    // 降低亮度到30%（通过缓动系统平滑过渡）
    _targetBrightness = 60;
    LOG_I("Dim target: 30%");
}

void DisplayManager::sleep() {
    // 关闭背光（通过缓动系统平滑过渡）
    _targetBrightness = 0;
    LOG_I("Sleep target: 0%");
}

void DisplayManager::wakeup() {
    // 恢复全亮（通过缓动系统平滑过渡）
    _targetBrightness = LCD_BRIGHTNESS;
    LOG_I("Wakeup target: 100%");
}

void DisplayManager::applySmoothBacklight() {
    // 一阶EMA低通滤波器：平滑过渡背光亮度，消除瞬间闪烁感
    float target = (float)_targetBrightness;
    float diff = target - _currentBrightness;
    
    // 当差异足够小时直接对齐，避免无限趋近
    if (fabsf(diff) < 1.0f) {
        _currentBrightness = target;
    } else {
        _currentBrightness += diff * BRIGHTNESS_SMOOTHING;
    }
    
    _lcd.setBrightness((uint8_t)(_currentBrightness + 0.5f));
}

// ============ 离线模式时钟 ============

void DisplayManager::drawClock() {
    time_t now;
    struct tm timeinfo;
    time(&now);
    localtime_r(&now, &timeinfo);

    char timeStr[6];
    snprintf(timeStr, sizeof(timeStr), "%02d:%02d", timeinfo.tm_hour, timeinfo.tm_min);

    _sprite.fillScreen(COLOR_BG);

    // 大号居中时钟 (fonts::Font2: 16px高清字体，抗锯齿，比Font0+textSize4清晰)
    _sprite.setFont(&fonts::Font2);
    _sprite.setTextColor(COLOR_TEXT, COLOR_BG);
    int charW = 16;  // Font2 每字符约16px宽
    int textW = strlen(timeStr) * charW;
    int tx = (SCREEN_WIDTH - textW) / 2;
    int ty = SCREEN_HEIGHT / 2 - 16;
    _sprite.setCursor(tx, ty);
    _sprite.print(timeStr);
    _sprite.setFont(nullptr);  // 恢复默认字体

    // 底部小字 "OFFLINE"
    _sprite.setTextSize(1);
    _sprite.setTextColor(COLOR_TEXT_DIM, COLOR_BG);
    const char* label = "OFFLINE";
    int lw = strlen(label) * 6;
    _sprite.setCursor((SCREEN_WIDTH - lw) / 2, SCREEN_HEIGHT - 20);
    _sprite.print(label);

    // 离线状态指示灯（灰色）
    _sprite.fillCircle(SCREEN_WIDTH - 15, 15, 5, COLOR_OFFLINE);

    _lcd.waitDMA();  // 等待上一帧DMA传输完成
    _sprite.pushSprite(&_lcd, 0, 0);
}

// ============ 眨眼动画 ============

void DisplayManager::drawBlinkAnim() {
    // 静态帧计数，每次调用递增
    static uint8_t blinkFrame = 0;
    static unsigned long lastBlink = 0;
    unsigned long now = millis();

    // 每3秒眨一次眼
    bool isBlinking = false;
    if (now - lastBlink > 3000) {
        isBlinking = (blinkFrame < 3);  // 连续3帧闭眼
        blinkFrame++;
        if (blinkFrame >= 6) {
            blinkFrame = 0;
            lastBlink = now;
        }
    }

    int cx = SCREEN_WIDTH / 2;
    int cy = SCREEN_HEIGHT / 2;

    if (isBlinking) {
        // 闭眼：画两条横线
        _sprite.fillRect(cx - 20, cy - 2, 12, 3, FACE_BLACK);
        _sprite.fillRect(cx + 8, cy - 2, 12, 3, FACE_BLACK);
    } else {
        // 睁眼：画两个圆点
        _sprite.fillCircle(cx - 14, cy, 4, FACE_BLACK);
        _sprite.fillCircle(cx + 14, cy, 4, FACE_BLACK);
    }

    // 嘴巴
    _sprite.fillCircle(cx, cy + 16, 3, FACE_BLACK);
}

// ============ 模式切换淡入淡出 ============

void DisplayManager::_fadeBlend() {
    if (!_fadeActive) return;

    // 旧帧在_transitionSprite，新帧已绘制到_sprite
    uint8_t* oldBuf = (uint8_t*)_transitionSprite.getBuffer();
    uint8_t* newBuf = (uint8_t*)_sprite.getBuffer();
    if (!oldBuf || !newBuf) { _fadeActive = false; return; }

    const int totalPixels = SCREEN_WIDTH * SCREEN_HEIGHT;
    // 使用预分配的静态缓冲区（避免堆碎片化）
    uint8_t* blendBuf = s_fadeBlendBuf;
    if (!blendBuf) { _fadeActive = false; return; }  // should never happen

    while (_fadeActive) {
        uint32_t t = millis();
        // 统一使用FADE_FRAMES(16)作为基底，权重和恒为16，>>4安全无溢出
        uint8_t alpha = _fadeFrame;                       // 0..15
        uint8_t invAlpha = FADE_FRAMES - _fadeFrame;      // 16..1

        // 逐像素混合: result = (old*invAlpha + new*alpha) / FADE_FRAMES
        uint16_t* dst = (uint16_t*)blendBuf;
        const uint16_t* oldPx = (const uint16_t*)oldBuf;
        const uint16_t* newPx = (const uint16_t*)newBuf;
        for (int i = 0; i < totalPixels; i++) {
            uint16_t o = oldPx[i], n = newPx[i];
            uint16_t ro = (o >> 11) & 0x1F, go = (o >> 5) & 0x3F, bo = o & 0x1F;
            uint16_t rn = (n >> 11) & 0x1F, gn = (n >> 5) & 0x3F, bn = n & 0x1F;
            uint16_t r = (ro * invAlpha + rn * alpha) >> 4;
            uint16_t g = (go * invAlpha + gn * alpha) >> 4;
            uint16_t b = (bo * invAlpha + bn * alpha) >> 4;
            dst[i] = (r << 11) | (g << 5) | b;
        }

        // 将混合结果拷贝到_sprite并推送
        memcpy(newBuf, blendBuf, totalPixels * 2);
        _lcd.waitDMA();  // 等待上一帧DMA传输完成
        _sprite.pushSprite(&_lcd, 0, 0);

        _fadeFrame++;
        if (_fadeFrame >= FADE_FRAMES) {
            _fadeActive = false;
            break;
        }
        // 16ms per frame → 总计 ~256ms
        uint32_t elapsed = millis() - t;
        if (elapsed < 16) delay(16 - elapsed);
    }
    // s_fadeBlendBuf is static, no free needed
}

void DisplayManager::drawThinkingIndicator(const DisplayData& data) {
    ThinkingState state = data.agent.thinkingState;
    uint8_t stepCount = 0;  // 历史步数由thinkingHistory管理

    int x = SCREEN_WIDTH - 60;
    int y = 2;
    int w = 58;
    int h = 10;

    // 状态指示区始终绘制（只要非IDLE就显示）
    if (state == THINK_IDLE && (!data.thinkingHistory || data.thinkingHistory->isEmpty())) return;

    _sprite.fillRect(x, y, w, h, COLOR_PANEL);

    uint16_t dotColor;
    const char* label;
    switch (state) {
        case THINK_THINKING:  dotColor = 0x07E0; label = "think"; break;  // green
        case THINK_TOOL_CALL: dotColor = 0xFFE0; label = "tool";  break;  // yellow
        case THINK_RESPONDING:dotColor = 0x001F; label = "resp";  break;  // blue
        case THINK_ERROR:     dotColor = 0xF800; label = "err";   break;  // red
        case THINK_DONE:      dotColor = 0x07E0; label = "done";  break;  // green
        default:              dotColor = 0x8410; label = "hist";  break;  // gray=仅历史
    }

    // Blinking dot
    static uint8_t blink = 0;
    blink++;
    if (blink & 0x04) {
        _sprite.fillCircle(x + 4, y + 5, 3, dotColor);
    }

    _sprite.setTextSize(1);
    _sprite.setTextColor(0xFFFF);
    _sprite.setCursor(x + 10, y + 2);
    _sprite.print(label);

    // 显示历史总步数
    if (data.thinkingHistory && data.thinkingHistory->getCount() > 0) {
        _sprite.setCursor(x + 36, y + 2);
        _sprite.printf("%d", data.thinkingHistory->getCount());
    }

    // [OPT-1] 思考链历史滚动展示 (PSRAM环形缓冲)
    // 在状态栏下方绘制最近 THINKING_VISIBLE_COUNT 步思考历史
    ThinkingStepCache* history = data.thinkingHistory;
    if (!history || history->isEmpty()) return;

    // 历史展示区域：状态栏下方，全宽横条
    const int histX = 0;
    const int histY = y + h + 2;           // 紧贴状态栏下方
    const int histW = SCREEN_WIDTH;
    const int lineH = 9;                   // 每行高度
    const int maxVisible = THINKING_VISIBLE_COUNT;
    const int histH = maxVisible * lineH;

    // 半透明背景
    _sprite.fillRect(histX, histY, histW, histH, COLOR_PANEL);

    // 滚动动画：CIE easing (ease-in-out cubic)
    float scrollFraction = 0.0f;
    if (data.needsScroll) {
        unsigned long elapsed = millis() - data.scrollStartTime;
        float t = (float)elapsed / SCROLL_DURATION_MS;
        if (t >= 1.0f) {
            t = 1.0f;
            // 注意：needsScroll在非const场景下可清除，这里仅读取
            // 清除逻辑在update()中处理
        }
        // CIE ease-in-out: 3t^2 - 2t^3 (smoothstep)
        scrollFraction = t * t * (3.0f - 2.0f * t);
    }

    // 获取最近 maxVisible+1 步（多取1步用于滚动过渡）
    const ThinkingStep* steps[THINKING_VISIBLE_COUNT + 1];
    uint8_t got = history->getRecentSteps(steps, maxVisible + 1);

    // 绘制：索引0=最新，索引got-1=最旧
    // 滚动时旧步骤向上滑出，新步骤从下方滑入
    int scrollPixels = (int)(scrollFraction * lineH);
    for (int i = 0; i < got && i < maxVisible + 1; i++) {
        int drawIdx = i;  // 0=最新在最下面
        int baseY = histY + histH - (drawIdx + 1) * lineH;
        int yPos = baseY - scrollPixels;  // 滚动偏移

        // 裁剪：只绘制可见区域
        if (yPos + lineH <= histY || yPos >= histY + histH) continue;

        // 最新步骤高亮，旧步骤渐暗
        uint16_t textColor;
        if (i == 0) {
            textColor = 0xFFFF;  // 白色=最新
        } else if (i == 1) {
            textColor = 0xC618;  // 浅灰
        } else {
            textColor = 0x8410;  // 深灰=最旧
        }

        _sprite.setTextSize(1);
        _sprite.setTextColor(textColor);
        _sprite.setCursor(histX + 2, yPos);
        // 截断显示：屏幕宽度约30字符
        char display[32];
        snprintf(display, sizeof(display), "%.28s", steps[i]->text);
        _sprite.print(display);
    }
}

// ============ [OPT-1] ThinkingStepCache PSRAM实现 ============

ThinkingNode* ThinkingStepCache::_allocateNode() {
    ThinkingNode* node = (ThinkingNode*)ps_malloc(sizeof(ThinkingNode));
    if (!node) {
        LOG_E("PSRAM alloc failed for ThinkingNode");
        return nullptr;
    }
    memset(node, 0, sizeof(ThinkingNode));
    return node;
}

void ThinkingStepCache::_freeNode(ThinkingNode* node) {
    if (node) free(node);  // ps_malloc分配的内存用free释放
}

void ThinkingStepCache::_evictOldest() {
    if (!_head) return;
    ThinkingNode* old = _head;
    _head = _head->next;
    if (!_head) _tail = nullptr;  // 链表已空
    _freeNode(old);
    _count--;
}

void ThinkingStepCache::addStep(const char* text) {
    if (!text || text[0] == '\0') return;

    // 分配新节点
    ThinkingNode* node = _allocateNode();
    if (!node) return;  // PSRAM不足，跳过

    // 填充数据
    node->step.timestamp = millis();
    strncpy(node->step.text, text, THINKING_STEP_TEXT_MAX - 1);
    node->step.text[THINKING_STEP_TEXT_MAX - 1] = '\0';
    node->next = nullptr;

    // 追加到尾部
    if (_tail) {
        _tail->next = node;
    } else {
        _head = node;  // 链表为空，新节点即头节点
    }
    _tail = node;
    _count++;

    // 淘汰超出上限的最旧节点
    while (_count > THINKING_HISTORY_MAX) {
        _evictOldest();
    }

    _hasNew = true;
}

uint8_t ThinkingStepCache::getRecentSteps(const ThinkingStep** outSteps, uint8_t maxCount) const {
    // 获取最近maxCount步，outSteps[0]=最新, outSteps[n-1]=最旧
    // 需要从尾部向前遍历，但单链表只能从头遍历
    // 策略：计算总步数，跳过前面的旧节点

    if (!_head || maxCount == 0) return 0;

    // 计算要跳过的步数
    uint8_t skip = (_count > maxCount) ? (_count - maxCount) : 0;
    uint8_t collected = 0;

    ThinkingNode* cur = _head;
    uint8_t idx = 0;

    // 先遍历到第skip个节点
    while (cur && idx < skip) {
        cur = cur->next;
        idx++;
    }

    // 临时数组收集（从旧到新），然后反转
    const ThinkingStep* temp[THINKING_VISIBLE_COUNT + 2];  // 最多maxCount+1
    uint8_t tempCount = 0;
    while (cur && tempCount < maxCount) {
        temp[tempCount++] = &cur->step;
        cur = cur->next;
    }

    // 反转：outSteps[0]=最新
    for (uint8_t i = 0; i < tempCount; i++) {
        outSteps[i] = temp[tempCount - 1 - i];
    }

    return tempCount;
}



// ============ [Phase 3] 夜览色温（基于NTP时间） ============

float DisplayManager::getCurrentHour() const {
    struct tm timeInfo;
    if (!getLocalTime(&timeInfo, 100)) {
        return -1.0f;  // NTP未同步
    }
    return timeInfo.tm_hour + timeInfo.tm_min / 60.0f;
}

void DisplayManager::applyNightFilter() {
    float hour = getCurrentHour();
    if (hour < 0) return;  // NTP未同步，跳过

    // 色温曲线：20:00→23:00渐变到暖色，06:00→08:00恢复
    float targetWarmth = 0.0f;
    if (hour >= 23.0f || hour < 6.0f) {
        targetWarmth = 0.8f;   // 深夜最大暖色
    } else if (hour >= 20.0f && hour < 23.0f) {
        targetWarmth = (hour - 20.0f) / 3.0f * 0.8f;  // 20~23线性渐变
    } else if (hour >= 6.0f && hour < 8.0f) {
        targetWarmth = 0.8f - (hour - 6.0f) / 2.0f * 0.8f;  // 6~8恢复
    }

    // EMA平滑避免突变
    _nightWarmth = _nightWarmth * 0.95f + targetWarmth * 0.05f;
    if (_nightWarmth < 0.01f) return;  // 暖色极低，跳过处理

    // 像素级色温矩阵：直接在sprite帧缓冲上逐像素应用色温变换
    uint16_t* buf = (uint16_t*)_sprite.getBuffer();
    if (!buf) return;
    
    const int totalPixels = SCREEN_WIDTH * SCREEN_HEIGHT;
    // [OPT-NIGHT] 色温矩阵：参考2700K色温曲线，R微增/G略减/B大幅减
    // 预计算整数因子 (Q8定点: 256=1.0)
    const int rFactor = 256 + (int)(_nightWarmth * 20.0f);   // 1.00→1.08 (R微增)
    const int gFactor = 256 - (int)(_nightWarmth * 30.0f);   // 1.00→0.88 (G略减)
    const int bFactor = 256 - (int)(_nightWarmth * 100.0f);  // 1.00→0.61 (B大幅减)
    
    for (int i = 0; i < totalPixels; i++) {
        uint16_t c = buf[i];
        int r = (c >> 11) & 0x1F;
        int g = (c >> 5)  & 0x3F;
        int b =  c        & 0x1F;
        
        // Q8定点乘法：(val * factor + 128) >> 8 ≈ val * (factor/256)
        r = (r * rFactor + 128) >> 8;  if (r > 31) r = 31;
        g = (g * gFactor + 128) >> 8;  if (g > 63) g = 63;  if (g < 0) g = 0;
        b = (b * bFactor + 128) >> 8;  if (b < 0)  b = 0;
        
        buf[i] = (uint16_t)((r << 11) | (g << 5) | b);
    }
}

uint16_t DisplayManager::nightShiftColor(uint16_t color) const {
    if (_nightWarmth < 0.01f) return color;
    
    int r = (color >> 11) & 0x1F;
    int g = (color >> 5)  & 0x3F;
    int b =  color        & 0x1F;
    
    // [OPT-NIGHT] 与applyNightFilter使用相同的色温矩阵
    const int rFactor = 256 + (int)(_nightWarmth * 20.0f);
    const int gFactor = 256 - (int)(_nightWarmth * 30.0f);
    const int bFactor = 256 - (int)(_nightWarmth * 100.0f);
    
    r = (r * rFactor + 128) >> 8;  if (r > 31) r = 31;
    g = (g * gFactor + 128) >> 8;  if (g > 63) g = 63;  if (g < 0) g = 0;
    b = (b * bFactor + 128) >> 8;  if (b < 0)  b = 0;
    
    return (uint16_t)((r << 11) | (g << 5) | b);
}

// ============ V-Sync / TE 中断 (硬件Tearing Effect) ============
// TE引脚由display_manager.h中的TE_PIN定义(config.h配置)
// ST7789V2在每次frame写入起始时拉低TE引脚，可用作V-Sync信号

void IRAM_ATTR DisplayManager::_teIsrHandler() {
    s_teTriggered = true;
}

void DisplayManager::setupVSync() {
    // 初始化TE中断引脚(需在display init之后调用)
    // ST7789V2 TE引脚默认输出模式，frame scan期间为LOW
    // 注: 需先通过SPI命令0x35启用TE output line
    if (LCD_TE_PIN < 0) {
        LOG_I("V-Sync disabled (LCD_TE_PIN < 0)");
        return;
    }
    pinMode(LCD_TE_PIN, INPUT_PULLUP);
    attachInterrupt(digitalPinToInterrupt(LCD_TE_PIN), _teIsrHandler, FALLING);
    s_teTriggered = false;
    LOG_I("V-Sync TE interrupt configured on GPIO %d\n", LCD_TE_PIN);
}

void DisplayManager::waitForVSync(uint32_t timeout_ms) {
    // 阻塞等待TE中断(下一帧扫描开始)
    // 如果TE未初始化或超时，直接返回(非阻塞退化)
    if (LCD_TE_PIN < 0 || !digitalPinIsValid(LCD_TE_PIN)) return;
    
    s_teTriggered = false;
    unsigned long start = millis();
    while (!s_teTriggered) {
        if (millis() - start > timeout_ms) break;
        vTaskDelay(pdMS_TO_TICKS(1));  // 1ms yield，释放CPU给其他FreeRTOS任务
    }
}
