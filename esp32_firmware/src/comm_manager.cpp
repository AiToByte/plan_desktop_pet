#include "comm_manager.h"

CommManager::CommManager() : _connected(false), _hasNewData(false), _lastReconnect(0) {
    _serverHost = "";
    _serverPort = SERVER_PORT;
}

void CommManager::begin() {
    _buffer = "";
    _lastData = "";
}

void CommManager::setServer(String host, int port) {
    _serverHost = host;
    _serverPort = port;
    Serial.print("[Comm] Server set to: ");
    Serial.print(host);
    Serial.print(":");
    Serial.println(port);
}

bool CommManager::connect() {
    if (_serverHost.length() == 0) {
        Serial.println("[Comm] No server configured!");
        return false;
    }
    
    Serial.print("[Comm] Connecting to ");
    Serial.print(_serverHost);
    Serial.print(":");
    Serial.println(_serverPort);
    
    if (_client.connect(_serverHost.c_str(), _serverPort)) {
        Serial.println("[Comm] Connected!");
        _connected = true;
        
        // 发送握手消息
        DynamicJsonDocument doc(256);
        doc["type"] = "handshake";
        doc["device"] = "esp32s3";
        doc["version"] = "1.0.0";
        
        String json;
        serializeJson(doc, json);
        _client.println(json);
        
        return true;
    }
    
    Serial.println("[Comm] Connection failed!");
    _connected = false;
    return false;
}

void CommManager::disconnect() {
    _client.stop();
    _connected = false;
}

void CommManager::reconnect() {
    unsigned long now = millis();
    if (now - _lastReconnect < RECONNECT_INTERVAL) {
        return;
    }
    _lastReconnect = now;
    
    Serial.println("[Comm] Reconnecting...");
    disconnect();
    connect();
}

void CommManager::update() {
    if (!_connected) return;
    
    while (_client.available()) {
        char c = _client.read();
        if (c == '\n') {
            processData(_buffer);
            _buffer = "";
        } else {
            _buffer += c;
        }
    }
    
    // 检查连接状态
    if (!_client.connected()) {
        Serial.println("[Comm] Connection lost!");
        _connected = false;
    }
}

void CommManager::processData(String data) {
    data.trim();
    if (data.length() == 0) return;
    
    _lastData = data;
    _hasNewData = true;
    
    Serial.print("[Comm] Received: ");
    Serial.println(data.substring(0, 50) + "...");
}

bool CommManager::isConnected() {
    return _connected && _client.connected();
}

bool CommManager::hasNewData() {
    bool result = _hasNewData;
    _hasNewData = false;
    return result;
}

String CommManager::getData() {
    return _lastData;
}

void CommManager::sendHeartbeat() {
    DynamicJsonDocument doc(128);
    doc["type"] = "heartbeat";
    doc["ts"] = millis();
    
    String json;
    serializeJson(doc, json);
    _client.println(json);
}

void CommManager::sendMessage(String type, JsonObject data) {
    DynamicJsonDocument doc(512);
    doc["type"] = type;
    doc["data"] = data;
    doc["ts"] = millis();
    
    String json;
    serializeJson(doc, json);
    _client.println(json);
}
