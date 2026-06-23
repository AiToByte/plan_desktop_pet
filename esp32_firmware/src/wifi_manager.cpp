#include "wifi_manager.h"
#include <ESPmDNS.h>
#include "log.h"
#ifdef BLE_PROVISIONING_ENABLED
#include "ble_provisioner.h"
#endif

WiFiManager::WiFiManager() : _connected(false), _lastAttempt(0), _configMode(false) {}

void WiFiManager::begin() {
    WiFi.mode(WIFI_STA);
    WiFi.setAutoReconnect(true);
    
    // 初始化Web配网模块
    _webConfig.begin();
}

bool WiFiManager::tryUDPDiscovery(unsigned long timeoutMs) {
    WiFiUDP udp;
    // 使用与PC端相同的广播端口
    if (!udp.begin(19877)) {
        LOG_I("UDP Discovery: 监听端口失败");
        return false;
    }
    
    LOG_I("UDP Discovery: 监听端口 19877，超时 %lu ms\n", timeoutMs);
    
    unsigned long start = millis();
    char buf[128];
    
    while (millis() - start < timeoutMs) {
        int packetSize = udp.parsePacket();
        if (packetSize > 0 && packetSize < (int)sizeof(buf)) {
            int len = udp.read(buf, sizeof(buf) - 1);
            buf[len] = '\0';
            
            // 格式: DESKTOP_PET_SERVER:IP:PORT
            String msg = String(buf);
            if (msg.startsWith("DESKTOP_PET_SERVER:")) {
                String payload = msg.substring(19); // 跳过前缀
                int colonIdx = payload.indexOf(':');
                if (colonIdx > 0) {
                    String ip = payload.substring(0, colonIdx);
                    int port = payload.substring(colonIdx + 1).toInt();
                    
                    if (ip.length() > 0 && port > 0) {
                        LOG_I("UDP Discovery: 发现服务器 %s:%d\n", ip.c_str(), port);
                        
                        // 保存到Flash（与WebConfig统一命名空间和Key）
                        Preferences prefs;
                        prefs.begin("pet_config", false);
                        prefs.putString("host", ip);
                        prefs.putInt("port", port);
                        prefs.putBool("valid", true);
                        prefs.end();
                        
                        udp.stop();
                        return true;
                    }
                }
            }
        }
        delay(10);
    }
    
    udp.stop();
    LOG_I("UDP Discovery: 超时，未发现服务器");
    return false;
}

bool WiFiManager::connect() {
    // 优先使用保存的配置连接
    if (_webConfig.connectFromSaved()) {
        _connected = true;
        _configMode = false;
        _startMDNS();
        return true;
    }
    
    // 保存的配置失败，先尝试mDNS发现PC服务器（最快）
    LOG_E("Saved config failed, trying mDNS discovery...");
    if (_tryMDNSDiscovery()) {
        LOG_W("mDNS discovery OK, retrying connection...");
        if (_webConfig.connectFromSaved()) {
            _connected = true;
            _configMode = false;
            _startMDNS();
            return true;
        }
    }
    
    // mDNS失败，尝试UDP自动发现PC服务器
    LOG_E("mDNS failed, trying UDP discovery...");
    if (tryUDPDiscovery()) {
        LOG_W("UDP discovery OK, retrying connection...");
        if (_webConfig.connectFromSaved()) {
            _connected = true;
            _configMode = false;
            _startMDNS();
            return true;
        }
    }
    
    // 自动发现也失败，尝试BLE配网（120s超时），超时后降级AP
#ifdef BLE_PROVISIONING_ENABLED
    LOG_W("Trying BLE provisioning (120s timeout)...");
    BLEProvisioner ble;
    if (ble.startProvisioning(120000)) {
        // BLE配网成功，重新尝试WiFi连接
        LOG_W("BLE provisioned, retrying WiFi...");
        if (_webConfig.connectFromSaved()) {
            _connected = true;
            _configMode = false;
            _startMDNS();
            return true;
        }
        LOG_E("BLE provisioned but WiFi still failed");
    }
    // BLE超时或WiFi仍失败，降级到AP配网模式
    LOG_E("BLE timeout/failed, falling back to AP mode...");
#endif
    
    startConfigMode();
    return false;
}

void WiFiManager::startConfigMode() {
    _configMode = true;
    _webConfig.startAPMode();
    
    LOG_I("=========================================");
    LOG_I("Web配网模式已启动");
    LOG_I("请连接热点: %s", String(AP_SSID).c_str());
    LOG_I("密码: %s", String(AP_PASSWORD).c_str());
    LOG_I("然后访问: http://%s", _webConfig.getAPIP().c_str());
    LOG_I("=========================================");
}

void WiFiManager::handleConfig() {
    if (_configMode) {
        _webConfig.handleClient();
    }
}

bool WiFiManager::isConfiguring() {
    return _configMode;
}

bool WiFiManager::isConnected() {
    if (_configMode) return false;
    _connected = (WiFi.status() == WL_CONNECTED);
    return _connected;
}

String WiFiManager::getIP() {
    if (_connected) {
        return WiFi.localIP().toString();
    }
    return "0.0.0.0";
}

String WiFiManager::getServerHost() {
    StoredConfig cfg = _webConfig.getConfig();
    if (cfg.valid) {
        return cfg.server_host;
    }
    return "";
}

int WiFiManager::getServerPort() {
    StoredConfig cfg = _webConfig.getConfig();
    if (cfg.valid) {
        return cfg.server_port;
    }
    return SERVER_PORT;
}

void WiFiManager::disconnect() {
    WiFi.disconnect();
    _connected = false;
}

bool WiFiManager::_tryMDNSDiscovery() {
    LOG_I("mDNS: querying _deskpet._tcp.local. ...");
    
    int n = MDNS.queryService("deskpet", "tcp");
    if (n == 0) {
        LOG_I("mDNS: no service found");
        return false;
    }
    
    // 取第一个结果
    String ip = MDNS.IP(0).toString();
    int port = MDNS.port(0);
    
    if (ip.length() == 0 || port <= 0) {
        LOG_E("mDNS: invalid result");
        return false;
    }
    
    LOG_I("mDNS: found %s:%d\n", ip.c_str(), port);
    
    // 保存到Flash（与WebConfig统一命名空间和Key）
    Preferences prefs;
    prefs.begin("pet_config", false);
    prefs.putString("host", ip);
    prefs.putInt("port", port);
    prefs.putBool("valid", true);
    prefs.end();
    
    return true;
}

void WiFiManager::_startMDNS() {
    if (MDNS.begin("deskpet")) {
        MDNS.addService("deskpet", "tcp", _webConfig.getConfig().server_port);
        LOG_I("mDNS started: deskpet.local");
    } else {
        LOG_E("mDNS start failed");
    }
}
