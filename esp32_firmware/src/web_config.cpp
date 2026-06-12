#include "web_config.h"

WebConfig::WebConfig() : _server(nullptr), _state(CONFIG_IDLE), _configStartTime(0) {
    _config.valid = false;
    _config.server_port = SERVER_PORT;
}

bool WebConfig::begin() {
    _prefs.begin("pet_config", false);
    return loadFromFlash();
}

bool WebConfig::connectFromSaved() {
    if (!_config.valid) {
        Serial.println("[WebConfig] No saved config found");
        return false;
    }
    
    Serial.print("[WebConfig] Connecting to saved WiFi: ");
    Serial.println(_config.wifi_ssid);
    
    WiFi.mode(WIFI_STA);
    WiFi.begin(_config.wifi_ssid.c_str(), _config.wifi_password.c_str());
    
    unsigned long start = millis();
    while (WiFi.status() != WL_CONNECTED) {
        if (millis() - start > WIFI_TIMEOUT) {
            Serial.println("[WebConfig] Saved config connection failed");
            return false;
        }
        delay(500);
        Serial.print(".");
    }
    
    Serial.println();
    Serial.print("[WebConfig] Connected! IP: ");
    Serial.println(WiFi.localIP());
    
    _state = CONFIG_CONNECTED;
    return true;
}

void WebConfig::startAPMode() {
    Serial.println("[WebConfig] Starting AP mode...");
    
    // 配置AP模式
    WiFi.mode(WIFI_AP_STA);
    WiFi.softAP(AP_SSID, AP_PASSWORD);
    
    delay(500);
    
    Serial.print("[WebConfig] AP started: ");
    Serial.print(AP_SSID);
    Serial.print(" Password: ");
    Serial.println(AP_PASSWORD);
    Serial.print("[WebConfig] AP IP: ");
    Serial.println(WiFi.softAPIP());
    
    // 创建Web服务器
    if (_server) {
        delete _server;
    }
    _server = new WebServer(CONFIG_PORT);
    
    // 注册路由
    _server->on("/", HTTP_GET, [this]() { handleRoot(); });
    _server->on("/save", HTTP_POST, [this]() { handleSave(); });
    _server->on("/reset", HTTP_GET, [this]() { handleReset(); });
    _server->on("/status", HTTP_GET, [this]() { handleStatus(); });
    
    // OTA固件升级路由
    _server->on("/ota", HTTP_GET, [this]() { handleOTA(); });
    _server->on("/update", HTTP_POST, [this]() { handleOTAUpload(); }, [this]() { /* multipart handler handled internally */ });
    
    _server->begin();
    _state = CONFIG_AP_MODE;
    _configStartTime = millis();
    
    Serial.println("[WebConfig] Web server started on port 80");
}

void WebConfig::handleClient() {
    if (_state == CONFIG_AP_MODE && _server) {
        _server->handleClient();
        
        // 检查超时
        if (millis() - _configStartTime > CONFIG_TIMEOUT) {
            Serial.println("[WebConfig] Config timeout, restarting...");
            ESP.restart();
        }
    }
}

bool WebConfig::isConfiguring() {
    return (_state == CONFIG_AP_MODE);
}

bool WebConfig::isConnected() {
    if (_state == CONFIG_CONNECTED) {
        return (WiFi.status() == WL_CONNECTED);
    }
    return false;
}

StoredConfig WebConfig::getConfig() {
    return _config;
}

void WebConfig::resetConfig() {
    _prefs.clear();
    _config.valid = false;
    Serial.println("[WebConfig] Config reset");
}

String WebConfig::getAPIP() {
    return WiFi.softAPIP().toString();
}

// ============ Web页面处理 ============

void WebConfig::handleRoot() {
    _server->send(200, "text/html", getConfigPageHTML());
}

void WebConfig::handleSave() {
    String ssid = _server->arg("ssid");
    String password = _server->arg("password");
    String serverHost = _server->arg("server_host");
    String serverPort = _server->arg("server_port");
    
    // 验证输入
    if (ssid.length() == 0) {
        _server->send(400, "text/html", getErrorPageHTML("WiFi名称不能为空"));
        return;
    }
    
    if (serverHost.length() == 0) {
        _server->send(400, "text/html", getErrorPageHTML("服务器地址不能为空"));
        return;
    }
    
    int port = serverPort.toInt();
    if (port <= 0 || port > 65535) {
        port = SERVER_PORT;
    }
    
    // 保存配置
    saveToFlash(ssid, password, serverHost, port);
    
    _server->send(200, "text/html", getSuccessPageHTML());
    
    Serial.println("[WebConfig] Config saved, restarting in 3 seconds...");
    delay(3000);
    ESP.restart();
}

void WebConfig::handleReset() {
    resetConfig();
    _server->send(200, "text/html", getSuccessPageHTML());
    
    Serial.println("[WebConfig] Config reset, restarting in 3 seconds...");
    delay(3000);
    ESP.restart();
}

void WebConfig::handleStatus() {
    String json = "{";
    json += "\"state\":\"" + String(_state) + "\",";
    json += "\"valid\":" + String(_config.valid ? "true" : "false") + ",";
    json += "\"ssid\":\"" + _config.wifi_ssid + "\",";
    json += "\"server\":\"" + _config.server_host + ":" + String(_config.server_port) + "\"";
    json += "}";
    _server->send(200, "application/json", json);
}

// ============ Flash存储 ============

void WebConfig::saveToFlash(String ssid, String pass, String host, int port) {
    _prefs.putString("ssid", ssid);
    _prefs.putString("pass", pass);
    _prefs.putString("host", host);
    _prefs.putInt("port", port);
    _prefs.putBool("valid", true);
    
    _config.wifi_ssid = ssid;
    _config.wifi_password = pass;
    _config.server_host = host;
    _config.server_port = port;
    _config.valid = true;
    
    Serial.println("[WebConfig] Config saved to Flash");
}

bool WebConfig::loadFromFlash() {
    _config.valid = _prefs.getBool("valid", false);
    
    if (!_config.valid) {
        Serial.println("[WebConfig] No valid config in Flash");
        return false;
    }
    
    _config.wifi_ssid = _prefs.getString("ssid", "");
    _config.wifi_password = _prefs.getString("pass", "");
    _config.server_host = _prefs.getString("host", "");
    _config.server_port = _prefs.getInt("port", SERVER_PORT);
    
    Serial.print("[WebConfig] Loaded config: ");
    Serial.print(_config.wifi_ssid);
    Serial.print(" -> ");
    Serial.print(_config.server_host);
    Serial.print(":");
    Serial.println(_config.server_port);
    
    return true;
}

// ============ HTML页面生成 ============

String WebConfig::getConfigPageHTML() {
    String html = R"rawliteral(
<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>桌面宠物配网</title>
    <style>
        * { box-sizing: border-box; margin: 0; padding: 0; }
        body {
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            min-height: 100vh;
            display: flex;
            align-items: center;
            justify-content: center;
            padding: 20px;
        }
        .container {
            background: white;
            border-radius: 20px;
            box-shadow: 0 20px 60px rgba(0,0,0,0.3);
            padding: 40px;
            width: 100%;
            max-width: 400px;
        }
        h1 {
            text-align: center;
            color: #333;
            margin-bottom: 30px;
            font-size: 24px;
        }
        .emoji {
            text-align: center;
            font-size: 48px;
            margin-bottom: 20px;
        }
        .form-group {
            margin-bottom: 20px;
        }
        label {
            display: block;
            margin-bottom: 8px;
            color: #555;
            font-weight: 500;
        }
        input {
            width: 100%;
            padding: 12px 16px;
            border: 2px solid #e0e0e0;
            border-radius: 10px;
            font-size: 16px;
            transition: border-color 0.3s;
        }
        input:focus {
            outline: none;
            border-color: #667eea;
        }
        .hint {
            font-size: 12px;
            color: #999;
            margin-top: 4px;
        }
        button {
            width: 100%;
            padding: 14px;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white;
            border: none;
            border-radius: 10px;
            font-size: 18px;
            font-weight: 600;
            cursor: pointer;
            transition: transform 0.2s, box-shadow 0.2s;
        }
        button:hover {
            transform: translateY(-2px);
            box-shadow: 0 5px 20px rgba(102,126,234,0.4);
        }
        button:active {
            transform: translateY(0);
        }
        .divider {
            border-top: 1px solid #eee;
            margin: 25px 0;
        }
        .reset-btn {
            background: #ff6b6b;
            margin-top: 10px;
        }
        .reset-btn:hover {
            box-shadow: 0 5px 20px rgba(255,107,107,0.4);
        }
        .footer {
            text-align: center;
            margin-top: 20px;
            color: #999;
            font-size: 12px;
        }
    </style>
</head>
<body>
    <div class="container">
        <div class="emoji">🤖</div>
        <h1>桌面宠物配网</h1>
        <form action="/save" method="POST">
            <div class="form-group">
                <label>📶 WiFi名称</label>
                <input type="text" name="ssid" placeholder="输入WiFi名称" required>
            </div>
            <div class="form-group">
                <label>🔑 WiFi密码</label>
                <input type="password" name="password" placeholder="输入WiFi密码">
                <div class="hint">开放网络可留空</div>
            </div>
            <div class="divider"></div>
            <div class="form-group">
                <label>🖥️ 服务器地址</label>
                <input type="text" name="server_host" placeholder="如: 192.168.1.100" required>
                <div class="hint">运行PC监控程序的电脑IP地址</div>
            </div>
            <div class="form-group">
                <label>🔌 服务器端口</label>
                <input type="number" name="server_port" value="19876" min="1" max="65535">
                <div class="hint">默认端口 19876，一般无需修改</div>
            </div>
            <button type="submit">✅ 保存并连接</button>
        </form>
        <a href="/ota"><button style="background:linear-gradient(135deg,#00b894 0%,#00cec9 100%);margin-bottom:10px;" type="button">📦 固件升级(OTA)</button></a>
        <div class="divider"></div>
        <a href="/reset"><button class="reset-btn" type="button">🔄 重置配置</button></a>
        <div class="footer">配置将保存到设备，重启后自动连接</div>
    </div>
</body>
</html>
)rawliteral";
    return html;
}

String WebConfig::getSuccessPageHTML() {
    String html = R"rawliteral(
<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>配置成功</title>
    <style>
        body {
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            min-height: 100vh;
            display: flex;
            align-items: center;
            justify-content: center;
        }
        .container {
            background: white;
            border-radius: 20px;
            padding: 40px;
            text-align: center;
            box-shadow: 0 20px 60px rgba(0,0,0,0.3);
        }
        .emoji { font-size: 64px; margin-bottom: 20px; }
        h1 { color: #333; margin-bottom: 10px; }
        p { color: #666; }
    </style>
</head>
<body>
    <div class="container">
        <div class="emoji">✅</div>
        <h1>配置成功！</h1>
        <p>设备正在重启，请稍候...</p>
        <p style="margin-top:20px; color:#999; font-size:12px;">约10秒后自动连接WiFi</p>
    </div>
</body>
</html>
)rawliteral";
    return html;
}

String WebConfig::getErrorPageHTML(String msg) {
    String html = R"rawliteral(
<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>错误</title>
    <style>
        body {
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            min-height: 100vh;
            display: flex;
            align-items: center;
            justify-content: center;
        }
        .container {
            background: white;
            border-radius: 20px;
            padding: 40px;
            text-align: center;
            box-shadow: 0 20px 60px rgba(0,0,0,0.3);
        }
        .emoji { font-size: 64px; margin-bottom: 20px; }
        h1 { color: #e74c3c; margin-bottom: 10px; }
        p { color: #666; margin-bottom: 20px; }
        a { color: #667eea; text-decoration: none; font-weight: 600; }
    </style>
</head>
<body>
    <div class="container">
        <div class="emoji">❌</div>
        <h1>配置失败</h1>
        <p>)rawliteral" + msg + R"rawliteral(</p>
        <a href="/">← 返回重试</a>
    </div>
</body>
</html>
)rawliteral";
    return html;
}

// ============ OTA 固件升级 ============

void WebConfig::handleOTA() {
    String html = R"rawliteral(
<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>固件升级 - 桌面宠物</title>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
               background: linear-gradient(135deg, #0c0c1d 0%, #1a1a2e 50%, #16213e 100%);
               min-height: 100vh; display: flex; justify-content: center; align-items: center; }
        .container { background: rgba(255,255,255,0.95); border-radius: 24px;
                     padding: 40px; width: 100%; max-width: 420px;
                     box-shadow: 0 20px 60px rgba(0,0,0,0.3); text-align: center; }
        .emoji { font-size: 64px; margin-bottom: 20px; }
        h1 { color: #2d3436; margin-bottom: 10px; font-size: 24px; }
        p { color: #666; margin-bottom: 20px; font-size: 14px; }
        .upload-area { border: 2px dashed #ddd; border-radius: 12px; padding: 30px;
                       margin-bottom: 20px; cursor: pointer; transition: all 0.3s; }
        .upload-area:hover { border-color: #667eea; background: rgba(102,126,234,0.05); }
        .upload-area.dragover { border-color: #667eea; background: rgba(102,126,234,0.1); }
        input[type="file"] { display: none; }
        .btn { background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
               color: white; border: none; padding: 14px 40px; border-radius: 12px;
               font-size: 16px; font-weight: 600; cursor: pointer; width: 100%; margin-bottom: 10px; }
        .btn:hover { transform: translateY(-2px); box-shadow: 0 10px 30px rgba(102,126,234,0.4); }
        .btn:disabled { opacity: 0.6; cursor: not-allowed; transform: none; }
        .btn-back { background: transparent; color: #667eea; box-shadow: none; margin-top: 10px; }
        .progress { display: none; margin-bottom: 20px; }
        .progress-bar { height: 8px; background: #eee; border-radius: 4px; overflow: hidden; }
        .progress-fill { height: 100%; background: linear-gradient(90deg, #667eea, #764ba2);
                         width: 0%; transition: width 0.3s; }
        .progress-text { font-size: 12px; color: #999; margin-top: 5px; }
        .status { margin-top: 15px; padding: 12px; border-radius: 8px; font-size: 14px; display: none; }
        .status.success { background: #d4edda; color: #155724; display: block; }
        .status.error { background: #f8d7da; color: #721c24; display: block; }
        .file-info { margin-top: 10px; font-size: 13px; color: #667eea; }
    </style>
</head>
<body>
    <div class="container">
        <div class="emoji">📦</div>
        <h1>固件升级</h1>
        <p>选择 .bin 固件文件进行OTA无线升级</p>
        <form id="otaForm" method="POST" action="/update" enctype="multipart/form-data">
            <div class="upload-area" id="uploadArea">
                <p>📁 点击选择或拖拽固件文件</p>
                <p style="font-size:12px;color:#999;">支持 .bin 格式</p>
                <input type="file" id="firmware" name="firmware" accept=".bin">
            </div>
            <div class="file-info" id="fileInfo"></div>
            <div class="progress" id="progress">
                <div class="progress-bar"><div class="progress-fill" id="progressFill"></div></div>
                <div class="progress-text" id="progressText">0%</div>
            </div>
            <button type="submit" class="btn" id="uploadBtn" disabled>🚀 开始升级</button>
            <a href="/" class="btn btn-back">← 返回配置页</a>
        </form>
        <div class="status" id="status"></div>
    </div>
    <script>
        const uploadArea = document.getElementById('uploadArea');
        const fileInput = document.getElementById('firmware');
        const fileInfo = document.getElementById('fileInfo');
        const uploadBtn = document.getElementById('uploadBtn');
        const progress = document.getElementById('progress');
        const progressFill = document.getElementById('progressFill');
        const progressText = document.getElementById('progressText');
        const status = document.getElementById('status');
        uploadArea.addEventListener('click', () => fileInput.click());
        uploadArea.addEventListener('dragover', (e) => { e.preventDefault(); uploadArea.classList.add('dragover'); });
        uploadArea.addEventListener('dragleave', () => uploadArea.classList.remove('dragover'));
        uploadArea.addEventListener('drop', (e) => { e.preventDefault(); uploadArea.classList.remove('dragover');
            if (e.dataTransfer.files.length) { fileInput.files = e.dataTransfer.files; handleFile(e.dataTransfer.files[0]); } });
        fileInput.addEventListener('change', () => { if (fileInput.files.length) handleFile(fileInput.files[0]); });
        function handleFile(file) {
            if (!file.name.endsWith('.bin')) { status.className = 'status error'; status.textContent = '请选择 .bin 文件'; status.style.display='block'; return; }
            fileInfo.textContent = file.name + ' (' + (file.size/1024).toFixed(1) + ' KB)';
            uploadBtn.disabled = false; status.style.display = 'none';
        }
        document.getElementById('otaForm').addEventListener('submit', function(e) {
            e.preventDefault();
            const formData = new FormData(this);
            const xhr = new XMLHttpRequest();
            xhr.upload.addEventListener('progress', (e) => {
                if (e.lengthComputable) { const pct = Math.round(e.loaded/e.total*100);
                    progressFill.style.width = pct + '%'; progressText.textContent = pct + '%'; }
            });
            xhr.onload = function() {
                if (xhr.status === 200) { status.className = 'status success';
                    status.textContent = '✅ 固件升级成功！设备即将重启...'; }
                else { status.className = 'status error'; status.textContent = '❌ 升级失败: ' + xhr.responseText; }
                uploadBtn.disabled = false;
            };
            xhr.onerror = function() { status.className = 'status error'; status.textContent = '❌ 网络错误'; uploadBtn.disabled = false; };
            progress.style.display = 'block'; uploadBtn.disabled = true;
            xhr.open('POST', '/update'); xhr.send(formData);
        });
    </script>
</body>
</html>
)rawliteral";
    _server->send(200, "text/html", html);
}

void WebConfig::handleOTAUpload() {
    HTTPUpload& upload = _server->upload();

    if (upload.status == UPLOAD_FILE_START) {
        Serial.printf("[OTA] Start: %s\n", upload.filename.c_str());
        if (!Update.begin(UPDATE_SIZE_UNKNOWN)) {
            Update.printError(Serial);
        }
    }
    else if (upload.status == UPLOAD_FILE_WRITE) {
        if (Update.write(upload.buf, upload.currentSize) != upload.currentSize) {
            Update.printError(Serial);
        }
    }
    else if (upload.status == UPLOAD_FILE_END) {
        if (Update.end(true)) {
            Serial.printf("[OTA] Success: %u bytes\n", upload.totalSize);
        } else {
            Update.printError(Serial);
        }
    }

    // 上传完成后发送响应
    if (upload.status == UPLOAD_FILE_END) {
        if (Update.hasError()) {
            _server->send(500, "text/plain", "升级失败");
        } else {
            _server->send(200, "text/plain", "升级成功");
            delay(1000);
            ESP.restart();
        }
    }
}
