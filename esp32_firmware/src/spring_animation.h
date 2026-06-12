/*
 * 弹簧物理动画器 — 数值弹性过渡（苹果级体验）
 * 阻尼弹簧模型 + 滞回死区消除微抖
 */
#ifndef SPRING_ANIMATION_H
#define SPRING_ANIMATION_H

#include <Arduino.h>
#include <math.h>

class SpringAnimator {
public:
    SpringAnimator(float stiffness = 0.03f, float damping = 0.85f,
                   float hysteresis = 0.5f);

    void setTarget(float target);
    bool update(unsigned long dt_ms);
    float current() const { return _current; }
    float target()  const { return _target;  }
    bool  isSettled() const { return _settled; }

private:
    float _current;
    float _target;
    float _velocity;
    float _stiffness;   // 0.01~0.10（越大越快）
    float _damping;     // 0.70~0.95（越大越飘，临界≈0.87）
    float _hysteresis;  // 目标值死区（同值不重触发）
    bool  _settled;
};

#endif // SPRING_ANIMATION_H
