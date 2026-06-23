#include "sound_manager.h"
#include "sin_lut.h"
#include "log.h"

// ============ ISR静态变量 ============
static volatile uint8_t  s_sinIdx = 0;      // LUT索引
static volatile uint16_t s_stepAcc = 0;     // 累加器（定点数）
static volatile uint8_t  s_pwmDuty = 0;     // 当前PWM占空比
static volatile uint16_t s_stepPerTick = 0; // 每tick步进值（定点）

#define STEP_FRAC_BITS 10
#define STEP_SCALE     (1 << STEP_FRAC_BITS)  // 1024

// ============ 硬件定时器ISR ============
#if ESP_ARDUINO_VERSION >= ESP_ARDUINO_VERSION_VAL(3,0,0)
static void IRAM_ATTR sineTimerISR(void* arg) {
    (void)arg;
    uint16_t step = s_stepPerTick;
    if (step == 0) return;

    s_stepAcc += step;
    if (s_stepAcc >= STEP_SCALE) {
        s_stepAcc -= STEP_SCALE;
        s_sinIdx = (s_sinIdx + 1) & 63;  // % 64
    }
    s_pwmDuty = SIN_LUT[s_sinIdx];
    ledcWrite(BUZZER_PIN, s_pwmDuty);
}
#else
// Arduino-ESP32 v2.x: timer ISR签名
static void IRAM_ATTR sineTimerISR(void* arg) {
    (void)arg;
    uint16_t step = s_stepPerTick;
    if (step == 0) return;

    s_stepAcc += step;
    if (s_stepAcc >= STEP_SCALE) {
        s_stepAcc -= STEP_SCALE;
        s_sinIdx = (s_sinIdx + 1) & 63;
    }
    s_pwmDuty = SIN_LUT[s_sinIdx];
    ledcWrite(0, s_pwmDuty);  // v2.x使用channel 0
}
#endif

// ============ SoundManager实现 ============

SoundManager::SoundManager()
    : _enabled(true), _initialized(false), _toneFreq(0)
#if SOUND_I2S_PDM_ENABLED
    , _i2sInitialized(false)
#endif
    , _audioMode(AUDIO_PWM)
#if ESP_ARDUINO_VERSION >= ESP_ARDUINO_VERSION_VAL(3,0,0)
    , _sineTimer(nullptr)
#else
    , _timerGroup(0), _timerIdx(0)
#endif
{}

void SoundManager::begin() {
#if ESP_ARDUINO_VERSION >= ESP_ARDUINO_VERSION_VAL(3,0,0)
    // Arduino-ESP32 v3.x: 新统一API (pin, freq, resolution)
    ledcAttach(BUZZER_PIN, 2000, 8);
#else
    // Arduino-ESP32 v2.x: 旧分离API (channel, freq, resolution)
    ledcSetup(0, 2000, 8);
    ledcAttachPin(BUZZER_PIN, 0);
#endif
    _initialized = true;
    LOG_I("Initialized on GPIO %s", (String(BUZZER_PIN)).c_str());
}

// ============ 方波蜂鸣（兼容原有接口）============
// 阻塞时长: 15-200ms per tone。ESP32 delay()=vTaskDelay()，同核其他任务可继续运行
void SoundManager::beep(uint16_t freq, uint16_t duration) {
    if (!_enabled || !_initialized) return;
#if ESP_ARDUINO_VERSION >= ESP_ARDUINO_VERSION_VAL(3,0,0)
    ledcWriteTone(BUZZER_PIN, freq);
    delay(duration);
    ledcWrite(BUZZER_PIN, 0);
#else
    ledcWriteTone(0, freq);
    delay(duration);
    ledcWrite(0, 0);
#endif
}

// ============ 正弦波柔和音调（苹果级听感）============
// 阻塞时长: 30-200ms per tone。delay()=vTaskDelay()，WiFi栈不受影响
void SoundManager::beepSine(uint16_t freq, uint16_t duration) {
    if (!_enabled || !_initialized) return;
    
#if SOUND_I2S_PDM_ENABLED
    // I2S-PDM模式：更高保真度
    if (_audioMode == AUDIO_I2S_PDM && _i2sInitialized) {
        _i2sTone(freq, duration);
        return;
    }
#endif
    
    // PWM模式（原有实现）
    if (freq < 100 || freq > 8000) {
        beep(freq, duration);
        return;
    }

    s_stepPerTick = (uint32_t)freq * SIN_LUT_SIZE * STEP_SCALE / PWM_CARRIER_HZ;
    s_stepAcc = 0;
    s_sinIdx = 0;

    _startSineTimer();

#if ESP_ARDUINO_VERSION >= ESP_ARDUINO_VERSION_VAL(3,0,0)
    delay(duration);
    _stopSineTimer();
    ledcWrite(BUZZER_PIN, 0);
#else
    delay(duration);
    _stopSineTimer();
    ledcWrite(0, 0);
#endif
}

// ============ 定时器控制 ============
void SoundManager::_startSineTimer() {
#if ESP_ARDUINO_VERSION >= ESP_ARDUINO_VERSION_VAL(3,0,0)
    if (!_sineTimer) {
        _sineTimer = timerBegin(PWM_CARRIER_HZ);
        timerAttachInterrupt(_sineTimer, &sineTimerISR);
    }
    timerStart(_sineTimer);
#else
    // Arduino-ESP32 v2.x
    timer_isr_handle_t handle;
    timer_config_t config = {};
    config.divider = 80;  // 80MHz / 80 = 1MHz tick
    config.counter_dir = TIMER_COUNT_UP;
    config.counter_en = TIMER_PAUSE;
    config.alarm_en = TIMER_ALARM_EN;
    config.auto_reload = TIMER_AUTORELOAD_EN;
    timer_init(TIMER_GROUP_0, TIMER_0, &config);
    timer_set_alarm_value(TIMER_GROUP_0, TIMER_0, 1000000 / PWM_CARRIER_HZ);  // 25 ticks @ 40kHz
    timer_enable_intr(TIMER_GROUP_0, TIMER_0);
    timer_isr_register(TIMER_GROUP_0, TIMER_0, sineTimerISR, nullptr, 0, &handle);
    timer_start(TIMER_GROUP_0, TIMER_0);
#endif
}

void SoundManager::_stopSineTimer() {
#if ESP_ARDUINO_VERSION >= ESP_ARDUINO_VERSION_VAL(3,0,0)
    if (_sineTimer) {
        timerStop(_sineTimer);
    }
#else
    timer_pause(TIMER_GROUP_0, TIMER_0);
#endif
    s_stepPerTick = 0;  // 确保ISR立即停止写入
}


// ====== I2S-PDM 音频后端 (ESP32-S3专用) ======
#if SOUND_I2S_PDM_ENABLED
// ESP-IDF v5.x 提供 <driver/i2s_pdm.h> 新API；v4.x 使用旧 i2s_config_t API
#if __has_include(<driver/i2s_pdm.h>)
// ========== ESP-IDF v5.x / Arduino-ESP32 v3.x 新API ==========
#include <driver/i2s_pdm.h>
#include "log.h"

static i2s_chan_handle_t s_i2sTxChan = nullptr;

void SoundManager::_initI2S() {
    // 创建I2S通道（PDM TX模式）
    i2s_chan_config_t chan_cfg = I2S_CHANNEL_DEFAULT_CONFIG(I2S_NUM_0, I2S_ROLE_MASTER);
    chan_cfg.dma_desc_num = 4;
    chan_cfg.dma_frame_num = 256;

    esp_err_t err = i2s_new_channel(&chan_cfg, &s_i2sTxChan, nullptr);
    if (err != ESP_OK) {
        LOG_E("I2S new_channel failed: %d\n", err);
        _audioMode = AUDIO_PWM;
        return;
    }

    // PDM TX配置（单声道，8-bit，44.1kHz）
    i2s_pdm_tx_config_t pdm_cfg = {};
    pdm_cfg.clk_cfg = I2S_PDM_TX_CLK_DEFAULT_CONFIG(44100);
    pdm_cfg.slot_cfg = I2S_PDM_TX_SLOT_DEFAULT_CONFIG(I2S_DATA_BIT_WIDTH_8BIT, I2S_SLOT_MODE_MONO);
    pdm_cfg.gpio_cfg.clk = I2S_GPIO_UNUSED;
    pdm_cfg.gpio_cfg.dout = (gpio_num_t)BUZZER_PIN;
    pdm_cfg.gpio_cfg.invert_flags.clk_inv = false;

    err = i2s_channel_init_pdm_tx_mode(s_i2sTxChan, &pdm_cfg);
    if (err != ESP_OK) {
        LOG_E("I2S PDM TX init failed: %d\n", err);
        i2s_del_channel(s_i2sTxChan);
        s_i2sTxChan = nullptr;
        _audioMode = AUDIO_PWM;
        return;
    }

    err = i2s_channel_enable(s_i2sTxChan);
    if (err != ESP_OK) {
        LOG_E("I2S channel enable failed: %d\n", err);
        i2s_del_channel(s_i2sTxChan);
        s_i2sTxChan = nullptr;
        _audioMode = AUDIO_PWM;
        return;
    }

    _i2sInitialized = true;
    LOG_I("I2S-PDM v5.x initialized on GPIO %s", (String(BUZZER_PIN)).c_str());
}

#else
// ========== ESP-IDF v4.x / Arduino-ESP32 v2.x 旧API ==========
void SoundManager::_initI2S() {
    i2s_config_t i2s_config = {};
    i2s_config.mode = (i2s_mode_t)(I2S_MODE_MASTER | I2S_MODE_TX | I2S_MODE_PDM);
    i2s_config.sample_rate = 44100;
    i2s_config.bits_per_sample = I2S_BITS_PER_SAMPLE_8BIT;
    i2s_config.channel_format = I2S_CHANNEL_FMT_ONLY_LEFT;
    i2s_config.communication_format = I2S_COMM_FORMAT_STAND_I2S;
    i2s_config.intr_alloc_flags = ESP_INTR_FLAG_LEVEL1;
    i2s_config.dma_buf_count = 4;
    i2s_config.dma_buf_len = 256;
    i2s_config.use_apll = false;
    i2s_config.tx_desc_auto_clear = true;

    i2s_pin_config_t pin_config = {};
    pin_config.bck_io_num = I2S_PIN_NO_CHANGE;
    pin_config.ws_io_num = I2S_PIN_NO_CHANGE;
    pin_config.data_out_num = BUZZER_PIN;
    pin_config.data_in_num = I2S_PIN_NO_CHANGE;

    esp_err_t err = i2s_driver_install(I2S_NUM_0, &i2s_config, 0, nullptr);
    if (err != ESP_OK) {
        LOG_E("I2S install failed: %d, falling back to PWM\n", err);
        _audioMode = AUDIO_PWM;
        return;
    }
    i2s_set_pin(I2S_NUM_0, &pin_config);
    i2s_set_clk(I2S_NUM_0, 44100, I2S_BITS_PER_SAMPLE_8BIT, I2S_CHANNEL_MONO);
    _i2sInitialized = true;
    LOG_I("I2S-PDM v4.x initialized on GPIO %s", (String(BUZZER_PIN)).c_str());
}
#endif  // __has_include(<driver/i2s_pdm.h>)

void SoundManager::_i2sTone(uint16_t freq, uint16_t duration) {
    if (!_i2sInitialized) return;
    
    // 生成正弦波基础缓冲区
    const int samplesPerCycle = 44100 / freq;
    const int bufLen = (samplesPerCycle > 256) ? 256 : samplesPerCycle;
    uint8_t baseBuf[256];
    uint8_t envBuf[256];
    
    for (int i = 0; i < bufLen; i++) {
        float angle = 2.0f * 3.14159f * i / bufLen;
        baseBuf[i] = (uint8_t)(128 + 120 * sinf(angle));
    }
    
    // ADSR参数动态缩放：短音(<80ms)时压缩attack/release，保证有效响铃时间
    uint16_t attackMs  = 8;   // 淡入 (最小瞬态)
    uint16_t decayMs   = 0;   // 无衰减(纯正弦不需要)
    uint16_t releaseMs = 15;  // 淡出 (消除断尾爆音)
    
    // 短音保护：attack+release不能超过duration的20%，最少保留80%有效响铃
    uint16_t envelopeBudget = (duration * 20) / 100;  // 20%的duration留给包络
    uint16_t totalEnvelope = attackMs + releaseMs;
    if (totalEnvelope > envelopeBudget && envelopeBudget > 0) {
        float scale = (float)envelopeBudget / (float)totalEnvelope;
        attackMs  = (uint16_t)(attackMs * scale);
        releaseMs = (uint16_t)(releaseMs * scale);
        // 确保至少1ms的attack和release
        if (attackMs < 1) attackMs = 1;
        if (releaseMs < 1) releaseMs = 1;
    }
    
    unsigned long now = millis();
    unsigned long endTime = now + duration;
    unsigned long releaseStart = endTime - releaseMs;
    
    size_t bytesWritten = 0;
    while (millis() < endTime) {
        // 计算当前包络增益 (0.0 ~ 1.0)
        unsigned long t = millis();
        float gain = 1.0f;
        if (t - now < attackMs) {
            // Attack阶段: 线性淡入
            gain = (float)(t - now) / (float)attackMs;
        } else if (t >= releaseStart && t < endTime) {
            // Release阶段: 线性淡出
            gain = (float)(endTime - t) / (float)releaseMs;
        }
        
        // 应用包络到正弦波
        for (int i = 0; i < bufLen; i++) {
            float sample = (baseBuf[i] - 128) * gain;
            envBuf[i] = (uint8_t)(128 + (int8_t)sample);
        }
        
        i2s_write(I2S_NUM_0, envBuf, bufLen, &bytesWritten, portMAX_DELAY);
    }
    
    // 额外写一小段静音，确保DMA缓冲区清空
    memset(envBuf, 128, bufLen);
    i2s_write(I2S_NUM_0, envBuf, bufLen, &bytesWritten, portMAX_DELAY);
}

void SoundManager::setAudioMode(AudioMode mode) {
    _audioMode = mode;
    if (mode == AUDIO_I2S_PDM && !_i2sInitialized) {
        _initI2S();
    }
}
#endif  // SOUND_I2S_PDM_ENABLED
// ============ 复合音效 ============
// 注意: 复合音效串行播放多段tone，总阻塞 ~100-650ms
// ESP32 delay()=vTaskDelay()不会阻塞WiFi栈，仅暂停当前task
void SoundManager::beepPattern(uint16_t freq, uint16_t onMs, uint16_t offMs, uint8_t count) {
    for (uint8_t i = 0; i < count; i++) {
        beep(freq, onMs);
        if (i < count - 1) delay(offMs);
    }
}

// 总阻塞 ~440ms (80+80+80+80+120)
void SoundManager::playStartup() {
    beepSine(1000, 80);
    delay(80);
    beepSine(1500, 80);
    delay(80);
    beepSine(2000, 120);
}

// 总阻塞 ~160ms (60+40+60)
void SoundManager::playNotification() {
    beepSine(2500, 60);
    delay(40);
    beepSine(2500, 60);
}

// 总阻塞 ~650ms (beepPattern 3×150 + 2×100)
void SoundManager::playAlert() {
    beepPattern(1500, 150, 100, 3);
}

void SoundManager::playOtaProgress() {
    beepSine(1800, 30);
}

// 总阻塞 ~600ms (100+100+100+100+200)
void SoundManager::playOtaSuccess() {
    beepSine(1000, 100);
    delay(100);
    beepSine(1500, 100);
    delay(100);
    beepSine(2000, 200);
}

// 总阻塞 ~900ms (beepPattern 3×200 + 2×100)
void SoundManager::playOtaFail() {
    beepPattern(800, 200, 100, 3);
}

void SoundManager::setEnabled(bool enabled) {
    _enabled = enabled;
}

bool SoundManager::isEnabled() const {
    return _enabled;
}
