#ifndef TOUCH_HANDLER_H
#define TOUCH_HANDLER_H

#include <Arduino.h>
#include "config.h"

enum TouchEvent {
    TOUCH_NONE,
    TOUCH_SINGLE_TAP,
    TOUCH_DOUBLE_TAP,
    TOUCH_LONG_PRESS,
    TOUCH_PROXIMITY       // 接近感应事件
};

using TouchCallback = void(*)(TouchEvent);

// ============ 接近感应器（EMA快慢线差分） ============
class ProximitySensor {
public:
    ProximitySensor();
    void begin();
    bool update();         // 每帧调用，返回true表示触发接近事件
    bool isNear() const;   // 当前是否处于接近状态
    float getFastEMA() const;
    float getSlowEMA() const;
    uint16_t getBaseline() const;
private:
    float _fastEMA;
    float _slowEMA;
    uint16_t _baseline;
    bool _initialized;
    bool _isNear;
    unsigned long _lastEventTime;
    unsigned long _lastNearTime;  // 最近一次接近时间（用于wake duration）
public:
    unsigned long getLastNearTime() const { return _lastNearTime; }
};

class TouchHandler {
public:
    TouchHandler();
    void begin();
    void update();
    void setCallback(TouchCallback cb);
    uint16_t readValue();
    bool isTouched();
    
    // 接近感应
    ProximitySensor proximity;
    bool isProximityWakeActive() const;  // 接近唤醒亮屏是否生效中
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
