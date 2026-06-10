#ifndef COMM_MANAGER_H
#define COMM_MANAGER_H

#include <WiFiClient.h>
#include <ArduinoJson.h>
#include "config.h"

class CommManager {
public:
    CommManager();
    void begin();
    void setServer(String host, int port);  // 动态设置服务器地址
    void update();
    bool connect();
    void disconnect();
    void reconnect();
    bool isConnected();
    bool hasNewData();
    String getData();
    void sendHeartbeat();
    void sendMessage(String type, JsonObject data);
    
private:
    WiFiClient _client;
    bool _connected;
    String _buffer;
    String _lastData;
    bool _hasNewData;
    unsigned long _lastReconnect;
    String _serverHost;  // 动态服务器地址
    int _serverPort;     // 动态服务器端口
    
    void processData(String data);
};

#endif
