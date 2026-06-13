#include "touch_handler.h"

// ============ ProximitySensor 实现 ============

ProximitySensor::ProximitySensor()
    : _fastEMA(0), _slowEMA(0), _baseline(0),
      _initialized(false), _isNear(false),
      _lastEventTime(0), _lastNearTime(0) {}

void ProximitySensor::begin() {
    // 多次采样取基线
    float sum = 0;
    for (int i = 0; i < 50; i++) {
        sum += touchRead(TOUCH_PIN);
        delay(2);
    }
    _baseline = (uint16_t)(sum / 50);
    _fastEMA = _baseline;
    _slowEMA = _baseline;
    _initialized = true;
    Serial.printf("[Proximity] Baseline calibrated: %u\n", _baseline);
}

bool ProximitySensor::update() {
    if (!_initialized) return false;
    
    uint16_t raw = touchRead(TOUCH_PIN);
    _fastEMA = PROX_EMA_FAST_ALPHA * raw + (1.0f - PROX_EMA_FAST_ALPHA) * _fastEMA;
    _slowEMA = PROX_EMA_SLOW_ALPHA * raw + (1.0f - PROX_EMA_SLOW_ALPHA) * _slowEMA;
    
    float diff = _fastEMA - _slowEMA;
    unsigned long now = millis();
    
    if (!_isNear) {
        // 等待上升沿（手指接近时电容值上升）
        if (diff > PROX_RISING_THRESHOLD) {
            _isNear = true;
            _lastNearTime = now;
            if (now - _lastEventTime > PROX_COOLDOWN_MS) {
                _lastEventTime = now;
                Serial.printf("[Proximity] NEAR detected (diff=%.1f)\n", diff);
                return true;  // 触发接近事件
            }
        }
    } else {
        // 等待下降沿（手指远离）
        if (diff < PROX_FALLING_THRESHOLD) {
            _isNear = false;
        }
        // 持续接近时更新时间戳
        _lastNearTime = now;
    }
    return false;
}

bool ProximitySensor::isNear() const { return _isNear; }
float ProximitySensor::getFastEMA() const { return _fastEMA; }
float ProximitySensor::getSlowEMA() const { return _slowEMA; }
uint16_t ProximitySensor::getBaseline() const { return _baseline; }


TouchHandler::TouchHandler()
    : _baseline(0), _threshold(TOUCH_THRESHOLD),
      _initialized(false), _wasTouched(false),
      _touchStart(0), _lastTapTime(0),
      _tapCount(0), _lastEvent(TOUCH_NONE),
      _callback(nullptr) {}

void TouchHandler::begin() {
    calibrate();
    proximity.begin();  // 同时初始化接近感应
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
    
    // 接近感应（独立于触摸事件，优先检查）
    if (proximity.update()) {
        if (_callback) _callback(TOUCH_PROXIMITY);
    }

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

bool TouchHandler::isProximityWakeActive() const {
    return proximity.isNear() || 
           (millis() - proximity._lastNearTime < PROX_WAKE_DURATION_MS);
}

void TouchHandler::setCallback(TouchCallback cb) {
    _callback = cb;
}

uint16_t TouchHandler::readValue() {
    return touchRead(TOUCH_PIN);
}

bool TouchHandler::isTouched() {
    if (!_initialized) return false;
    uint16_t current = touchRead(TOUCH_PIN);
    // ESP32-S3触摸值可能高于基线，使用绝对差值法
    uint16_t delta = abs((int32_t)_baseline - (int32_t)current);
    return delta > _threshold;
}
