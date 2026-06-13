/*
 * BH1750环境光传感器管理器 - 实现
 * 
 * 硬件: BH1750FVI (GY-302模块)
 * 协议: I2C, 地址0x23
 * 分辨率: 1 lx (高分辨率模式)
 * 
 * 背光映射逻辑:
 *   0~10 lx:    最低背光(防止全黑)
 *   10~100 lx:  线性映射 20%~50%
 *   100~1000 lx: 线性映射 50%~100%
 *   >1000 lx:   100%
 */

#include "ambient_light.h"

// ====== 构造/析构 ======

AmbientLightManager::AmbientLightManager()
    : _available(false), _lastLux(0), _lastReadTime(0) {
}

AmbientLightManager::~AmbientLightManager() {
    if (_available) powerDown();
}

// ====== 初始化 ======

bool AmbientLightManager::begin(int sdaPin, int sclPin) {
    _wire.begin(sdaPin, sclPin);
    
    // 检测传感器是否响应
    _wire.beginTransmission(BH1750_ADDR);
    if (_wire.endTransmission() != 0) {
        Serial.println("[Light] BH1750 not found on I2C bus");
        _available = false;
        return false;
    }
    
    // 上电 + 连续高分辨率模式
    _writeCommand(BH1750_POWER_ON);
    delay(10);
    _writeCommand(BH1750_CONT_HRES);
    delay(180);  // 首次测量需要120~180ms
    
    _available = true;
    Serial.println("[Light] BH1750 initialized (continuous high-res)");
    return true;
}

// ====== 读取光照度 ======

int16_t AmbientLightManager::readLux() {
    if (!_available) return -1;
    
    _wire.requestFrom((uint8_t)BH1750_ADDR, (uint8_t)2);
    if (_wire.available() < 2) {
        Serial.println("[Light] BH1750 read failed");
        return -1;
    }
    
    uint16_t raw = (_wire.read() << 8) | _wire.read();
    
    // BH1750原始值÷1.2得到lux(高分辨率模式)
    int16_t rawLux = (int16_t)(raw / 1.2f);
    if (rawLux < 0) rawLux = 0;
    
    // EMA滤波：new = alpha * raw + (1-alpha) * old
    _emaLux = EMA_ALPHA * rawLux + (1.0f - EMA_ALPHA) * _emaLux;
    
    _lastLux = (int16_t)_emaLux;
    _lastReadTime = millis();
    
    return _lastLux;
}

// ====== CIE 1931 亮度曲线 ======

// CIE 1931 感知亮度映射
// 输入: 0.0~1.0 (归一化亮度)
// 输出: 0.0~1.0 (感知亮度，符合人眼响应)
static float cie1931_curve(float Y) {
    // 标准CIE 1931公式
    // Y/Yn <= 0.008856: L* = 903.3 * Y/Yn
    // Y/Yn > 0.008856:  L* = 116 * (Y/Yn)^(1/3) - 16
    if (Y <= 0.008856f) {
        return 903.3f * Y;
    } else {
        return 116.0f * powf(Y, 1.0f/3.0f) - 16.0f;
    }
}

// ====== 自动背光 ======

uint8_t AmbientLightManager::autoAdjustBacklight(int16_t lux) {
    if (lux < 0) return 128;  // 读取失败时给中等亮度
    
    // 归一化lux到0.0~1.0（假设最大感知亮度在10000lux）
    // 避免浮点除法，用整数映射
    const int16_t MAX_LUX = 10000;
    if (lux > MAX_LUX) lux = MAX_LUX;
    
    // 归一化到0.0~1.0
    float normalized = (float)lux / (float)MAX_LUX;
    
    // 应用CIE 1931曲线（归一化到0.0~1.0输出）
    // CIE曲线输出范围: 0~100，归一化到0.0~1.0
    float perceived = cie1931_curve(normalized) / 100.0f;
    
    // 确保输出在有效范围
    if (perceived < 0.0f) perceived = 0.0f;
    if (perceived > 1.0f) perceived = 1.0f;
    
    // 最低亮度保护（防止完全黑暗时屏幕关闭）
    const uint8_t MIN_PWM = 15;  // 约6%亮度，确保屏幕可见
    const uint8_t MAX_PWM = 255;
    
    // 映射到PWM范围
    uint8_t pwm = MIN_PWM + (uint8_t)(perceived * (MAX_PWM - MIN_PWM));
    
    return pwm;
}

// ====== 功耗管理 ======

void AmbientLightManager::powerDown() {
    if (!_available) return;
    _writeCommand(0x00);  // Power Down指令
    Serial.println("[Light] BH1750 powered down");
}

void AmbientLightManager::powerUp() {
    if (!_available) return;
    _writeCommand(BH1750_POWER_ON);
    delay(10);
    _writeCommand(BH1750_CONT_HRES);
    delay(180);
    Serial.println("[Light] BH1750 powered up");
}

// ====== 内部方法 ======

bool AmbientLightManager::_writeCommand(uint8_t cmd) {
    _wire.beginTransmission(BH1750_ADDR);
    _wire.write(cmd);
    return (_wire.endTransmission() == 0);
}
