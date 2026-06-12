#ifndef COMM_MANAGER_H
#define COMM_MANAGER_H

#include <WiFiClient.h>
#include <ArduinoJson.h>
#include "config.h"

// 帧协议状态机
enum FrameState {
    FRAME_IDLE,         // 等待新帧（检测 LEN: 或 { 开头）
    FRAME_READ_LEN,     // 读取长度前缀 "LEN:NNNN\n"
    FRAME_READ_BODY,    // 按长度读取payload
    FRAME_LEGACY_LINE   // 兼容旧格式：\n 分隔
};

class CommManager {
public:
    CommManager();
    void begin();
    void setServer(String host, int port);
    void update();
    bool connect();
    void disconnect();
    void reconnect();
    bool isConnected();
    bool hasNewData();
    String getData();
    void sendHeartbeat();
    void sendMessage(String type, JsonObject data);
    unsigned long getLastReceiveTime() const { return _lastReceiveTime; }
    
private:
    WiFiClient _client;
    bool _connected;
    String _lastData;
    bool _hasNewData;
    unsigned long _lastReconnect;
    unsigned long _lastReceiveTime;  // 最后收到数据的时间戳
    String _serverHost;
    int _serverPort;
    
    // 帧协议状态机
    FrameState _frameState;
    String _lenBuffer;       // 累积 LEN: 前缀
    String _frameBuffer;     // 累积完整帧payload
    int _expectedLen;        // 期望的payload长度
    
    void processData(String data);
    void sendFramed(const String& json);  // 发送带长度前缀的帧
};

#endif
