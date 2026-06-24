# API 参考手册

本文档列出桌面电子宠物项目各子系统的公开 API，供开发者查阅和集成参考。

---

## 一、ESP32 端公开 API

ESP32 固件基于 Arduino 框架，使用 C++17。所有模块位于 `esp32_firmware/src/` 目录。

### 1.1 DisplayManager

显示管理模块，负责 LCD 驱动、表情动画、UI 绘制和屏幕休眠控制。

**文件**: `display_manager.h`

```cpp
class DisplayManager {
public:
    // 初始化
    DisplayManager();
    void begin();
    void update(const DisplayData& data);
    void updateAnimation();
    void showBootScreen(String message);

    // 屏幕休眠控制
    void dim();       // 降低亮度（数据超时）
    void sleep();     // 关闭背光（深度休眠）
    void wakeup();    // 恢复全亮

    // 亮度控制（一阶缓动 EMA）
    void setBrightness(uint8_t brightness);
    void setBrightnessImmediate(uint8_t brightness);
    void applySmoothBacklight();   // 每帧调用，平滑过渡

    // 夜览色温
    uint16_t nightShiftColor(uint16_t color) const;  // RGB565 暖色偏移
    void applyNightFilter();       // 按 NTP 时间自动调色温
    float getCurrentHour() const;  // 返回 0.0~24.0

    // 像素模式切换
    void setPixelMode(PixelPlayer* player);  // 进入自定义像素模式
    void setNormalMode();                     // 返回正常模式
    bool isPixelMode() const;
    DisplayMode getDisplayMode() const;
    PixelPlayer* getPixelPlayer() const;

    // 离线模式
    void drawClock();       // 显示实时时钟
    void drawBlinkAnim();   // 眨眼动画

    // V-Sync
    void waitForVSync(uint32_t timeout_ms = 20);
};
```

**表情类型枚举**:

```cpp
enum FaceType {
    FACE_HAPPY = 0,     // 空闲 - 开心放松
    FACE_WORKING = 1,   // 工作中 - 专注认真
    FACE_AUTH = 2,      // 需授权 - 紧张等待
    FACE_OFFLINE = 3,   // 离线 - 睡眠状态
};
```

**显示模式枚举**:

```cpp
enum DisplayMode {
    MODE_NORMAL = 0,    // 正常状态显示
    MODE_PIXEL,         // 自定义像素显示
};
```

**ThinkingStepCache** - PSRAM 思考链历史缓冲：

```cpp
class ThinkingStepCache {
public:
    void addStep(const String& stepText);
    uint8_t getVisibleSteps(ThinkingStep steps[], uint8_t maxCount) const;
    uint8_t count() const;
    bool hasNewStep() const;
    void clearNewFlag();
};
```

### 1.2 CommManager

通信管理模块，处理 WiFi TCP 连接和帧协议解析。

**文件**: `comm_manager.h`

```cpp
class CommManager {
public:
    CommManager();
    void begin();
    void setServer(String host, int port);
    void update();
    bool connect();
    void disconnect();
    void reconnect();
    bool isConnected();
    bool hasNewData();
    String getData();
    void sendHeartbeat();
    void sendMessage(String type, JsonObject data);
    unsigned long getLastReceiveTime() const;
    void sendFramed(const String& json);  // 带长度前缀的帧发送
};
```

**帧协议状态机**:

```cpp
enum FrameState {
    FRAME_IDLE,         // 等待新帧
    FRAME_READ_LEN,     // 读取长度前缀 "LEN:NNNN\n"
    FRAME_READ_BODY,    // 按长度读取 payload
    FRAME_LEGACY_LINE   // 兼容旧格式：\n 分隔
};
```

### 1.3 PixelPlayer

PXL 格式解析与像素动画播放器，支持 PSRAM 帧缓冲和差分解码。

**文件**: `pixel_player.h`

```cpp
class PixelPlayer {
public:
    PixelPlayer();
    ~PixelPlayer();

    // 加载
    bool loadFromBuffer(const uint8_t* data, size_t len);

    // 播放控制
    void play();
    void pause();
    void stop();

    // 帧操作
    uint16_t* getCurrentFrame();       // 获取当前帧 RGB565 数据指针
    bool nextFrame();                  // 切换到下一帧
    bool setFrameIndex(uint16_t idx);  // 跳转到指定帧
    uint16_t getCurrentFrameIndex() const;
    uint16_t getTotalFrames() const;
    uint16_t getFrameInterval() const;

    // 状态查询
    bool isLoaded() const;
    bool isPlaying() const;
    bool isPaused() const;
    PxlPlayState getState() const;
    bool isLooping() const;

    // 动画更新（主循环调用，返回是否需要重绘）
    bool update();

    // 帧缓冲
    uint16_t* getFrameBuffer() const;
    uint16_t getWidth() const;
    uint16_t getHeight() const;

    // 内存管理
    void release();
};
```

**PXL 文件头结构** (16 字节, packed):

```cpp
struct PxlFileHeader {
    char     magic[3];        // "PXL"
    uint8_t  version;         // 1
    uint16_t width;           // 图像宽度
    uint16_t height;          // 图像高度
    uint16_t frame_count;     // 帧数
    uint16_t frame_interval;  // 帧间隔 (ms)
    uint16_t flags;           // 标志位
    uint16_t reserved;        // 保留
};
```

**播放状态枚举**:

```cpp
enum PxlPlayState {
    PXL_IDLE = 0,    // 未加载
    PXL_PLAYING,     // 播放中
    PXL_PAUSED,      // 暂停
    PXL_STOPPED      // 已停止
};
```

### 1.4 传感器与外设 API

#### TouchHandler - 触摸与接近感应

**文件**: `touch_handler.h`

```cpp
enum TouchEvent {
    TOUCH_NONE,
    TOUCH_SINGLE_TAP,
    TOUCH_DOUBLE_TAP,
    TOUCH_LONG_PRESS,
    TOUCH_PROXIMITY       // 接近感应事件
};

class TouchHandler {
public:
    void begin();
    void update();
    void setCallback(TouchCallback cb);
    uint16_t readValue();
    bool isTouched();
    bool isProximityWakeActive() const;

    ProximitySensor proximity;  // 接近感应器实例
};

class ProximitySensor {
public:
    void begin();
    bool update();          // 每帧调用，返回 true 表示触发接近事件
    bool isNear() const;
    float getFastEMA() const;
    float getSlowEMA() const;
    uint16_t getBaseline() const;
    unsigned long getLastNearTime() const;
};
```

#### AmbientLightManager - BH1750 环境光传感器

**文件**: `ambient_light.h`

```cpp
class AmbientLightManager {
public:
    static constexpr uint8_t BH1750_ADDR = 0x23;  // I2C 地址

    bool begin(int sdaPin = 41, int sclPin = 42);
    int16_t readLux();                          // 返回 0~65535 lx，-1=失败
    uint8_t autoAdjustBacklight(int16_t lux);   // 返回推荐 PWM (0~255)
    int16_t getLastLux() const;                 // 缓存值
    void powerDown();                           // 低功耗模式
    void powerUp();
    bool isAvailable() const;
};
```

**自动背光映射曲线**: 10lx=20%, 100lx=50%, 1000lx=100%

#### HapticDriver - DRV2605L 触觉反馈

**文件**: `haptic_driver.h`

```cpp
class HapticDriver {
public:
    static constexpr uint8_t DRV2605_ADDR = 0x5A;

    bool begin(int sdaPin = 41, int sclPin = 42);
    void playEffect(uint8_t effectId);   // 1~123 预设效果
    void click();                         // 轻击（触摸确认）
    void buzz();                          // 嗡嗡（通知）
    void strongHit();                     // 强击（警告）
    void softTouch();                     // 软触（滑动反馈）
    void playWaveform(const uint8_t* sequence, uint8_t count);
    void stop();
    bool calibrate();                     // 自动校准 LRA 参数
    void setMotorType(uint8_t type);      // 0=ERM, 1=LRA
    bool isAvailable() const;
};
```

#### SoundManager - 蜂鸣器音频

**文件**: `sound_manager.h`

```cpp
class SoundManager {
public:
    void begin();
    void beep(uint16_t freq = 2000, uint16_t duration = 50);
    void beepSine(uint16_t freq, uint16_t duration);   // 正弦波柔和音调
    void beepPattern(uint16_t freq, uint16_t onMs, uint16_t offMs, uint8_t count);
    void playStartup();
    void playNotification();
    void playAlert();
    void playOtaProgress();
    void playOtaSuccess();
    void playOtaFail();
    void setEnabled(bool enabled);
    bool isEnabled() const;

    enum AudioMode { AUDIO_PWM, AUDIO_I2S_PDM };
    void setAudioMode(AudioMode mode);
    AudioMode getAudioMode() const;
};
```

#### WiFiManager - WiFi 连接管理

**文件**: `wifi_manager.h`

```cpp
class WiFiManager {
public:
    void begin();
    bool connect();                              // 连接已保存的 WiFi
    bool tryUDPDiscovery(unsigned long timeoutMs = 15000);  // 自动发现 PC 服务器
    void startConfigMode();                      // 启动配网模式
    void handleConfig();                         // 处理配网请求
    bool isConfiguring();
    bool isConnected();
    String getIP();
    String getServerHost();
    int getServerPort();
    void disconnect();
};
```

---

## 二、PC 端模块 API

PC 端使用 Python 编写，所有模块位于 `pc_monitor/modules/` 目录。

### 2.1 AgentMonitor - AI Agent 状态监控

**文件**: `pc_monitor/modules/agent_monitor.py`

通过进程 CPU 使用率和 JSONL 日志文件检测 Agent 工作状态。

```python
class AgentStatus(Enum):
    IDLE = "idle"           # 空闲
    WORKING = "working"     # 工作中
    AUTHORIZING = "auth"    # 等待授权
    OFFLINE = "offline"     # 离线

@dataclass
class AgentState:
    status: AgentStatus
    process_name: str
    pid: Optional[int]
    cpu_percent: float
    memory_mb: float
    uptime_seconds: float
    timestamp: float

class AgentMonitor:
    def __init__(self, config: Dict[str, Any]) -> None:
        """
        Args:
            config: 配置字典
                - process_names: List[str] - 监控的进程名列表，默认 ["claudecode", "codex"]
                - check_interval: int - 检查间隔(秒)，默认 2
                - auth_jsonl_dirs: List[str] - JSONL 日志目录，默认 ["~/.claude/projects"]
                - auth_jsonl_max_lines: int - JSONL 扫描行数，默认 30
        """

    def get_state(self) -> AgentState:
        """获取当前 Agent 状态

        优先使用 PID 缓存验证（微秒级），仅在缓存失效时
        触发全量进程遍历。

        状态判断逻辑:
            - CPU 滑动窗口均值 > 30%: WORKING
            - 3% < CPU <= 30%: AUTHORIZING
            - CPU <= 3% 连续 6 次(~12s): IDLE
            - 进程不存在: OFFLINE

        Returns:
            AgentState 数据对象
        """

    def start_monitoring(self, callback=None):
        """启动持续监控循环

        Args:
            callback: 可选回调函数，每次检查后调用 callback(state)
        """

    def stop_monitoring(self):
        """停止监控（立即生效，无需等待当前间隔结束）"""
```

**状态判断常量**:

| 常量 | 值 | 说明 |
|------|-----|------|
| `CPU_THRESHOLD_WORKING` | 30.0 | CPU 高于此值判定为工作中 |
| `CPU_THRESHOLD_AUTHORIZING` | 3.0 | CPU 低于此值开始计数空闲 |
| `IDLE_CONFIRM_COUNT` | 6 | 连续低 CPU 次数确认空闲（约 12 秒） |
| `CPU_HISTORY_WINDOW` | 5 | CPU 滑动窗口大小 |

### 2.2 TokenTracker - Token 使用统计

**文件**: `pc_monitor/modules/token_stats.py`

解析 AI Agent 日志文件，统计 Token 消耗和费用。

```python
@dataclass
class TokenStats:
    total_input_tokens: int
    total_output_tokens: int
    total_requests: int
    tokens_last_hour: int
    tokens_last_day: int
    estimated_cost_usd: float
    timestamp: float

class TokenTracker:
    def __init__(self, config: dict):
        """
        Args:
            config: 配置字典
                - log_paths: List[str] - 日志文件/目录路径列表
                - update_interval: int - 轮询间隔(秒)，默认 30
                - auto_discover: bool - 是否自动发现 JSONL 文件
                - auto_discover_dirs: List[str] - 自动发现目录列表
                - auto_discover_pattern: str - 文件匹配模式，默认 "*.jsonl"
        """

    def get_stats(self) -> TokenStats:
        """获取 Token 统计（增量更新）

        内部使用 LogTailer 增量读取日志文件，避免全量扫描。
        10 秒内返回缓存结果。

        Returns:
            TokenStats 数据对象
        """
```

**费用估算定价** (USD / 1M tokens):

| 模型 | Input | Output |
|------|-------|--------|
| claude-3-opus | $15.00 | $75.00 |
| claude-3-sonnet | $3.00 | $15.00 |
| claude-3-haiku | $0.25 | $1.25 |
| default | $3.00 | $15.00 |

**LogTailer** - 增量日志读取器：

```python
class LogTailer:
    def read_new_lines(self, file_path: str) -> List[str]:
        """读取文件新增行，跳过已读部分

        支持文件轮转检测（inode 变化或文件缩小）。
        首次读取从文件末尾 10KB 开始。
        """
```

### 2.3 WeatherService - 天气信息获取

**文件**: `pc_monitor/modules/weather.py`

调用 OpenWeatherMap API 获取实时天气数据。

```python
@dataclass
class WeatherInfo:
    city: str
    temperature: float      # 温度 (C)
    feels_like: float       # 体感温度 (C)
    humidity: int           # 湿度 (%)
    description: str        # 天气描述
    icon_code: str          # 图标代码 (如 "01d")
    wind_speed: float       # 风速 (m/s)
    timestamp: float

class WeatherService:
    BASE_URL = "https://api.openweathermap.org/data/2.5/weather"

    def __init__(self, config: Dict[str, Any]) -> None:
        """
        Args:
            config: 配置字典
                - api_key: str - OpenWeatherMap API Key
                - city: str - 城市名，默认 "Beijing"
                - update_interval: int - 默认刷新间隔(秒)，默认 1800
                - update_interval_idle: int - 空闲时刷新间隔，默认 3600
                - update_interval_working: int - 工作时刷新间隔，默认 600
                - cache_file: str - 缓存文件路径
        """

    def fetch_weather(self) -> Optional[WeatherInfo]:
        """获取天气信息

        优先使用缓存，缓存过期则请求 API。
        API 失败时返回缓存或模拟数据。
        根据 Agent 状态动态调整刷新频率。

        Returns:
            WeatherInfo 对象，失败时返回模拟数据
        """

    def set_agent_status(self, status: str):
        """设置当前 Agent 状态，影响天气刷新频率"""

    def get_icon_name(self, icon_code: str) -> str:
        """获取 ESP32 显示用图标名称

        Args:
            icon_code: OpenWeatherMap 图标代码 (如 "01d")

        Returns:
            图标名称 (如 "sun", "cloud", "rain")
        """
```

**图标映射表**:

| icon_code | 显示名称 | 描述 |
|-----------|---------|------|
| `01d` | `sun` | 晴天 |
| `01n` | `moon` | 晴夜 |
| `02d` | `cloud_sun` | 少云 |
| `02n` | `cloud_moon` | 少云夜 |
| `03d/n` | `cloud` | 多云 |
| `04d/n` | `clouds` | 阴天 |
| `09d/n` | `rain_light` | 小雨 |
| `10d/n` | `rain` | 雨 |
| `11d/n` | `thunder` | 雷暴 |
| `13d/n` | `snow` | 雪 |
| `50d/n` | `fog` | 雾 |

### 2.4 Communication - PC 与 ESP32 通信

**文件**: `pc_monitor/modules/communication.py`

支持串口和 WiFi 两种通信模式，PC 端作为 TCP Server 等待 ESP32 连接。

```python
@dataclass
class DeviceMessage:
    msg_type: str       # 消息类型: status, token, weather, animation, ping, pixel_data
    data: dict          # 消息数据
    timestamp: float    # 时间戳

class CommunicationBase:
    """通信基类"""

    def set_message_callback(self, callback: Callable[[DeviceMessage], None]):
        """设置消息回调"""

    def connect(self) -> bool:
        """建立连接"""

    def disconnect(self):
        """断开连接"""

    def send_message(self, msg: DeviceMessage) -> bool:
        """发送消息"""

    def is_connected(self) -> bool:
        """是否已连接"""

class SerialCommunication(CommunicationBase):
    """串口通信 (COM 端口)"""

    def __init__(self, config: dict):
        """
        Args:
            config: 配置字典
                - serial_port: str - 串口名，默认 "COM3"
                - serial_baud: int - 波特率，默认 115200
        """

class WiFiCommunication(CommunicationBase):
    """WiFi 通信 (PC 作为 TCP Server)"""

    def __init__(self, config: dict):
        """
        Args:
            config: 配置字典
                - wifi_host: str - 监听地址，默认 "0.0.0.0"
                - wifi_port: int - 监听端口，默认 19876
                - udp_broadcast_port: int - UDP 广播端口，默认 19877
                - udp_broadcast_interval: int - 广播间隔(秒)，默认 5
        """

    @staticmethod
    def resolve_mdns(hostname: str = "deskpet.local") -> Optional[str]:
        """通过 mDNS 解析设备主机名"""

def create_communication(config: dict) -> CommunicationBase:
    """工厂函数：根据 mode 配置创建通信实例

    Args:
        config: 必须包含 mode 字段 ("serial" 或 "wifi")

    Returns:
        SerialCommunication 或 WiFiCommunication 实例
    """
```

**帧协议**: 所有消息使用 `LEN:<length>\n<payload>\n` 格式发送，最大帧大小 128KB。

**心跳机制**: WiFi 模式下每 10 秒发送 ping，30 秒无 pong 响应视为断连。

---

## 三、像素工具 Python API

像素工具位于 `pixel_tool/` 目录，提供 PXL 格式的编码、解码和网络发送功能。

### 3.1 pxl_encoder - PXL 编码器

**文件**: `pixel_tool/pxl_encoder.py`

将图片/GIF 转换为 .pxl 二进制像素文件。

```python
# 常量
PXL_MAGIC = b'PXL'
PXL_VERSION = 1
PXL_FLAG_RLE = 0x0002    # RLE 压缩标志
PXL_FLAG_DELTA = 0x0004  # 差分帧编码标志
DEFAULT_SIZE = (32, 32)
DEFAULT_INTERVAL = 200   # ms


def rgb888_to_rgb565(r: int, g: int, b: int) -> int:
    """RGB888 转 RGB565

    Args:
        r, g, b: 0~255 颜色分量

    Returns:
        RGB565 格式的 16 位颜色值
    """


def image_to_rgb565_data(img: Image.Image) -> bytes:
    """将 PIL 图像转换为 RGB565 字节数据

    使用 numpy 向量化，比纯 Python 循环快 10-50 倍。

    Args:
        img: PIL Image 对象

    Returns:
        RGB565 字节数据 (width * height * 2 bytes)
    """


def rle_compress(rgb565_data: bytes) -> bytes:
    """RLE 压缩 RGB565 数据流

    格式:
        - bit7=1: run，后接 2 字节重复像素 (big-endian)
        - bit7=0: literal，后接 flag*2 字节原始像素

    Args:
        rgb565_data: 原始 RGB565 字节数据

    Returns:
        RLE 压缩后的字节数据
    """


def create_pxl_header(width: int, height: int, frame_count: int,
                      frame_interval: int = 200, flags: int = 1) -> bytes:
    """创建 PXL 文件头 (16 字节)

    Args:
        width: 图像宽度
        height: 图像高度
        frame_count: 帧数
        frame_interval: 帧间隔 (ms)
        flags: 标志位 (bit0=loop, bit1=RLE, bit2=delta)

    Returns:
        16 字节文件头
    """


def image_to_pxl(image_path: str, output_path: str = None,
                 size: tuple = (32, 32), interval: int = 200,
                 loop: bool = True) -> str:
    """将单张图片转换为 .pxl 文件

    Args:
        image_path: 输入图片路径
        output_path: 输出路径，默认与输入同名 .pxl
        size: 目标尺寸，默认 (32, 32)
        interval: 帧间隔 (ms)
        loop: 是否循环播放

    Returns:
        输出文件路径
    """


def gif_to_pxl(gif_path: str, output_path: str = None,
               size: tuple = (32, 32), max_frames: int = 16,
               loop: bool = True, progress_cb=None) -> str:
    """将 GIF 动画转换为 .pxl 多帧文件

    自动启用差分帧压缩 (delta encoding)，后续帧仅编码变化像素，
    传输量降低 60-90%。

    Args:
        gif_path: 输入 GIF 路径
        output_path: 输出路径
        size: 目标尺寸
        max_frames: 最大帧数限制
        loop: 是否循环播放
        progress_cb: 进度回调 (current, total)

    Returns:
        输出文件路径
    """


def png_to_pxl_frames(png_path: str, output_path: str = None,
                      size: tuple = (32, 32), interval: int = 200,
                      progress_cb=None) -> str:
    """将 PNG 雪碧图 (水平排列帧序列) 转换为 .pxl 文件

    自动检测帧数：图像宽度 / 高度 = 帧数。

    Args:
        png_path: 输入雪碧图路径
        output_path: 输出路径
        size: 目标尺寸
        interval: 帧间隔 (ms)
        progress_cb: 进度回调

    Returns:
        输出文件路径
    """
```

#### DeltaCompressor - 差分帧编码器

```python
class DeltaCompressor:
    """PXL 帧间差分编码器：仅编码变化像素，降低传输量 60-90%"""

    @staticmethod
    def encode(prev_rgb565: bytes, curr_rgb565: bytes) -> bytes:
        """生成差分帧

        Args:
            prev_rgb565: 前一帧 RGB565 数据
            curr_rgb565: 当前帧 RGB565 数据

        Returns:
            delta opcodes (不含帧头)

        Opcode 类型:
            - DELTA_COPY (0x00): 跳过不变像素
            - DELTA_REPEAT (0x01): N 个连续变化像素 (同一新值)
            - DELTA_LITERAL (0x02): N 个像素 (各自新值)
        """

    @staticmethod
    def decode(prev_rgb565: bytes, delta_data: bytes, pixel_count: int) -> bytes:
        """从差分帧还原完整帧

        Args:
            prev_rgb565: 前一帧 RGB565 数据
            delta_data: 差分 opcodes
            pixel_count: 像素总数

        Returns:
            还原后的完整 RGB565 数据
        """
```

### 3.2 pxl_decoder - PXL 解码器

**文件**: `pixel_tool/pxl_decoder.py`

将 .pxl 二进制文件解码为图片或 GIF。

```python
def read_pxl_header(data: bytes) -> dict:
    """读取 PXL 文件头

    Args:
        data: 文件原始字节

    Returns:
        字典包含: version, width, height, frame_count, frame_interval, flags

    Raises:
        ValueError: 文件过小或 magic 不匹配
    """


def rle_decompress(compressed: bytes, pixel_count: int) -> bytes:
    """RLE 解压为原始 RGB565 数据

    Args:
        compressed: RLE 压缩字节流
        pixel_count: 期望像素总数

    Returns:
        解压后的 RGB565 字节流 (pixel_count * 2 bytes)
    """


def pxl_to_frames(pxl_path: str) -> list:
    """将 PXL 文件解码为 PIL 图像帧列表

    自动识别 RLE 压缩格式。

    Args:
        pxl_path: .pxl 文件路径

    Returns:
        list[PIL.Image.Image] 图像帧列表
    """


def pxl_to_png(pxl_path: str, output_path: str = None) -> str:
    """将 PXL 文件解码为 PNG (取第一帧)

    Args:
        pxl_path: .pxl 文件路径
        output_path: 输出路径

    Returns:
        输出文件路径
    """


def pxl_to_gif(pxl_path: str, output_path: str = None) -> str:
    """将 PXL 动画文件解码为 GIF

    Args:
        pxl_path: .pxl 文件路径
        output_path: 输出路径

    Returns:
        输出文件路径
    """
```

### 3.3 pxl_sender - PXL 网络发送器

**文件**: `pixel_tool/pxl_sender.py`

通过 TCP 将 .pxl 文件发送到 ESP32 桌面宠物。

```python
# 常量
CHUNK_PIXEL_BYTES = 1024     # 每包数据大小
DEFAULT_ESP32_PORT = 19876   # 默认 ESP32 端口
SEND_TIMEOUT = 10.0          # 发送超时 (秒)
CHUNK_SEND_DELAY = 0.05      # 包间延迟 (秒)


def pxl_to_base64_chunks(pxl_path: str, chunk_size: int = 1024) -> list:
    """读取 .pxl 文件并分包

    Args:
        pxl_path: .pxl 文件路径
        chunk_size: 每包字节数

    Returns:
        包列表，每包包含 format, width, height, frame_count,
        packet_index, total_packets, chunk_base64 等字段
    """


def send_pxl_to_esp32(pxl_path: str, host: str, port: int = 19876,
                      timeout: float = 10.0, switch_mode: bool = True) -> bool:
    """将 .pxl 文件发送到 ESP32

    发送完成后自动发送 pixel_cmd 切换到像素模式。

    Args:
        pxl_path: .pxl 文件路径
        host: ESP32 IP 地址
        port: 端口号
        timeout: 连接超时
        switch_mode: 是否自动切换到像素模式

    Returns:
        是否发送成功
    """


def send_pixel_command(host: str, port: int, command: str,
                       mode: str = None) -> bool:
    """发送像素显示控制命令

    Args:
        host: ESP32 IP 地址
        port: 端口号
        command: 命令名称 (如 "play", "pause", "stop")
        mode: 模式名称 (如 "pixel", "normal")

    Returns:
        是否发送成功
    """
```

---

## 附录：消息协议速查

### PC -> ESP32 消息类型

| type | data 字段 | 说明 |
|------|----------|------|
| `status` | `{agent: str, cpu: float, mem: float}` | Agent 状态更新 |
| `token` | `{total: int, hour: int, cost: float}` | Token 统计更新 |
| `weather` | `{temp: float, icon: str, city: str}` | 天气信息更新 |
| `animation` | `{expression: str}` | 表情切换 |
| `pixel_data` | `{chunk_base64: str, packet_index: int, ...}` | PXL 分包数据 |
| `pixel_cmd` | `{command: str, mode: str}` | 像素模式控制 |
| `ping` | `{}` | 心跳探测 |

### ESP32 -> PC 消息类型

| type | data 字段 | 说明 |
|------|----------|------|
| `pong` | `{}` | 心跳响应 |
| `crash_report` | `{reason: str, count: int, stack: str}` | 崩溃遥测 |
| `touch_event` | `{event: str}` | 触摸事件反馈 |

### 通信参数

| 参数 | 值 |
|------|-----|
| TCP Server 端口 | 19876 |
| UDP 广播端口 | 19877 |
| 串口波特率 | 115200 |
| 帧格式 | `LEN:<length>\n<payload>\n` |
| 最大帧大小 | 128 KB |
| 心跳间隔 | 10 秒 |
| 心跳超时 | 30 秒 |
| mDNS 主机名 | `deskpet.local` |
