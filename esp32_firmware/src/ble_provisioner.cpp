/*
 * BLE辅助配网模块 - NimBLE实现
 * 
 * 配网流程:
 *   1. WiFi连接失败时调用startProvisioning()
 *   2. 手机BLE客户端(如nRF Connect)连接，写入SSID/Password
 *   3. 收到完整凭证后尝试连接WiFi
 *   4. 成功→保存Preferences+BLE.stop()释放内存
 * 
 * 内存优化: NimBLE比原生BLE栈节省约100KB RAM
 */

#include "ble_provisioner.h"
#include "log.h"

#ifdef BLE_PROVISIONING_ENABLED  // 条件编译：未定义时整个模块不参与编译

// Service UUID: 0x1820 (自定义)
static NimBLEUUID SERVICE_UUID("1820");
// Characteristic UUIDs
static NimBLEUUID SSID_UUID("2AA1");
static NimBLEUUID PASS_UUID("2AA2");
static NimBLEUUID HOST_UUID("2AA3");
static NimBLEUUID PORT_UUID("2AA4");

static const char* PREF_NAMESPACE = "ble_config";
static const char* BLE_DEVICE_NAME = "DeskPet-Setup";

// ============ 回调类 ============

class BLEProvisioner::ServerCallbacks : public NimBLEServerCallbacks {
public:
    ServerCallbacks(BLEProvisioner* parent) : _parent(parent) {}
    
    void onConnect(NimBLEServer* pServer) override {
        LOG_I("Client connected");
        // 连接后停止广播节省电量
        pServer->stopAdvertising();
    }
    
    void onDisconnect(NimBLEServer* pServer) override {
        LOG_I("Client disconnected, restarting advertising");
        // 断开后重新广播，等待重连
        if (_parent->_active && !_parent->_provisioned) {
            pServer->startAdvertising();
        }
    }
    
private:
    BLEProvisioner* _parent;
};

class BLEProvisioner::SSIDCallback : public NimBLECharacteristicCallbacks {
public:
    SSIDCallback(BLEProvisioner* parent) : _parent(parent) {}
    
    void onWrite(NimBLECharacteristic* pChar) override {
        _parent->_ssid = pChar->getValue().c_str();
        LOG_I("SSID received: %s\n", _parent->_ssid.c_str());
    }
    
private:
    BLEProvisioner* _parent;
};

class BLEProvisioner::PasswordCallback : public NimBLECharacteristicCallbacks {
public:
    PasswordCallback(BLEProvisioner* parent) : _parent(parent) {}
    
    void onWrite(NimBLECharacteristic* pChar) override {
        _parent->_password = pChar->getValue().c_str();
        LOG_I("Password received");
        // 收到密码后标记配网完成(SSID必须已设置)
        if (_parent->_ssid.length() > 0) {
            _parent->_provisioned = true;
            LOG_I("Provisioning complete, will attempt WiFi connect");
        }
    }
    
private:
    BLEProvisioner* _parent;
};

class BLEProvisioner::HostCallback : public NimBLECharacteristicCallbacks {
public:
    HostCallback(BLEProvisioner* parent) : _parent(parent) {}
    
    void onWrite(NimBLECharacteristic* pChar) override {
        _parent->_host = pChar->getValue().c_str();
        LOG_I("Host received: %s\n", _parent->_host.c_str());
    }
    
private:
    BLEProvisioner* _parent;
};

class BLEProvisioner::PortCallback : public NimBLECharacteristicCallbacks {
public:
    PortCallback(BLEProvisioner* parent) : _parent(parent) {}
    
    void onWrite(NimBLECharacteristic* pChar) override {
        std::string val = pChar->getValue();
        _parent->_port = atoi(val.c_str());
        LOG_I("Port received: %d\n", _parent->_port);
    }
    
private:
    BLEProvisioner* _parent;
};

// ============ BLEProvisioner实现 ============

BLEProvisioner::BLEProvisioner() 
    : _server(nullptr), _service(nullptr), _advertising(nullptr)
    , _port(8080), _active(false), _provisioned(false)
    , _startTime(0), _timeoutMs(0) {
}

BLEProvisioner::~BLEProvisioner() {
    stop();
}

bool BLEProvisioner::startProvisioning(uint32_t timeoutMs) {
    if (_active) {
        LOG_I("Already active");
        return false;
    }
    
    _timeoutMs = timeoutMs;
    _provisioned = false;
    _ssid = "";
    _password = "";
    _host = "";
    _port = 8080;
    
    LOG_I("Starting provisioning...");
    
    // 初始化BLE协议栈并启动广播
    if (!initBLEService()) {
        LOG_E("Failed to init BLE service");
        stop();
        return false;
    }
    
    _active = true;
    _startTime = millis();
    
    LOG_W("Advertising as '%s', timeout: %s\n", BLE_DEVICE_NAME, timeoutMs > 0 ? String(timeoutMs / 1000) + "s" : "none");
    
    // 阻塞等待配网完成或超时
    if (!waitForProvisioning()) {
        return false;
    }
    
    // 配网成功：保存凭证到Preferences
    Preferences prefs;
    prefs.begin(PREF_NAMESPACE, false);
    prefs.putString("ssid", _ssid);
    prefs.putString("password", _password);
    if (_host.length() > 0) prefs.putString("host", _host);
    if (_port > 0) prefs.putUShort("port", _port);
    prefs.end();
    
    LOG_I("Credentials saved to Preferences");
    stop();
    return true;
}

// 初始化BLE协议栈：创建Server/Service/Characteristics并启动广播
bool BLEProvisioner::initBLEService() {
    NimBLEDevice::init(BLE_DEVICE_NAME);
    NimBLEDevice::setPower(ESP_PWR_LVL_P3);  // ~0dBm，配网距离不需要远
    
    _server = NimBLEDevice::createServer();
    _server->setCallbacks(new ServerCallbacks(this));
    
    _service = _server->createService(SERVICE_UUID);
    
    // SSID: Read + Write
    NimBLECharacteristic* ssidChar = _service->createCharacteristic(
        SSID_UUID, NIMBLE_PROPERTY::READ | NIMBLE_PROPERTY::WRITE);
    ssidChar->setCallbacks(new SSIDCallback(this));
    ssidChar->setValue("");
    
    // Password: Write only (不暴露读取)
    NimBLECharacteristic* passChar = _service->createCharacteristic(
        PASS_UUID, NIMBLE_PROPERTY::WRITE);
    passChar->setCallbacks(new PasswordCallback(this));
    
    // Host: Read + Write (可选)
    NimBLECharacteristic* hostChar = _service->createCharacteristic(
        HOST_UUID, NIMBLE_PROPERTY::READ | NIMBLE_PROPERTY::WRITE);
    hostChar->setCallbacks(new HostCallback(this));
    hostChar->setValue("deskpet.local");
    
    // Port: Read + Write (可选)
    NimBLECharacteristic* portChar = _service->createCharacteristic(
        PORT_UUID, NIMBLE_PROPERTY::READ | NIMBLE_PROPERTY::WRITE);
    portChar->setCallbacks(new PortCallback(this));
    portChar->setValue("8080");
    
    _service->start();
    
    _advertising = NimBLEDevice::getAdvertising();
    _advertising->addServiceUUID(SERVICE_UUID);
    _advertising->setScanResponse(true);
    _advertising->setMinPreferred(0x06);  // 有助于iPhone连接
    _advertising->start();
    
    return true;
}

// 阻塞等待配网完成或超时
bool BLEProvisioner::waitForProvisioning() {
    while (_active && !_provisioned) {
        delay(100);
        
        if (_timeoutMs > 0 && (millis() - _startTime) > _timeoutMs) {
            LOG_W("Provisioning timeout");
            stop();
            return false;
        }
        
        yield();  // 避免看门狗超时
    }
    return _provisioned;
}

void BLEProvisioner::stop() {
    if (!_active) return;
    
    _active = false;
    _advertising = nullptr;
    _service = nullptr;
    _server = nullptr;
    
    NimBLEDevice::deinit(true);  // true = release memory
    LOG_I("Stopped, memory released");
}

#endif // BLE_PROVISIONING_ENABLED
