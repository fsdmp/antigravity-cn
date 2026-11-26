#!/bin/bash
# Antigravity 管理器中文界面 — 双击启动 (CDP 注入, 零文件修改)
# 逻辑: 若管理器已在运行会先退出再以注入模式重启; 终端窗口保持打开即持续守护
cd "$(dirname "$0")" || exit 1
echo "Antigravity 管理器汉化 (保持此窗口开启; 关闭窗口不影响已注入的界面)"
echo "停止注入守护: python3 scripts/manager/zh_hub.py --stop"
echo ""
exec python3 scripts/manager/zh_hub.py --relaunch
