/*
 * DRV2605L LRA触觉反馈驱动
 * 
 * I2C地址: 0x5A
 * 支持: LRA(线性谐振致动器) + ERM(偏心旋转质量)
 * 预设效果: click(模式1)/buzz(模式47)/waveform(自定义序列)
 * 
 * 接线(文档见 docs/HARDWARE_DRV2605L.md):
 *   SDA → GPIO41 (与BH1750共享I2C总线)
 *   SCL → GPIO42
 *   VCC → 3.3V
 *   GND → GND
 *   OUT+/OUT- → LRA马达
 */

#ifndef HAPTIC_DRIVER_H
#define HAPTIC_DRIVER_H

#include <Arduino.h>
#include <Wire.h>

class HapticDriver {
public:
    // DRV2605L I2C地址
    static constexpr uint8_t DRV2605_ADDR = 0x5A;
    
    // 预设效果ID (DRV2605L内置123种效果)
    static constexpr uint8_t EFFECT_CLICK   = 1;   // 轻击
    static constexpr uint8_t EFFECT_BUZZ    = 47;  // 持续嗡嗡
    static constexpr uint8_t EFFECT_STRONG  = 72;  // 强击
    static constexpr uint8_t EFFECT_SOFT    = 3;   // 软触
    static constexpr uint8_t EFFECT_RAMP_UP = 12;  // 渐强

    HapticDriver();
    ~HapticDriver();

    // 初始化I2C + DRV2605L
    // sdaPin/sclPin: I2C引脚(默认GPIO41/42)
    // 返回: true=驱动器响应
    bool begin(int sdaPin = 41, int sclPin = 42);

    // 播放预设效果
    // effectId: 1~123 (见DRV2605L datasheet)
    void playEffect(uint8_t effectId);

    // 快捷方法
    void click();      // 轻击反馈(触摸确认)
    void buzz();       // 持续嗡嗡(通知)
    void strongHit();  // 强击(警告)
    void softTouch();  // 软触(滑动反馈)

    // 播放波形序列
    // sequence: 效果ID数组(最大8个)
    // count: 序列长度
    void playWaveform(const uint8_t* sequence, uint8_t count);

    // 停止当前效果
    void stop();

    // 自动校准LRA参数（自动调用begin()后）
    bool calibrate();
    
    // 设置马达类型
    // 0=ERM(偏心旋转), 1=LRA(线性谐振)
    void setMotorType(uint8_t type);

    // 驱动器是否可用
    bool isAvailable() const { return _available; }

private:
    TwoWire _wire;
    bool _available;
    uint8_t _motorType;  // 0=ERM, 1=LRA

    bool _writeRegister(uint8_t reg, uint8_t value);
    uint8_t _readRegister(uint8_t reg);
    void _setWaveformSlot(uint8_t slot, uint8_t effectId);
};

#endif // HAPTIC_DRIVER_H
