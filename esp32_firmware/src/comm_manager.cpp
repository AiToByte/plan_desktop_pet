#include "comm_manager.h"

CommManager::CommManager() 
    : _connected(false), _hasNewData(false), _lastReconnect(0)
    , _lastReceiveTime(0), _frameState(FRAME_IDLE)
    , _expectedLen(0) {
    _serverHost = "";
    _serverPort = SERVER_PORT;
}

void CommManager::begin() {
    _lastData = "";
    _lenBuffer = "";
    _frameBuffer = "";
    _frameState = FRAME_IDLE;
    _expectedLen = 0;
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
        _frameState = FRAME_IDLE;
        
        // 发送握手消息（使用帧协议）
        StaticJsonDocument<128> doc;
        doc["type"] = "handshake";
        doc["device"] = "esp32s3";
        doc["version"] = "2.0.0";  // v2: 长度前缀帧协议
        
        String json;
        serializeJson(doc, json);
        sendFramed(json);
        
        return true;
    }
    
    Serial.println("[Comm] Connection failed!");
    _connected = false;
    return false;
}

void CommManager::disconnect() {
    _client.stop();
    _connected = false;
    _frameState = FRAME_IDLE;
    _lenBuffer = "";
    _frameBuffer = "";
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
        
        switch (_frameState) {
            case FRAME_IDLE:
                // 检测帧类型：'L' = 长度前缀, '{' = 旧格式JSON
                if (c == 'L') {
                    _lenBuffer = "L";
                    _frameState = FRAME_READ_LEN;
                } else if (c == '{') {
                    // 旧格式fallback：整行是一个JSON
                    _frameBuffer = "{";
                    _frameState = FRAME_LEGACY_LINE;
                }
                // 其他字符（空白等）跳过
                break;
                
            case FRAME_READ_LEN:
                // 累积到换行符：期望格式 "EN:NNNN\n"
                if (c == '\n') {
                    // 解析 "LEN:NNNN" → "L" + "EN:NNNN"
                    // _lenBuffer = "LEN:NNNN"
                    if (_lenBuffer.startsWith("LEN:")) {
                        _expectedLen = atoi(_lenBuffer.substring(4).c_str());
                        if (_expectedLen > 0 && _expectedLen < 256 * 1024) {
                            _frameBuffer = "";
                            _frameBuffer.reserve(_expectedLen);
                            _frameState = FRAME_READ_BODY;
                            Serial.printf("[Comm] Frame len=%d\n", _expectedLen);
                        } else {
                            Serial.printf("[Comm] Invalid len: %s\n", _lenBuffer.c_str());
                            _frameState = FRAME_IDLE;
                        }
                    } else {
                        Serial.printf("[Comm] Bad header: %s\n", _lenBuffer.c_str());
                        _frameState = FRAME_IDLE;
                    }
                    _lenBuffer = "";
                } else {
                    _lenBuffer += c;
                    // 防止超长header攻击
                    if (_lenBuffer.length() > 16) {
                        Serial.println("[Comm] Header overflow, reset");
                        _lenBuffer = "";
                        _frameState = FRAME_IDLE;
                    }
                }
                break;
                
            case FRAME_READ_BODY:
                _frameBuffer += c;
                if ((int)_frameBuffer.length() >= _expectedLen) {
                    // 完整帧到达
                    processData(_frameBuffer);
                    _frameBuffer = "";
                    _expectedLen = 0;
                    _frameState = FRAME_IDLE;
                }
                break;
                
            case FRAME_LEGACY_LINE:
                if (c == '\n') {
                    processData(_frameBuffer);
                    _frameBuffer = "";
                    _frameState = FRAME_IDLE;
                } else {
                    _frameBuffer += c;
                    // 防止单帧过大（旧格式无长度保护）
                    if (_frameBuffer.length() > 32 * 1024) {
                        Serial.println("[Comm] Legacy frame overflow, reset");
                        _frameBuffer = "";
                        _frameState = FRAME_IDLE;
                    }
                }
                break;
        }
    }
    
    // 检查连接状态
    if (!_client.connected()) {
        Serial.println("[Comm] Connection lost!");
        _connected = false;
    }
}

void CommManager::processData(const String& data) {
    data.trim();
    if (data.length() == 0) return;
    
    _lastData = data;
    _hasNewData = true;
    _lastReceiveTime = millis();
    
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

void CommManager::sendFramed(const String& json) {
    // 帧格式: "LEN:<length>\n<payload>"
    String header = "LEN:" + String(json.length()) + "\n";
    _client.print(header);
    _client.print(json);
}

void CommManager::sendHeartbeat() {
    DynamicJsonDocument doc(128);
    doc["type"] = "heartbeat";
    doc["ts"] = millis();
    
    String json;
    serializeJson(doc, json);
    sendFramed(json);
}

void CommManager::sendMessage(String type, JsonObject data) {
    DynamicJsonDocument doc(512);
    doc["type"] = type;
    doc["data"] = data;
    doc["ts"] = millis();
    
    String json;
    serializeJson(doc, json);
    sendFramed(json);
}
