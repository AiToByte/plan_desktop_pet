#ifndef SOUND_MANAGER_H
#define SOUND_MANAGER_H

#include <Arduino.h>
#include "config.h"

#if ESP_ARDUINO_VERSION >= ESP_ARDUINO_VERSION_VAL(3,0,0)
#include <esp32-hal-timer.h>
#else
#include <driver/timer.h>
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
private:
    bool _enabled;
    bool _initialized;
    volatile uint16_t _toneFreq;  // 当前正弦波频率(ISR读取)

#if ESP_ARDUINO_VERSION >= ESP_ARDUINO_VERSION_VAL(3,0,0)
    hw_timer_t* _sineTimer;
#else
    // v2.x: timer指针类型不同，使用group+idx跟踪
    int _timerGroup;
    int _timerIdx;
#endif

    void _startSineTimer();
    void _stopSineTimer();
};

#endif // SOUND_MANAGER_H
