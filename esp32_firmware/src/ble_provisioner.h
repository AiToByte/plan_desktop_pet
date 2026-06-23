/*
 * BLE辅助配网模块 - NimBLE实现
 * 设备名: "DeskPet-Setup"
 * 
 * 配网流程:
 *   1. WiFi连接失败时自动启动BLE广播
 *   2. 手机BLE客户端连接并写入WiFi凭证
 *   3. 设备尝试连接WiFi，成功后BLE.stop()释放内存
 *   4. 凭证保存到Preferences持久化
 * 
 * Service UUID: 0x1820 (自定义)
 * Characteristics:
 *   - SSID:     0x2AA1 (Read/Write)
 *   - Password: 0x2AA2 (Write)
 *   - Host:     0x2AA3 (Read/Write)  -- 可选，服务器IP
 *   - Port:     0x2AA4 (Read/Write)  -- 可选，服务器端口
 */

#ifndef BLE_PROVISIONER_H
#define BLE_PROVISIONER_H

#ifdef BLE_PROVISIONING_ENABLED  // 条件编译：未定义时整个模块不参与编译

#include <Arduino.h>
#include <NimBLEDevice.h>
#include <Preferences.h>

class BLEProvisioner {
public:
    BLEProvisioner();
    ~BLEProvisioner();

    // 启动BLE配网广播(阻塞直到配网成功或超时)
    // timeoutMs: 超时时间(毫秒)，0=不超时
    // 返回: true=配网成功, false=超时或失败
    bool startProvisioning(uint32_t timeoutMs = 0);

    // 停止BLE并释放内存
    void stop();

    // 是否正在配网
    bool isActive() const { return _active; }

    // 获取配网结果
    String getSSID() const { return _ssid; }
    String getPassword() const { return _password; }
    String getHost() const { return _host; }
    uint16_t getPort() const { return _port; }

private:
    NimBLEServer* _server;
    NimBLEService* _service;
    NimBLEAdvertising* _advertising;
    
    // 配网数据
    String _ssid;
    String _password;
    String _host;
    uint16_t _port;
    
    bool _active;
    bool _provisioned;
    uint32_t _startTime;
    uint32_t _timeoutMs;

    // 回调类声明
    class ServerCallbacks;
    class SSIDCallback;
    class PasswordCallback;
    class HostCallback;
    class PortCallback;

    // 内部辅助方法
    bool initBLEService();
    bool waitForProvisioning();
};

#endif // BLE_PROVISIONING_ENABLED
#endif // BLE_PROVISIONER_H
