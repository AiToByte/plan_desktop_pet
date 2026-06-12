#include "touch_handler.h"

TouchHandler::TouchHandler()
    : _baseline(0), _threshold(TOUCH_THRESHOLD),
      _initialized(false), _wasTouched(false),
      _touchStart(0), _lastTapTime(0),
      _tapCount(0), _lastEvent(TOUCH_NONE),
      _callback(nullptr) {}

void TouchHandler::begin() {
    calibrate();
    _initialized = true;
    Serial.printf("[Touch] Initialized on GPIO %d, baseline=%u, threshold=%u\n",
                  TOUCH_PIN, _baseline, _threshold);
}

void TouchHandler::calibrate() {
    // 采样20次取平均作为基线
    uint32_t sum = 0;
    for (int i = 0; i < 20; i++) {
        sum += touchRead(TOUCH_PIN);
        delay(10);
    }
    _baseline = sum / 20;
}

void TouchHandler::update() {
    if (!_initialized) return;

    uint16_t val = touchRead(TOUCH_PIN);
    bool touched = (val < (_baseline - _threshold));
    unsigned long now = millis();

    if (touched && !_wasTouched) {
        // 按下
        _touchStart = now;
        _wasTouched = true;
    }
    else if (!touched && _wasTouched) {
        // 释放
        _wasTouched = false;
        unsigned long duration = now - _touchStart;

        if (duration >= TOUCH_LONG_PRESS_MS) {
            _lastEvent = TOUCH_LONG_PRESS;
            _tapCount = 0;
            if (_callback) _callback(TOUCH_LONG_PRESS);
        } else {
            // 短按
            if (now - _lastTapTime < 400) {
                _tapCount++;
            } else {
                _tapCount = 1;
            }
            _lastTapTime = now;
        }
    }

    // 检测双击超时（400ms无第二次按下则触发单击/双击）
    if (_tapCount > 0 && !_wasTouched && (now - _lastTapTime > 400)) {
        if (_tapCount >= 2) {
            _lastEvent = TOUCH_DOUBLE_TAP;
            if (_callback) _callback(TOUCH_DOUBLE_TAP);
        } else {
            _lastEvent = TOUCH_SINGLE_TAP;
            if (_callback) _callback(TOUCH_SINGLE_TAP);
        }
        _tapCount = 0;
    }
}

void TouchHandler::setCallback(TouchCallback cb) {
    _callback = cb;
}

uint16_t TouchHandler::readValue() {
    return touchRead(TOUCH_PIN);
}

bool TouchHandler::isTouched() {
    if (!_initialized) return false;
    return (touchRead(TOUCH_PIN) < (_baseline - _threshold));
}
