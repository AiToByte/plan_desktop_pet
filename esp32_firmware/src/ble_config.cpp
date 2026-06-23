/*
 * BLE 零配网实现
 * 使用 NimBLE-Arduino 库 (比原生BLE更省资源)
 * 
 * 依赖: NimBLE-Arduino (platformio.ini中已配置)
 */

#include "ble_config.h"
#include <WiFi.h>
#include "log.h"

// BLE UUID定义
#define CONFIG_SERVICE_UUID      "1820"  // 自定义配网服务
#define CONFIG_SSID_CHAR_UUID    "2A69"  // SSID特征
#define CONFIG_PASS_CHAR_UUID    "2A6A"  // 密码特征
#define CONFIG_URL_CHAR_UUID     "2A6B"  // 资源URL特征
#define CONFIG_STATUS_CHAR_UUID  "2A6C"  // 状态特征

// ============ BLE 回调类 ============

class BleConfigServerCallbacks : public NimBLEServerCallbacks {
    BleConfigManager& _mgr;
public:
    BleConfigServerCallbacks(BleConfigManager& mgr) : _mgr(mgr) {}
    
    void onConnect(NimBLEServer* pServer) override {
        LOG_I("Client connected");
        _mgr.setState(BLE_CONFIG_CONNECTED);
    }
    
    void onDisconnect(NimBLEServer* pServer) override {
        LOG_I("Client disconnected");
        if (_mgr.isConfiguring()) {
            _mgr.startAdvertising(_mgr._advTimeout);
        }
    }
};

class BleConfigSsidCallbacks : public NimBLECharacteristicCallbacks {
    BleConfigManager& _mgr;
public:
    BleConfigSsidCallbacks(BleConfigManager& mgr) : _mgr(mgr) {}
    
    void onWrite(NimBLECharacteristic* pChar) override {
        _mgr._credentials.ssid = pChar->getValue().c_str();
        LOG_I("SSID received: %s\n", _mgr._credentials.ssid.c_str());
    }
};

class BleConfigPassCallbacks : public NimBLECharacteristicCallbacks {
    BleConfigManager& _mgr;
public:
    BleConfigPassCallbacks(BleConfigManager& mgr) : _mgr(mgr) {}
    
    void onWrite(NimBLECharacteristic* pChar) override {
        _mgr._credentials.password = pChar->getValue().c_str();
        LOG_I("Password received (%d chars)\n", _mgr._credentials.password.length());
        
        // 收到密码后标记凭据就绪
        if (_mgr._credentials.ssid.length() > 0) {
            _mgr._hasNewCredentials = true;
            _mgr.setState(BLE_CONFIG_CREDENTIALS);
            LOG_I("Credentials complete!");
        }
    }
};

class BleConfigUrlCallbacks : public NimBLECharacteristicCallbacks {
    BleConfigManager& _mgr;
public:
    BleConfigUrlCallbacks(BleConfigManager& mgr) : _mgr(mgr) {}
    
    void onWrite(NimBLECharacteristic* pChar) override {
        _mgr._credentials.resourceUrl = pChar->getValue().c_str();
        LOG_I("Resource URL: %s\n", _mgr._credentials.resourceUrl.c_str());
    }
};

// ============ BleConfigManager 实现 ============

BleConfigManager::BleConfigManager()
    : _server(nullptr), _service(nullptr)
    , _ssidChar(nullptr), _passChar(nullptr), _urlChar(nullptr), _statusChar(nullptr)
    , _state(BLE_CONFIG_IDLE), _hasNewCredentials(false)
    , _initialized(false), _advStartTime(0), _advTimeout(300) {}

bool BleConfigManager::begin(const String& deviceName) {
    if (_initialized) return true;
    
    LOG_I("Initializing: %s\n", deviceName.c_str());
    
    NimBLEDevice::init(deviceName.c_str());
    NimBLEDevice::setPower(ESP_PWR_LVL_P6);  // 增强发射功率
    
    _server = NimBLEDevice::createServer();
    _server->setCallbacks(new BleConfigServerCallbacks(*this));
    
    // 创建配网服务
    _service = _server->createService(CONFIG_SERVICE_UUID);
    
    // SSID特征 (读/写, 最大32字节)
    _ssidChar = _service->createCharacteristic(
        CONFIG_SSID_CHAR_UUID,
        NIMBLE_PROPERTY::READ | NIMBLE_PROPERTY::WRITE
    );
    _ssidChar->setCallbacks(new BleConfigSsidCallbacks(*this));
    _ssidChar->setValue("not_set");
    
    // 密码特征 (写, 最大64字节)
    _passChar = _service->createCharacteristic(
        CONFIG_PASS_CHAR_UUID,
        NIMBLE_PROPERTY::WRITE
    );
    _passChar->setCallbacks(new BleConfigPassCallbacks(*this));
    
    // 资源URL特征 (读/写, 最大128字节)
    _urlChar = _service->createCharacteristic(
        CONFIG_URL_CHAR_UUID,
        NIMBLE_PROPERTY::READ | NIMBLE_PROPERTY::WRITE
    );
    _urlChar->setCallbacks(new BleConfigUrlCallbacks(*this));
    _urlChar->setValue("");
    
    // 状态特征 (读/通知)
    _statusChar = _service->createCharacteristic(
        CONFIG_STATUS_CHAR_UUID,
        NIMBLE_PROPERTY::READ | NIMBLE_PROPERTY::NOTIFY
    );
    _notifyStatus(BLE_CONFIG_IDLE);
    
    _service->start();
    
    // 配置广播数据
    NimBLEAdvertising* adv = NimBLEDevice::getAdvertising();
    adv->addServiceUUID(CONFIG_SERVICE_UUID);
    adv->setScanResponse(true);
    adv->setMinPreferred(0x06);
    adv->setMinPreferred(0x12);
    
    _initialized = true;
    LOG_I("Init OK");
    return true;
}

bool BleConfigManager::startAdvertising(uint16_t timeoutSec) {
    if (!_initialized) return false;
    
    _advTimeout = timeoutSec;
    _advStartTime = millis();
    _state = BLE_CONFIG_ADVERTISING;
    
    NimBLEDevice::startAdvertising();
    LOG_W("Advertising started (timeout=%ds)\n", timeoutSec);
    
    _notifyStatus(BLE_CONFIG_ADVERTISING);
    return true;
}

void BleConfigManager::stop() {
    if (!_initialized) return;
    
    NimBLEDevice::stopAdvertising();
    _state = BLE_CONFIG_IDLE;
    _notifyStatus(BLE_CONFIG_IDLE);
    LOG_I("Advertising stopped");
}

void BleConfigManager::update() {
    if (_state != BLE_CONFIG_ADVERTISING) return;
    
    // 广播超时检查
    if (_advTimeout > 0) {
        unsigned long elapsed = (millis() - _advStartTime) / 1000;
        if (elapsed >= _advTimeout) {
            LOG_W("Advertising timeout");
            stop();
        }
    }
}

WifiCredentials BleConfigManager::getCredentials() {
    _hasNewCredentials = false;
    return _credentials;
}

void BleConfigManager::setState(BleConfigState state) {
    _state = state;
    _notifyStatus(state);
}

void BleConfigManager::_notifyStatus(uint8_t status) {
    if (_statusChar) {
        _statusChar->setValue(&status, 1);
        _statusChar->notify();
    }
}

const char* BleConfigManager::getStateString() const {
    switch (_state) {
        case BLE_CONFIG_IDLE:            return "idle";
        case BLE_CONFIG_ADVERTISING:     return "advertising";
        case BLE_CONFIG_CONNECTED:       return "connected";
        case BLE_CONFIG_CREDENTIALS:     return "credentials";
        case BLE_CONFIG_CONNECTING_WIFI: return "connecting_wifi";
        case BLE_CONFIG_WIFI_CONNECTED:  return "wifi_connected";
        case BLE_CONFIG_WIFI_FAILED:     return "wifi_failed";
        case BLE_CONFIG_DONE:            return "done";
        default: return "unknown";
    }
}
