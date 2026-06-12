/*
 * 弹簧物理动画器实现 — 阻尼弹簧 + 滞回死区
 */
#include "spring_animation.h"

SpringAnimator::SpringAnimator(float stiffness, float damping, float hysteresis)
    : _current(0), _target(0), _velocity(0)
    , _stiffness(stiffness), _damping(damping)
    , _hysteresis(hysteresis), _settled(true) {}

void SpringAnimator::setTarget(float target) {
    // 滞回死区：目标变化小于阈值不触发
    if (fabsf(target - _target) < _hysteresis) return;
    _target = target;
    _settled = false;
}

bool SpringAnimator::update(unsigned long dt_ms) {
    if (_settled) return false;

    // 时间归一化（以20ms为基准）
    float dt = dt_ms / 20.0f;
    if (dt < 0.1f) dt = 0.1f;
    if (dt > 5.0f) dt = 5.0f;

    // 阻尼弹簧物理：F = -k*x - c*v
    float displacement = _current - _target;
    float springForce  = -_stiffness * displacement;
    _velocity = (_velocity + springForce * dt) * _damping;
    _current += _velocity * dt;

    // 收敛判定：距离<0.01 且 速度<0.01
    if (fabsf(displacement) < 0.01f && fabsf(_velocity) < 0.01f) {
        _current  = _target;
        _velocity = 0;
        _settled  = true;
        return true;
    }
    return true;
}
