#include "wifi_manager.h"

WiFiManager::WiFiManager() : _connected(false), _lastAttempt(0), _configMode(false) {}

void WiFiManager::begin() {
    WiFi.mode(WIFI_STA);
    WiFi.setAutoReconnect(true);
    
    // 初始化Web配网模块
    _webConfig.begin();
}

bool WiFiManager::connect() {
    // 优先使用保存的配置连接
    if (_webConfig.connectFromSaved()) {
        _connected = true;
        _configMode = false;
        return true;
    }
    
    // 保存的配置失败，进入配网模式
    Serial.println("[WiFi] Saved config failed, starting config mode...");
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
