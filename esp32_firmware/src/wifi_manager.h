#ifndef WIFI_MANAGER_H
#define WIFI_MANAGER_H

#include <WiFi.h>
#include <WiFiUdp.h>
#include "config.h"
#include "web_config.h"

class WiFiManager {
public:
    WiFiManager();
    void begin();
    
    // 尝试连接WiFi（优先用保存的配置）
    bool connect();
    
    // UDP自动发现PC服务器
    bool tryUDPDiscovery(unsigned long timeoutMs = 15000);
    
    // 启动配网模式
    void startConfigMode();
    
    // 处理配网请求
    void handleConfig();
    
    // 检查是否正在配网
    bool isConfiguring();
    
    bool isConnected();
    String getIP();
    String getServerHost();
    int getServerPort();
    void disconnect();
    
private:
    WebConfig _webConfig;
    bool _connected;
    unsigned long _lastAttempt;
    bool _configMode;
    
    void _startMDNS();
    bool _tryMDNSDiscovery();
};

#endif
