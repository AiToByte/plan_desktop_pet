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
    int16_t lux = (int16_t)(raw / 1.2f);
    if (lux < 0) lux = 0;
    
    _lastLux = lux;
    _lastReadTime = millis();
    
    return lux;
}

// ====== 自动背光 ======

uint8_t AmbientLightManager::autoAdjustBacklight(int16_t lux) {
    if (lux < 0) return 128;  // 读取失败时给中等亮度
    
    // 分段线性映射
    if (lux <= 0) {
        return 30;   // 完全黑暗给最低亮度
    } else if (lux <= 10) {
        // 1~10 lx → 30~50 (最低可见)
        return map(lux, 1, 10, 30, 50);
    } else if (lux <= 100) {
        // 10~100 lx → 50~128 (20%~50%)
        return map(lux, 10, 100, 50, 128);
    } else if (lux <= 1000) {
        // 100~1000 lx → 128~255 (50%~100%)
        return map(lux, 100, 1000, 128, 255);
    } else {
        return 255;  // 强光环境100%
    }
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
