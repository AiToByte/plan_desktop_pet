#ifndef TOUCH_HANDLER_H
#define TOUCH_HANDLER_H

#include <Arduino.h>
#include "config.h"

enum TouchEvent {
    TOUCH_NONE,
    TOUCH_SINGLE_TAP,
    TOUCH_DOUBLE_TAP,
    TOUCH_LONG_PRESS
};

using TouchCallback = void(*)(TouchEvent);

class TouchHandler {
public:
    TouchHandler();
    void begin();
    void update();
    void setCallback(TouchCallback cb);
    uint16_t readValue();
    bool isTouched();
private:
    uint16_t _baseline;
    uint16_t _threshold;
    bool _initialized;
    bool _wasTouched;
    unsigned long _touchStart;
    unsigned long _lastTapTime;
    uint8_t _tapCount;
    TouchEvent _lastEvent;
    TouchCallback _callback;
    void calibrate();
};

#endif // TOUCH_HANDLER_H
