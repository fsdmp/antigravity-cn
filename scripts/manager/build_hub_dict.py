#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
build_hub_dict.py — 构建 Antigravity 管理器 (Hub) 界面词典

合并两层来源, 产出 translations/hub.i18n.json (英文原文 → 中文):
  1. translations/hub-community.i18n.json
     社区项目 antigravity-cn-community/Antigravity-Chinese-Localization 的词典
     (MIT 许可, 见 hub-community.LICENSE) — 覆盖 Hub 界面数千条
  2. translations/hub-ext.i18n.json — 本项目对新增界面串的补充 (高优先级覆盖)

维护: 管理器升级后界面新增英文串 → 补进 hub-ext.i18n.json (键=英文原文) → 重跑本脚本
"""
import json
import sys
from pathlib import Path

PROJECT = Path(__file__).resolve().parent.parent.parent
TR = PROJECT / "translations"
COMMUNITY = TR / "hub-community.i18n.json"
EXT = TR / "hub-ext.i18n.json"
OUT = TR / "hub.i18n.json"


def has_cjk(s: str) -> bool:
    return any("一" <= c <= "鿿" for c in s)


def load(p: Path) -> dict:
    if not p.exists():
        return {}
    d = json.loads(p.read_text(encoding="utf-8"))
    bad = [k for k, v in d.items() if not isinstance(v, str) or not v or not has_cjk(v)]
    for k in bad:
        print(f"  [!] 跳过非法条目: {k[:60]!r}", file=sys.stderr)
        del d[k]
    return d


def main():
    if not COMMUNITY.exists():
        sys.exit(f"错误: 缺少 {COMMUNITY} (社区词典底料, MIT)")
    community = load(COMMUNITY)
    ext = load(EXT)

    merged = dict(community)
    merged.update(ext)          # 本项目补充覆盖社区旧译

    OUT.write_text(json.dumps(merged, ensure_ascii=False, indent=1, sort_keys=True),
                   encoding="utf-8")
    print(f"词典构建完成: {OUT}")
    print(f"  社区底料 {len(community)} 条 + 本项目补充 {len(ext)} 条 = {len(merged)} 条")


if __name__ == "__main__":
    main()
