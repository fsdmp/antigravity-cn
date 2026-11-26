#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
update.py — Antigravity IDE 升级后的一键更新入口

IDE 升级可能带来:
  - 新增字符串（新功能界面）→ 重新提取时以英文原文为键去匹配翻译记忆，
    英文未变的直接命中；新增英文串会列出供补充翻译
  - 模块路径/键名变化 → 不影响（匹配按英文原文），未命中的自动回退英文

用法: python3 scripts/update.py [--install]
  默认只重新构建并报告覆盖率；--install 会重新安装到 IDE 并提示重启。
"""

import json
import subprocess
import sys
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent


def main():
    install = "--install" in sys.argv
    print("== 重新构建语言包 (针对当前安装的 IDE 版本) ==")
    r = subprocess.run([sys.executable, str(SCRIPTS / "build_vsix.py")])
    if r.returncode != 0:
        sys.exit(r.returncode)
    if install:
        print("\n== 重新安装 ==")
        subprocess.run([sys.executable, str(SCRIPTS / "install.py")])
        print("\n完成 ✓  请重启 Antigravity IDE")
    else:
        print("\n构建完成。如需安装: python3 scripts/install.py")


if __name__ == "__main__":
    main()
