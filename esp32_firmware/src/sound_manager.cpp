#include "sound_manager.h"

SoundManager::SoundManager() : _enabled(true), _initialized(false) {}

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

void SoundManager::beepPattern(uint16_t freq, uint16_t onMs, uint16_t offMs, uint8_t count) {
    for (uint8_t i = 0; i < count; i++) {
        beep(freq, onMs);
        if (i < count - 1) delay(offMs);
    }
}

void SoundManager::playStartup() {
    beep(1000, 80);
    delay(80);
    beep(1500, 80);
    delay(80);
    beep(2000, 120);
}

void SoundManager::playNotification() {
    beepPattern(2500, 60, 40, 2);
}

void SoundManager::playAlert() {
    beepPattern(1500, 150, 100, 3);
}

void SoundManager::playOtaProgress() {
    beep(1800, 30);
}

void SoundManager::playOtaSuccess() {
    beep(1000, 100);
    delay(100);
    beep(1500, 100);
    delay(100);
    beep(2000, 200);
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
