# 桌面电子宠物开发计划

## 项目概述
制作基于微雪ESP32-S3 1.54inch LCD的桌面电子宠物，用于监控AI Agent工作状态。

## 硬件方案
- **主控**: ESP32-S3
- **屏幕**: 微雪1.54inch LCD（方屏，240x240）
- **通信**: WiFi连接PC

## 功能需求
1. 监控AI Agent状态（工作中/空闲/需授权）
2. 显示Token使用数、请求数
3. 天气图标显示
4. 动画表情/图标

## 环境探索结果
- **Python**: 3.11.15 可用
- **PlatformIO**: 未安装（需安装）
- **Arduino CLI**: 未安装（需安装）
- **代码根目录**: D:/_MyProject/AIProject/Agent/GenericAgent

---

## 详细开发计划

### T2: 硬件选购指南整理
**交付物**: `plan_desktop_pet/hardware_guide.md`
**依赖**: 无
**SOP**: 无
**任务描述**:
1. 整理微雪ESP32-S3 1.54inch LCD的购买链接和规格参数
2. 列出所需配件（USB线、杜邦线等）
3. 提供硬件接线图（SPI引脚定义）
4. 预算估算

### T3: PC端监控程序开发（Python）
**交付物**: `plan_desktop_pet/pc_monitor/` 目录
**依赖**: 无
**SOP**: 无
**任务描述**:
1. 创建Python项目结构
2. 实现Agent状态监控（检测claudecode/codex/ooencode进程）
3. 实现Token使用统计（解析日志或API）
4. 实现天气API调用
5. 实现与ESP32的串口/WiFi通信协议
6. 编写配置文件（config.json）

### T4: ESP32固件开发（C++/Arduino）
**交付物**: `plan_desktop_pet/esp32_firmware/` 目录
**依赖**: T2（需要硬件规格）
**SOP**: 无
**任务描述**:
1. 安装PlatformIO环境
2. 创建Arduino项目结构
3. 实现屏幕驱动初始化（SPI）
4. 实现WiFi连接
5. 实现与PC的通信协议
6. 实现UI布局（状态栏、天气区、动画区）
7. 实现动画播放（GIF/Lottie解码）

### T5: 项目文档整理
**交付物**: `plan_desktop_pet/README.md`
**依赖**: T2, T3, T4
**SOP**: 无
**任务描述**:
1. 整理项目概述和功能说明
2. 编写硬件选购指南
3. 编写软件安装和使用说明
4. 编写API文档（通信协议）
5. 编写故障排除指南

---

## 执行顺序
1. **T2** → 硬件选购指南（无依赖，可立即开始）
2. **T3** → PC端监控程序（无依赖，可与T2并行）
3. **T4** → ESP32固件（依赖T2的硬件规格）
4. **T5** → 项目文档（依赖T2/T3/T4完成）

## 自检清单
- [ ] 每项都有独立完成判据 ✓
- [ ] 没有"处理所有文件"的模糊描述 ✓
- [ ] 依赖关系明确 ✓
- [ ] 交付物路径明确 ✓
- [ ] SOP引用正确 ✓
