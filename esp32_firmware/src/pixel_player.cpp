/*
 * 像素播放器模块 - 实现
 * 解析PXL二进制格式，管理PSRAM帧缓冲，提供播放控制
 */

#include "pixel_player.h"
#include <string.h>  // memcpy

PixelPlayer::PixelPlayer()
    : _frameBuffer(nullptr)
    , _currentFrame(0)
    , _state(PXL_IDLE)
    , _lastFrameTime(0)
    , _loaded(false)
{
    memset(&_header, 0, sizeof(PxlFileHeader));
}

PixelPlayer::~PixelPlayer() {
    release();
}

bool PixelPlayer::validateHeader(const uint8_t* data, size_t len) const {
    // 最小长度检查
    if (len < PXL_HEADER_SIZE) {
        Serial.println("[PixelPlayer] Data too small for header");
        return false;
    }

    const PxlFileHeader* hdr = (const PxlFileHeader*)data;

    // Magic检查
    if (hdr->magic[0] != 'P' || hdr->magic[1] != 'X' || hdr->magic[2] != 'L') {
        Serial.println("[PixelPlayer] Invalid magic");
        return false;
    }

    // 版本检查
    if (hdr->version != 1) {
        Serial.printf("[PixelPlayer] Unsupported version: %d\n", hdr->version);
        return false;
    }

    // 尺寸检查
    if (hdr->width == 0 || hdr->height == 0 || hdr->frame_count == 0) {
        Serial.println("[PixelPlayer] Invalid dimensions or frame count");
        return false;
    }

    // 最大帧数检查
    if (hdr->frame_count > PXL_MAX_FRAMES) {
        Serial.printf("[PixelPlayer] Too many frames: %d (max %d)\n", hdr->frame_count, PXL_MAX_FRAMES);
        return false;
    }

    // 总数据长度检查
    size_t expected = PXL_HEADER_SIZE + (size_t)hdr->frame_count * hdr->width * hdr->height * 2;
    if (len < expected) {
        Serial.printf("[PixelPlayer] Data too small: got %u, need %u\n", len, expected);
        return false;
    }

    return true;
}

bool PixelPlayer::loadFromBuffer(const uint8_t* data, size_t len) {
    // 先释放旧数据
    release();

    // 验证头部
    if (!validateHeader(data, len)) {
        return false;
    }

    // 拷贝头部
    memcpy(&_header, data, PXL_FILE_HEADER_SIZE);

    // 设置默认帧间隔
    if (_header.frame_interval == 0) {
        _header.frame_interval = 200;
    }

    // 计算总帧缓冲大小
    size_t totalSize = (size_t)_header.frame_count * _header.width * _header.height * 2;

    // 在PSRAM中分配缓冲区
    _frameBuffer = (uint16_t*)ps_malloc(totalSize);
    if (!_frameBuffer) {
        Serial.printf("[PixelPlayer] Failed to allocate %u bytes in PSRAM\n", totalSize);
        return false;
    }

    // 拷贝像素数据到PSRAM
    memcpy(_frameBuffer, data + PXL_HEADER_SIZE, totalSize);

    _currentFrame = 0;
    _state = PXL_STOPPED;
    _loaded = true;

    Serial.printf("[PixelPlayer] Loaded: %dx%d, %d frames, interval=%dms, %u bytes\n",
        _header.width, _header.height, _header.frame_count,
        _header.frame_interval, totalSize);

    return true;
}

void PixelPlayer::play() {
    if (!_loaded) return;
    _state = PXL_PLAYING;
    _lastFrameTime = millis();
    Serial.println("[PixelPlayer] Playing");
}

void PixelPlayer::pause() {
    if (_state == PXL_PLAYING) {
        _state = PXL_PAUSED;
        Serial.println("[PixelPlayer] Paused");
    }
}

void PixelPlayer::stop() {
    _state = PXL_STOPPED;
    _currentFrame = 0;
    Serial.println("[PixelPlayer] Stopped");
}

uint16_t* PixelPlayer::getCurrentFrame() {
    if (!_loaded || !_frameBuffer) return nullptr;

    size_t frameSize = _header.width * _header.height;
    return _frameBuffer + (frameSize * _currentFrame);
}

bool PixelPlayer::nextFrame() {
    if (!_loaded) return false;

    if (_currentFrame + 1 >= _header.frame_count) {
        if (isLooping()) {
            _currentFrame = 0;
            return true;
        }
        return false;  // 非循环模式，到达末帧
    }

    _currentFrame++;
    return true;
}

bool PixelPlayer::setFrameIndex(uint16_t idx) {
    if (!_loaded || idx >= _header.frame_count) return false;
    _currentFrame = idx;
    return true;
}

bool PixelPlayer::update() {
    if (!_loaded || _state != PXL_PLAYING) return false;

    unsigned long now = millis();
    if (now - _lastFrameTime >= _header.frame_interval) {
        _lastFrameTime = now;

        if (nextFrame()) {
            return true;  // 需要重绘
        } else {
            // 非循环模式播放结束
            if (!isLooping()) {
                _state = PXL_STOPPED;
                Serial.println("[PixelPlayer] Playback finished");
            }
            return true;
        }
    }

    return false;
}

void PixelPlayer::release() {
    if (_frameBuffer) {
        free(_frameBuffer);
        _frameBuffer = nullptr;
    }
    _loaded = false;
    _state = PXL_IDLE;
    _currentFrame = 0;
    memset(&_header, 0, sizeof(PxlFileHeader));
}
