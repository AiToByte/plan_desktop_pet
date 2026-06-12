#include "sound_manager.h"

SoundManager::SoundManager() : _enabled(true), _initialized(false) {}

void SoundManager::begin() {
    ledcSetup(0, 2000, 8);  // channel 0, 2kHz, 8-bit
    ledcAttachPin(BUZZER_PIN, 0);
    _initialized = true;
    Serial.println("[Sound] Initialized on GPIO " + String(BUZZER_PIN));
}

void SoundManager::beep(uint16_t freq, uint16_t duration) {
    if (!_enabled || !_initialized) return;
    ledcWriteTone(0, freq);
    delay(duration);
    ledcWrite(0, 0);
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
