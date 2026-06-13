/*
 * DRV2605L LRA触觉反馈驱动 - 实现
 * 
 * DRV2605L寄存器概览:
 *   0x01 Mode        - 播放模式(内部触发/外部触发/实时/波形序列)
 *   0x02 RatedVoltage - 额定电压(LRA需要校准)
 *   0x03 ODClamp     - 过驱动钳位电压
 *   0x04 Feedback    - 反馈控制(LRA/ERM选择)
 *   0x05 Control1    - 控制寄存器1
 *   0x06 Control2    - 控制寄存器2
 *   0x07 Control3    - 控制寄存器3
 *   0x0D WaveformSeq - 波形序列(8个槽位, 0x0D~0x14)
 *   0x0C Go          - 触发播放
 * 
 * 模式:
 *   0x00 Internal Trigger (软件触发)
 *   0x01 External Trigger (引脚触发)
 *   0x02 Real-time Playback (PWM/模拟输入)
 *   0x03 Diagnostics (诊断)
 *   0x05 Waveform Sequencer (波形序列)
 */

#include "haptic_driver.h"

// DRV2605L寄存器地址
static constexpr uint8_t REG_STATUS    = 0x00;
static constexpr uint8_t REG_MODE      = 0x01;
static constexpr uint8_t REG_RTPIN     = 0x02;
static constexpr uint8_t REG_LIBRARY   = 0x03;
static constexpr uint8_t REG_WAVESEQ1  = 0x04;
static constexpr uint8_t REG_WAVESEQ2  = 0x05;
static constexpr uint8_t REG_WAVESEQ3  = 0x06;
static constexpr uint8_t REG_WAVESEQ4  = 0x07;
static constexpr uint8_t REG_WAVESEQ5  = 0x08;
static constexpr uint8_t REG_WAVESEQ6  = 0x09;
static constexpr uint8_t REG_WAVESEQ7  = 0x0A;
static constexpr uint8_t REG_WAVESEQ8  = 0x0B;
static constexpr uint8_t REG_GO        = 0x0C;
static constexpr uint8_t REG_FEEDBACK  = 0x1A;
static constexpr uint8_t REG_CONTROL1  = 0x1B;
static constexpr uint8_t REG_CONTROL2  = 0x1C;
static constexpr uint8_t REG_CONTROL3  = 0x1D;
static constexpr uint8_t REG_RATEDVOL = 0x16;
static constexpr uint8_t REG_ODCLAMP  = 0x17;

// 模式值
static constexpr uint8_t MODE_INTERNAL = 0x00;
static constexpr uint8_t MODE_SEQUENCE = 0x05;

// ====== 构造/析构 ======

HapticDriver::HapticDriver()
    : _available(false), _motorType(1) {  // 默认LRA
}

HapticDriver::~HapticDriver() {
    if (_available) stop();
}

// ====== 初始化 ======

bool HapticDriver::begin(int sdaPin, int sclPin) {
    _wire.begin(sdaPin, sclPin);
    
    // 检测传感器
    _wire.beginTransmission(DRV2605_ADDR);
    if (_wire.endTransmission() != 0) {
        Serial.println("[Haptic] DRV2605L not found on I2C bus");
        _available = false;
        return false;
    }
    
    // 设置为内部触发模式
    _writeRegister(REG_MODE, MODE_INTERNAL);
    
    // 选择波形库(LRA用Library 6, ERM用Library 1/4/5)
    // Library 6: LRA优化，包含123种效果
    _writeRegister(REG_LIBRARY, 0x06);  // Library 6 for LRA
    
    // 反馈控制: LRA模式(0x80) + 带宽中等(0x20)
    _writeRegister(REG_FEEDBACK, 0xA0);  // [7]=1(LRA), [6:4]=带宽
    
    // Control1: 采样时间4x, 驱动时间36μs
    _writeRegister(REG_CONTROL1, 0x93);
    
    // Control2: 双向制动+空闲时间0
    _writeRegister(REG_CONTROL2, 0xF5);
    
    // Control3: 纳入电动制动+噪声门+软制动
    _writeRegister(REG_CONTROL3, 0xA0);
    
    _available = true;
    Serial.println("[Haptic] DRV2605L initialized (LRA mode, Library 6)");
    
    // 自动校准LRA参数
    calibrate();
    
    // 校准后重新配置工作模式
    _writeRegister(REG_MODE, MODE_INTERNAL);
    _writeRegister(REG_LIBRARY, 0x06);  // Library 6 for LRA
    _writeRegister(REG_CONTROL1, 0x93);
    _writeRegister(REG_CONTROL2, 0xF5);
    _writeRegister(REG_CONTROL3, 0xA0);
    
    Serial.println("[Haptic] Ready for playback");
    return true;
}


// ====== 自动校准 ======

bool HapticDriver::calibrate() {
    if (!_available) return false;

    // Step 1: 设置为待机模式
    _writeRegister(REG_MODE, 0x00);  // Internal Trigger mode (standby)
    delay(10);

    // Step 2: 配置LRA参数（校准前必须正确设置）
    // 额定电压: 对于LRA，典型值约1.8V RMS
    // DRV2605L: RatedVoltage = V_rms * 255 / 5.36V
    // 1.8V → ~85 (0x55)
    _writeRegister(REG_RATEDVOL, 0x55);

    // 过驱动钳位: 典型值约2.5V peak
    // ODClamp = V_peak * 255 / 5.6V
    // 2.5V → ~114 (0x72)
    _writeRegister(REG_ODCLAMP, 0x72);

    // Step 3: 设置Feedback寄存器 (LRA模式 + back-EMF使能)
    // [7]=1(LRA), [6:4]=0(不修改采样时间), [3]=0(自动补偿)
    _writeRegister(REG_FEEDBACK, 0xA0);

    // Step 4: 设置Control2 (校准时使用默认参数)
    _writeRegister(REG_CONTROL2, 0xF5);

    // Step 5: 进入自动校准模式 (Mode=0x07)
    _writeRegister(REG_MODE, 0x07);

    // Step 6: 触发校准
    _writeRegister(REG_GO, 0x01);

    // Step 7: 等待校准完成 (GO位自动清零)
    unsigned long start = millis();
    while (millis() - start < 1500) {  // 最多等1.5秒
        uint8_t go = _readRegister(REG_GO);
        if ((go & 0x01) == 0) {
            // 校准完成，读取诊断结果
            uint8_t diag = _readRegister(REG_STATUS);
            Serial.printf("[Haptic] Calibration done. Status=0x%02X (0x00=OK)
", diag);
            _available = true;
            return true;
        }
        delay(50);
    }

    Serial.println("[Haptic] Calibration TIMEOUT (>1500ms)");
    _available = false;
    return false;
}

// ====== 效果播放 ======

void HapticDriver::playEffect(uint8_t effectId) {
    if (!_available) return;
    
    // 设置模式为内部触发
    _writeRegister(REG_MODE, MODE_INTERNAL);
    
    // 设置波形序列槽0 = 效果ID, 槽1 = 终止(0)
    _writeRegister(REG_WAVESEQ1, effectId);
    _writeRegister(REG_WAVESEQ2, 0x00);  // 终止
    
    // 触发播放
    _writeRegister(REG_GO, 0x01);
}

void HapticDriver::click() {
    playEffect(EFFECT_CLICK);
}

void HapticDriver::buzz() {
    playEffect(EFFECT_BUZZ);
}

void HapticDriver::strongHit() {
    playEffect(EFFECT_STRONG);
}

void HapticDriver::softTouch() {
    playEffect(EFFECT_SOFT);
}

void HapticDriver::playWaveform(const uint8_t* sequence, uint8_t count) {
    if (!_available || count == 0) return;
    
    // 限制为8个槽位
    if (count > 8) count = 8;
    
    // 设置为波形序列模式
    _writeRegister(REG_MODE, MODE_SEQUENCE);
    
    // 填充波形序列寄存器
    for (uint8_t i = 0; i < count; i++) {
        _writeRegister(REG_WAVESEQ1 + i, sequence[i]);
    }
    // 终止标记
    if (count < 8) {
        _writeRegister(REG_WAVESEQ1 + count, 0x00);
    }
    
    // 触发播放
    _writeRegister(REG_GO, 0x01);
}

void HapticDriver::stop() {
    if (!_available) return;
    
    // 写入Go=0停止播放
    _writeRegister(REG_GO, 0x00);
    
    // 或者设置模式为待机
    _writeRegister(REG_MODE, MODE_INTERNAL);
    _writeRegister(REG_WAVESEQ1, 0x00);  // 空序列
    _writeRegister(REG_GO, 0x01);  // 触发空序列=立即停止
}

void HapticDriver::setMotorType(uint8_t type) {
    _motorType = type;
    if (!_available) return;
    
    // 修改反馈寄存器中的LRA/ERM位
    uint8_t feedback = _readRegister(REG_FEEDBACK);
    if (type == 1) {
        feedback |= 0x80;   // bit7=1: LRA
    } else {
        feedback &= ~0x80;  // bit7=0: ERM
    }
    _writeRegister(REG_FEEDBACK, feedback);
    
    // 切换波形库
    _writeRegister(REG_LIBRARY, type == 1 ? 0x06 : 0x01);
}

// ====== 寄存器操作 ======

bool HapticDriver::_writeRegister(uint8_t reg, uint8_t value) {
    _wire.beginTransmission(DRV2605_ADDR);
    _wire.write(reg);
    _wire.write(value);
    return (_wire.endTransmission() == 0);
}

uint8_t HapticDriver::_readRegister(uint8_t reg) {
    _wire.beginTransmission(DRV2605_ADDR);
    _wire.write(reg);
    _wire.endTransmission();
    _wire.requestFrom((uint8_t)DRV2605_ADDR, (uint8_t)1);
    return _wire.available() ? _wire.read() : 0;
}
