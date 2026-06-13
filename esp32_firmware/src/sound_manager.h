#ifndef SOUND_MANAGER_H
#define SOUND_MANAGER_H

#include <Arduino.h>
#include "config.h"

#if ESP_ARDUINO_VERSION >= ESP_ARDUINO_VERSION_VAL(3,0,0)
#include <esp32-hal-timer.h>
#else
#include <driver/timer.h>
#endif

// I2S-PDM支持 (ESP32-S3)
#if CONFIG_IDF_TARGET_ESP32S3
#define SOUND_I2S_PDM_ENABLED 1
#include <driver/i2s.h>
#else
#define SOUND_I2S_PDM_ENABLED 0
#endif

class SoundManager {
public:
    SoundManager();
    void begin();
    void beep(uint16_t freq = 2000, uint16_t duration = 50);
    void beepSine(uint16_t freq, uint16_t duration);  // 正弦波柔和音调
    void beepPattern(uint16_t freq, uint16_t onMs, uint16_t offMs, uint8_t count);
    void playStartup();
    void playNotification();
    void playAlert();
    void playOtaProgress();
    void playOtaSuccess();
    void playOtaFail();
    void setEnabled(bool enabled);
    bool isEnabled() const;
    
    // I2S-PDM模式切换（默认自动检测）
    enum AudioMode { AUDIO_PWM, AUDIO_I2S_PDM };
    void setAudioMode(AudioMode mode);
    AudioMode getAudioMode() const { return _audioMode; }
    
private:
    bool _enabled;
    bool _initialized;
    volatile uint16_t _toneFreq;
    AudioMode _audioMode;

#if ESP_ARDUINO_VERSION >= ESP_ARDUINO_VERSION_VAL(3,0,0)
    hw_timer_t* _sineTimer;
#else
    int _timerGroup;
    int _timerIdx;
#endif

#if SOUND_I2S_PDM_ENABLED
    bool _i2sInitialized;
    void _initI2S();
    void _i2sTone(uint16_t freq, uint16_t duration);
#endif

    void _startSineTimer();
    void _stopSineTimer();
};

#endif // SOUND_MANAGER_H
