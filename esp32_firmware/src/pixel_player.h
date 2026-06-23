/*
 * 像素播放器模块 - PXL格式解析与播放
 * 支持在PSRAM中缓存帧数据，提供播放控制接口
 */

#ifndef PIXEL_PLAYER_H
#define PIXEL_PLAYER_H

#include <Arduino.h>

// PXL文件格式常量
#define PXL_MAGIC_SIZE    3
#define PXL_HEADER_SIZE   16
#define PXL_DEFAULT_W     32
#define PXL_DEFAULT_H     32
#define PXL_MAX_FRAMES    64
#define PXL_FLAG_LOOP     0x0001
#define PXL_FLAG_RLE      0x0002
#define PXL_FLAG_DELTA    0x0004

// PXL文件头结构 (16字节, packed)
#pragma pack(push, 1)
struct PxlFileHeader {
    char     magic[3];        // "PXL"
    uint8_t  version;         // 1
    uint16_t width;           // 图像宽度
    uint16_t height;          // 图像高度
    uint16_t frame_count;     // 帧数
    uint16_t frame_interval;  // 帧间隔(ms)
    uint16_t flags;           // 标志位
    uint16_t reserved;        // 保留
};
#pragma pack(pop)

// 播放状态枚举
enum PxlPlayState {
    PXL_IDLE = 0,      // 未加载
    PXL_PLAYING,       // 播放中
    PXL_PAUSED,        // 暂停
    PXL_STOPPED        // 已停止
};

class PixelPlayer {
public:
    PixelPlayer();
    ~PixelPlayer();

    // 加载PXL数据（从内存缓冲区）
    bool loadFromBuffer(const uint8_t* data, size_t len);

    // 播放控制
    void play();
    void pause();
    void stop();

    // 帧操作
    uint16_t* getCurrentFrame();      // 获取当前帧RGB565数据指针
    bool nextFrame();                 // 切换到下一帧
    bool setFrameIndex(uint16_t idx); // 跳转到指定帧
    uint16_t getCurrentFrameIndex() const { return _currentFrame; }
    uint16_t getTotalFrames() const { return _header.frame_count; }
    uint16_t getFrameInterval() const { return _header.frame_interval; }

    // 状态查询
    bool isLoaded() const { return _loaded; }
    bool isPlaying() const { return _state == PXL_PLAYING; }
    bool isPaused() const { return _state == PXL_PAUSED; }
    PxlPlayState getState() const { return _state; }
    bool isLooping() const { return _header.flags & PXL_FLAG_LOOP; }

    // 动画更新（在主循环中调用，返回是否需要重绘）
    bool update();

    // 获取帧缓冲区指针（用于LCD pushImage）
    uint16_t* getFrameBuffer() const { return _frameBuffer; }
    uint16_t getWidth() const { return _header.width; }
    uint16_t getHeight() const { return _header.height; }

    // 释放内存
    void release();

private:
    PxlFileHeader _header;
    uint16_t*     _frameBuffer;    // PSRAM中分配的帧缓冲区
    uint16_t      _currentFrame;
    PxlPlayState  _state;
    unsigned long _lastFrameTime;
    bool          _loaded;

    // 辅助方法
    bool validateHeader(const uint8_t* data, size_t len) const;
    // [Step 6] 显式size_t转换，防止uint16_t乘法溢出
    size_t getFrameSize() const { return (size_t)_header.width * (size_t)_header.height * 2; }
    bool rleDecompress(const uint8_t* compressed, size_t compLen, uint16_t* output, size_t pixelCount);
    bool deltaDecompress(const uint8_t* deltaData, size_t deltaLen, const uint16_t* prevFrame, uint16_t* output, size_t pixelCount);
    bool allocPSRAMPBuffer(size_t totalSize);
    bool loadFrameData(const uint8_t* data, size_t len);
};

#endif // PIXEL_PLAYER_H
