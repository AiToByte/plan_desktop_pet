/*
 * BLE 零配网模块
 * 
 * 功能:
 *   - 无WiFi配置时自动进入BLE配网模式
 *   - 广播设备信息，接收WiFi凭据
 *   - 配网完成后自动连接WiFi
 * 
 * BLE Service: 0x1820 (自定义配网服务)
 *   Characteristic 0x2A69: WiFi SSID (读/写)
 *   Characteristic 0x2A6A: WiFi Password (写)
 *   Characteristic 0x2A6B: 资源URL (写)
 *   Characteristic 0x2A6C: 配网状态 (读/通知)
 * 
 * 协议: 设备广播 → 手机/PC连接 → 写入凭据 → ESP32连接WiFi
 */

#ifndef BLE_CONFIG_H
#define BLE_CONFIG_H

#include <Arduino.h>
#include <NimBLEDevice.h>

// 配网状态码
enum BleConfigState : uint8_t {
    BLE_CONFIG_IDLE = 0,          // 空闲
    BLE_CONFIG_ADVERTISING,       // 广播中
    BLE_CONFIG_CONNECTED,         // 设备已连接
    BLE_CONFIG_CREDENTIALS,       // 凭据已接收
    BLE_CONFIG_CONNECTING_WIFI,   // 正在连接WiFi
    BLE_CONFIG_WIFI_CONNECTED,    // WiFi已连接
    BLE_CONFIG_WIFI_FAILED,       // WiFi连接失败
    BLE_CONFIG_DONE               // 配网完成
};

// 配网凭据
struct WifiCredentials {
    String ssid;
    String password;
    String resourceUrl;   // 资源服务器URL(可选)
};

class BleConfigManager {
public:
    BleConfigManager();
    
    /**
     * 初始化BLE配网
     * @param deviceName BLE广播名称
     * @return true=初始化成功
     */
    bool begin(const String& deviceName = "DeskPet-Setup");
    
    /**
     * 进入配网模式(启动BLE广播)
     * @param timeoutSec 广播超时(秒), 0=永不超时
     * @return true=已进入广播模式
     */
    bool startAdvertising(uint16_t timeoutSec = 300);
    
    /** 停止广播并释放BLE资源 */
    void stop();
    
    /** 更新(在loop中调用, 处理超时等) */
    void update();
    
    /** 是否正在配网 */
    bool isConfiguring() const { return _state == BLE_CONFIG_ADVERTISING || _state == BLE_CONFIG_CONNECTED; }
    
    /** 是否有新的WiFi凭据 */
    bool hasCredentials() const { return _hasNewCredentials; }
    
    /** 获取凭据(读取后清除标记) */
    WifiCredentials getCredentials();
    
    /** 设置配网状态(供外部回调) */
    void setState(BleConfigState state);
    
    /** 获取当前状态 */
    BleConfigState getState() const { return _state; }
    
    /** 获取状态字符串 */
    const char* getStateString() const;

private:
    NimBLEServer* _server;
    NimBLEService* _service;
    NimBLECharacteristic* _ssidChar;
    NimBLECharacteristic* _passChar;
    NimBLECharacteristic* _urlChar;
    NimBLECharacteristic* _statusChar;
    
    BleConfigState _state;
    WifiCredentials _credentials;
    bool _hasNewCredentials;
    bool _initialized;
    unsigned long _advStartTime;
    uint16_t _advTimeout;
    
    // BLE回调友元类
    friend class BleConfigServerCallbacks;
    friend class BleConfigSsidCallbacks;
    friend class BleConfigPassCallbacks;
    friend class BleConfigUrlCallbacks;
    
    void _notifyStatus(uint8_t status);
};

#endif // BLE_CONFIG_H
