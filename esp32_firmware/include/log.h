/*
 * 桌面宠物 - 统一日志分级模块
 *
 * 日志级别: 0=ERROR, 1=WARN, 2=INFO(默认), 3=DEBUG
 * 用法:
 *   #include "log.h"
 *   LOG_I("WiFi connected, IP: %s", ip.c_str());
 *   LOG_E("Failed to init display");
 *
 * Release构建可在platformio.ini中设置:
 *   build_flags = -DLOG_LEVEL=0   // 仅ERROR
 */
#ifndef DESK_PET_LOG_H
#define DESK_PET_LOG_H

#ifndef LOG_LEVEL
#define LOG_LEVEL 2  // 默认INFO级别
#endif

#define LOG_E(fmt, ...) do { if (LOG_LEVEL >= 0) Serial.printf("[E][%s] " fmt "\n", __func__, ##__VA_ARGS__); } while(0)
#define LOG_W(fmt, ...) do { if (LOG_LEVEL >= 1) Serial.printf("[W][%s] " fmt "\n", __func__, ##__VA_ARGS__); } while(0)
#define LOG_I(fmt, ...) do { if (LOG_LEVEL >= 2) Serial.printf("[I][%s] " fmt "\n", __func__, ##__VA_ARGS__); } while(0)
#define LOG_D(fmt, ...) do { if (LOG_LEVEL >= 3) Serial.printf("[D][%s] " fmt "\n", __func__, ##__VA_ARGS__); } while(0)

#endif // DESK_PET_LOG_H
