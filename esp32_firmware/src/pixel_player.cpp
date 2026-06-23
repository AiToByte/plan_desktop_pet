/*
 * 像素播放器模块 - 实现
 * 解析PXL二进制格式，管理PSRAM帧缓冲，提供播放控制
 */

#include "pixel_player.h"
#include <string.h>  // memcpy
#include "log.h"

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
        LOG_I("Data too small for header");
        return false;
    }

    const PxlFileHeader* hdr = (const PxlFileHeader*)data;

    // Magic检查
    if (hdr->magic[0] != 'P' || hdr->magic[1] != 'X' || hdr->magic[2] != 'L') {
        LOG_E("Invalid magic");
        return false;
    }

    // 版本检查
    if (hdr->version != 1) {
        LOG_I("Unsupported version: %d\n", hdr->version);
        return false;
    }

    // 尺寸检查
    if (hdr->width == 0 || hdr->height == 0 || hdr->frame_count == 0) {
        LOG_E("Invalid dimensions or frame count");
        return false;
    }

    // 最大帧数检查
    if (hdr->frame_count > PXL_MAX_FRAMES) {
        LOG_I("Too many frames: %d (max %d)\n", hdr->frame_count, PXL_MAX_FRAMES);
        return false;
    }

    // 总数据长度检查
    size_t expected = PXL_HEADER_SIZE + (size_t)hdr->frame_count * hdr->width * hdr->height * 2;
    if (len < expected) {
        LOG_I("Data too small: got %u, need %u\n", len, expected);
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
    memcpy(&_header, data, PXL_HEADER_SIZE);

    // 设置默认帧间隔
    if (_header.frame_interval == 0) {
        _header.frame_interval = 200;
    }

    // [Step 4] 计算总帧缓冲大小（使用size_t防止uint16_t溢出）
    size_t totalSize = (size_t)_header.frame_count * (size_t)_header.width * (size_t)_header.height * 2;
    
    // 分配PSRAM帧缓冲（使用预分配池减少碎片）
    if (!allocPSRAMPBuffer(totalSize)) {
        return false;
    }

    // 加载帧数据到缓冲区（RLE解压或原始拷贝）
    if (!loadFrameData(data, len)) {
        return false;
    }

    _currentFrame = 0;
    _state = PXL_STOPPED;
    _loaded = true;

    LOG_I("Loaded: %dx%d, %d frames, interval=%dms, %u bytes\n", _header.width, _header.height, _header.frame_count, _header.frame_interval, totalSize);

    return true;
}

// PSRAM预分配池：复用静态缓冲区，避免反复ps_malloc/free导致堆碎片
bool PixelPlayer::allocPSRAMPBuffer(size_t totalSize) {
    static uint16_t* s_psramPool = nullptr;
    static size_t    s_poolSize  = 0;
    
    if (s_poolSize < totalSize) {
        if (s_psramPool) { free(s_psramPool); s_psramPool = nullptr; }
        s_psramPool = (uint16_t*)ps_malloc(totalSize);
        if (!s_psramPool) {
            LOG_E("Failed to allocate %u bytes in PSRAM pool\n", totalSize);
            s_poolSize = 0;
            return false;
        }
        s_poolSize = totalSize;
        LOG_I("PSRAM pool allocated: %u bytes\n", totalSize);
    }
    _frameBuffer = s_psramPool;
    return true;
}

// 加载帧数据：RLE压缩则逐帧解压，否则直接memcpy
bool PixelPlayer::loadFrameData(const uint8_t* data, size_t len) {
    size_t totalSize = (size_t)_header.frame_count * (size_t)_header.width * (size_t)_header.height * 2;

    if (_header.flags & PXL_FLAG_RLE) {
        size_t pixelsPerFrame = (size_t)_header.width * _header.height;
        const uint8_t* src = data + PXL_HEADER_SIZE;
        size_t remaining = len - PXL_HEADER_SIZE;

        for (uint16_t f = 0; f < _header.frame_count; f++) {
            uint16_t* dst = _frameBuffer + f * pixelsPerFrame;
            if (!rleDecompress(src, remaining, dst, pixelsPerFrame)) {
                LOG_E("RLE decompress failed at frame %d\n", f);
                free(_frameBuffer);
                _frameBuffer = nullptr;
                return false;
            }
            // 前进src：扫描压缩数据实际消耗的字节数
            size_t consumed = 0;
            size_t decoded = 0;
            while (decoded < pixelsPerFrame && consumed < remaining) {
                uint8_t flag = src[consumed++];
                if (flag & 0x80) {
                    decoded += flag & 0x7F;
                    consumed += 2;
                } else {
                    decoded += flag;
                    consumed += flag * 2;
                }
            }
            src += consumed;
            remaining -= consumed;
        }
        LOG_I("RLE decompressed %d frames OK\n", _header.frame_count);
    } else {
        memcpy(_frameBuffer, data + PXL_HEADER_SIZE, totalSize);
    }
    return true;
}

void PixelPlayer::play() {
    if (!_loaded) return;
    _state = PXL_PLAYING;
    _lastFrameTime = millis();
    LOG_I("Playing");
}

void PixelPlayer::pause() {
    if (_state == PXL_PLAYING) {
        _state = PXL_PAUSED;
        LOG_I("Paused");
    }
}

void PixelPlayer::stop() {
    _state = PXL_STOPPED;
    _currentFrame = 0;
    LOG_I("Stopped");
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
                LOG_I("Playback finished");
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

// ============ RLE 解压 ============
// 格式: flag_byte >= 0x80 → run长度=(flag & 0x7F), 后2字节像素(big-endian)
//        flag_byte <  0x80 → literal长度=flag, 后 flag*2 字节原始像素
bool PixelPlayer::rleDecompress(const uint8_t* compressed, size_t compLen, uint16_t* output, size_t pixelCount) {
    size_t ci = 0;   // compressed index
    size_t oi = 0;   // output index

    while (oi < pixelCount && ci < compLen) {
        uint8_t flag = compressed[ci++];
        if (flag & 0x80) {
            // Run-length: 重复同一个像素 (bounds check hoisted out of loop)
            uint8_t count = flag & 0x7F;
            if (ci + 2 > compLen) return false;
            uint16_t pixel = ((uint16_t)compressed[ci] << 8) | compressed[ci + 1]; // big-endian
            ci += 2;
            if (oi + count > pixelCount) count = pixelCount - oi;
            uint16_t* dst = output + oi;
            for (uint8_t i = 0; i < count; i++) dst[i] = pixel;
            oi += count;
        } else {
            // Literal: 直接拷贝原始像素 (bounds check hoisted, pointer write)
            uint8_t count = flag;
            if (ci + count * 2 > compLen) return false;
            if (oi + count > pixelCount) count = pixelCount - oi;
            uint16_t* dst = output + oi;
            for (uint8_t i = 0; i < count; i++) {
                dst[i] = ((uint16_t)compressed[ci] << 8) | compressed[ci + 1];
                ci += 2;
            }
            oi += count;
        }
    }
    return (oi == pixelCount);
}
