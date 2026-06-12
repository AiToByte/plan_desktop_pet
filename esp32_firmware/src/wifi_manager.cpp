#include "wifi_manager.h"

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
        Serial.println("[WiFi] UDP Discovery: 监听端口失败");
        return false;
    }
    
    Serial.printf("[WiFi] UDP Discovery: 监听端口 19877，超时 %lu ms\n", timeoutMs);
    
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
                        Serial.printf("[WiFi] UDP Discovery: 发现服务器 %s:%d\n", ip.c_str(), port);
                        
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
    Serial.println("[WiFi] UDP Discovery: 超时，未发现服务器");
    return false;
}

bool WiFiManager::connect() {
    // 优先使用保存的配置连接
    if (_webConfig.connectFromSaved()) {
        _connected = true;
        _configMode = false;
        return true;
    }
    
    // 保存的配置失败，尝试UDP自动发现PC服务器
    Serial.println("[WiFi] Saved config failed, trying UDP discovery...");
    if (tryUDPDiscovery()) {
        Serial.println("[WiFi] UDP discovery OK, retrying connection...");
        if (_webConfig.connectFromSaved()) {
            _connected = true;
            _configMode = false;
            return true;
        }
    }
    
    // 自动发现也失败，进入配网模式
    Serial.println("[WiFi] UDP discovery failed, starting config mode...");
    startConfigMode();
    return false;
}

void WiFiManager::startConfigMode() {
    _configMode = true;
    _webConfig.startAPMode();
    
    Serial.println("=========================================");
    Serial.println("[WiFi] Web配网模式已启动");
    Serial.print("[WiFi] 请连接热点: ");
    Serial.println(AP_SSID);
    Serial.print("[WiFi] 密码: ");
    Serial.println(AP_PASSWORD);
    Serial.print("[WiFi] 然后访问: http://");
    Serial.println(_webConfig.getAPIP());
    Serial.println("=========================================");
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
