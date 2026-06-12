#include "sound_manager.h"
#include "sin_lut.h"

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
    Serial.println("[Sound] Initialized on GPIO " + String(BUZZER_PIN));
}

// ============ 方波蜂鸣（兼容原有接口）============
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
void SoundManager::beepSine(uint16_t freq, uint16_t duration) {
    if (!_enabled || !_initialized) return;
    if (freq < 100 || freq > 8000) {
        // 频率超出LUT分辨率范围，回退到方波
        beep(freq, duration);
        return;
    }

    // 计算每tick步进值：step = freq * 64 / PWM_CARRIER_HZ * STEP_SCALE
    // = (freq << STEP_FRAC_BITS) * 64 / PWM_CARRIER_HZ
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
    timer_enable_interrupt(TIMER_GROUP_0, TIMER_0);
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

// ============ 复合音效 ============
void SoundManager::beepPattern(uint16_t freq, uint16_t onMs, uint16_t offMs, uint8_t count) {
    for (uint8_t i = 0; i < count; i++) {
        beep(freq, onMs);
        if (i < count - 1) delay(offMs);
    }
}

void SoundManager::playStartup() {
    beepSine(1000, 80);
    delay(80);
    beepSine(1500, 80);
    delay(80);
    beepSine(2000, 120);
}

void SoundManager::playNotification() {
    beepSine(2500, 60);
    delay(40);
    beepSine(2500, 60);
}

void SoundManager::playAlert() {
    beepPattern(1500, 150, 100, 3);
}

void SoundManager::playOtaProgress() {
    beepSine(1800, 30);
}

void SoundManager::playOtaSuccess() {
    beepSine(1000, 100);
    delay(100);
    beepSine(1500, 100);
    delay(100);
    beepSine(2000, 200);
}

void SoundManager::playOtaFail() {
    beepPattern(800, 200, 100, 3);
}

void SoundManager::setEnabled(bool enabled) {
    _enabled = enabled;
}

bool SoundManager::isEnabled() const {
    return _enabled;
}
