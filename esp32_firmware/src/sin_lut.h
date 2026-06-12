/*
 * 64-sample sine lookup table (8-bit, centered at 128)
 * 用于蜂鸣器产生柔和平滑的正弦波音调
 */
#ifndef SIN_LUT_H
#define SIN_LUT_H

#include <cstdint>

static const uint8_t SIN_LUT[64] = {
    128, 140, 152, 164, 176, 186, 196, 204,
    212, 218, 224, 228, 231, 233, 234, 233,
    231, 228, 224, 218, 212, 204, 196, 186,
    176, 164, 152, 140, 128, 116, 104,  92,
     80,  70,  60,  52,  44,  38,  32,  28,
     25,  23,  22,  23,  25,  28,  32,  38,
     44,  52,  60,  70,  80,  92, 104, 116,
    128, 140, 152, 164, 176, 186, 196, 204
};

#define SIN_LUT_SIZE 64
#define PWM_CARRIER_HZ 40000  // 40kHz PWM载波（不可闻，适合压电蜂鸣器）

#endif // SIN_LUT_H
