/*
 * BH1750环境光传感器管理器
 * 
 * I2C地址: 0x23 (ADDR引脚接GND时)
 * 模式: 连续高分辨率(1 lx精度)
 * 
 * 功能:
 *   - 读取环境光照度(lux)
 *   - 自动背光调节: lux→PWM映射
 *   - 低功耗休眠模式
 * 
 * 接线(文档见 docs/HARDWARE_BH1750.md):
 *   SDA → GPIO41
 *   SCL → GPIO42
 *   VCC → 3.3V
 *   GND → GND
 */

#ifndef AMBIENT_LIGHT_H
#define AMBIENT_LIGHT_H

#include <Arduino.h>
#include <Wire.h>

class AmbientLightManager {
public:
    // BH1750 I2C地址
    static constexpr uint8_t BH1750_ADDR = 0x23;
    
    // BH1750指令
    static constexpr uint8_t BH1750_POWER_ON  = 0x01;
    static constexpr uint8_t BH1750_RESET     = 0x07;
    static constexpr uint8_t BH1750_CONT_HRES = 0x10;  // 连续高分辨率模式
    static constexpr uint8_t BH1750_CONT_LRES = 0x13;  // 连续低分辨率模式(快速)
    static constexpr uint8_t BH1750_ONE_HRES  = 0x20;  // 单次高分辨率模式

    AmbientLightManager();
    ~AmbientLightManager();

    // 初始化I2C + BH1750
    // sdaPin/sclPin: I2C引脚(默认GPIO41/42)
    // 返回: true=传感器响应
    bool begin(int sdaPin = 41, int sclPin = 42);

    // 读取光照度(lux)
    // 返回: 0~65535 lx，-1=读取失败
    int16_t readLux();

    // 自动背光调节
    // 根据当前lux值计算推荐背光亮度(0~255)
    // 映射曲线: 10lx=20%, 100lx=50%, 1000lx=100%
    uint8_t autoAdjustBacklight(int16_t lux);

    // 获取上次读取的lux值(缓存)
    int16_t getLastLux() const { return _lastLux; }

    // 进入低功耗模式
    void powerDown();

    // 唤醒
    void powerUp();

    // 传感器是否可用
    bool isAvailable() const { return _available; }

private:
    TwoWire _wire;
    bool _available;
    int16_t _lastLux;
    unsigned long _lastReadTime;
    
    // EMA滤波参数（指数移动平均）
    float _emaLux;           // EMA滤波后的lux值
    static constexpr float EMA_ALPHA = 0.15f;  // 平滑系数（0.0~1.0，越小越平滑）

    bool _writeCommand(uint8_t cmd);
    int16_t _readRawValue();
};

#endif // AMBIENT_LIGHT_H
