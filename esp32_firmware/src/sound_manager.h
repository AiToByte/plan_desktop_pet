#ifndef SOUND_MANAGER_H
#define SOUND_MANAGER_H

#include <Arduino.h>
#include "config.h"

class SoundManager {
public:
    SoundManager();
    void begin();
    void beep(uint16_t freq = 2000, uint16_t duration = 50);
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
};

#endif // SOUND_MANAGER_H
