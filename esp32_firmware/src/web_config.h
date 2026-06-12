#ifndef WEB_CONFIG_H
#define WEB_CONFIG_H

#include <WiFi.h>
#include <WebServer.h>
#include <Preferences.h>
#include <Update.h>
#include <esp_ota_ops.h>
#include "config.h"

// 配网状态
enum ConfigState {
    CONFIG_IDLE,
    CONFIG_AP_MODE,
    CONFIG_CONNECTED,
    CONFIG_FAILED
};

// 存储的配置数据
struct StoredConfig {
    String wifi_ssid;
    String wifi_password;
    String server_host;
    int server_port;
    bool valid;
};

class WebConfig {
public:
    WebConfig();
    
    // 初始化，检查Flash中是否有保存的配置
    bool begin();
    
    // 尝试用保存的配置连接WiFi
    bool connectFromSaved();
    
    // 启动AP配网模式
    void startAPMode();
    
    // 处理Web请求（需在loop中调用）
    void handleClient();
    
    // 检查是否正在配网
    bool isConfiguring();
    
    // 检查是否已连接
    bool isConnected();
    
    // 获取配置
    StoredConfig getConfig();
    
    // 重置配置（清除Flash）
    void resetConfig();
    
    // 获取AP IP
    String getAPIP();

private:
    WebServer* _server;
    Preferences _prefs;
    StoredConfig _config;
    ConfigState _state;
    unsigned long _configStartTime;
    
    // Web页面处理
    void handleRoot();
    void handleSave();
    void handleReset();
    void handleStatus();
    
    // OTA固件升级（支持回滚）
    void handleOTA();
    void handleOTAUpload();
    void handleOTARollback();
    const esp_partition_t* _otaPrevPartition = nullptr;
    
    // 生成配网页面HTML
    String getConfigPageHTML();
    String getSuccessPageHTML();
    String getErrorPageHTML(String msg);
    
    // 保存配置到Flash
    void saveToFlash(String ssid, String pass, String host, int port);
    
    // 从Flash读取配置
    bool loadFromFlash();
};

#endif // WEB_CONFIG_H
