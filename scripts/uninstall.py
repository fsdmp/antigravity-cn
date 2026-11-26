#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
uninstall.py — 完整卸载汉化包，恢复安装前状态

还原内容:
  1. 卸载语言包扩展（CLI 或直接删除扩展目录）
  2. argv.json 还原为备份版本（移除 locale）
  3. settings.json 还原备份（恢复遥测设置原值；若安装前无此文件则删除追加的键）
  4. 管理器 AppleLanguages 偏好还原

备份位置: ~/.antigravity-ide/.zh-pack-backup/
"""

import json
import shutil
import subprocess
import sys
from pathlib import Path

DATA_DIR = Path.home() / ".antigravity-ide"
USER_DATA = Path.home() / "Library/Application Support/Antigravity IDE"
LANGUAGEPACKS = USER_DATA / "languagepacks.json"
BACKUP = DATA_DIR / ".zh-pack-backup"
ARGV_JSON = DATA_DIR / "argv.json"
USER_SETTINGS = DATA_DIR / "User" / "settings.json"
IDE_CLI = Path("/Applications/Antigravity IDE.app/Contents/Resources/app/bin/antigravity-ide")
MANAGER_BUNDLE = "com.google.antigravity"
EXT_ID = "antigravity-cn.antigravity-ide-zh-hans"


def remove_extension():
    if IDE_CLI.exists():
        r = subprocess.run([str(IDE_CLI), "--uninstall-extension", EXT_ID],
                           capture_output=True, text=True)
        out = (r.stdout + r.stderr).strip()
        if "successfully uninstalled" in out.lower() or "not installed" in out.lower():
            print(f"  CLI 卸载: {out.splitlines()[-1]}")
            return
        print(f"  CLI 卸载未成功 (返回码 {r.returncode}), 改为手动清理")
    # 手动清理: 删除扩展目录 + 从 extensions.json 移除登记
    ext_root = DATA_DIR / "extensions"
    removed = False
    if ext_root.exists():
        for d in list(ext_root.glob(f"{EXT_ID}*")):
            shutil.rmtree(d, ignore_errors=True)
            removed = True
        reg = ext_root / "extensions.json"
        if reg.exists():
            try:
                entries = json.loads(reg.read_text(encoding="utf-8"))
                entries = [e for e in entries
                           if e.get("identifier", {}).get("id") != EXT_ID]
                reg.write_text(json.dumps(entries, ensure_ascii=False, indent=2),
                               encoding="utf-8")
            except Exception as e:
                print(f"  extensions.json 清理失败: {e}")
    print(f"  手动清理{'完成' if removed else ': 未发现扩展目录'}")


def restore_json(p: Path, backup_name: str, remove_if_absent: bool):
    bak = BACKUP / backup_name
    if bak.exists():
        # 兜底: 若备份内容恰好只是本工具写入的遥测键(说明备份被重复安装污染,
        # 原始状态是该文件不存在), 删除文件才是真正还原
        try:
            keys = set(json.loads(bak.read_text(encoding="utf-8")).keys())
        except Exception:
            keys = None
        if keys is not None and keys and keys <= {"telemetry.telemetryLevel",
                                                  "telemetry.enableCrashReporter",
                                                  "telemetry.enableTelemetry"}:
            if p.exists():
                p.unlink()
            print(f"  {p.name} 备份仅含遥测键(安装前无此文件), 已删除")
            return
        shutil.copy2(bak, p)
        print(f"  {p.name} 已还原为备份版本")
    else:
        if remove_if_absent and p.exists():
            p.unlink()
            print(f"  {p.name} 安装前不存在, 已删除")
        else:
            print(f"  {p.name} 无备份且安装前不存在, 保持现状")


def restore_defaults():
    f = BACKUP / "applelanguages.txt"
    if f.exists():
        orig = f.read_text(encoding="utf-8").strip()
        if orig:
            # defaults read 输出形如: ( \n "en", \n "zh-CN", \n )，逐行解析语言代码
            langs = [l.strip().strip(',').strip('"') for l in orig.splitlines()
                     if l.strip().strip(',').strip('"')]
            subprocess.run(["defaults", "delete", MANAGER_BUNDLE, "AppleLanguages"],
                           capture_output=True)
            if langs:
                subprocess.run(["defaults", "write", MANAGER_BUNDLE, "AppleLanguages",
                                "-array", *langs], check=False)
            print(f"  管理器 AppleLanguages 已还原 ({len(langs)} 项)")
        else:
            subprocess.run(["defaults", "delete", MANAGER_BUNDLE, "AppleLanguages"],
                           capture_output=True)
            print("  管理器 AppleLanguages 已删除 (安装前无此项)")
    else:
        subprocess.run(["defaults", "delete", MANAGER_BUNDLE, "AppleLanguages"],
                       capture_output=True)
        print("  管理器 AppleLanguages 已删除 (无备份, 按安装前不存在处理)")


def cleanup_backup():
    if BACKUP.exists():
        shutil.rmtree(BACKUP)
        print(f"  备份目录已清理: {BACKUP}")


def remove_languagepack_entry():
    """从 languagepacks.json 移除本语言包条目, 主进程启动即回退英文; 并清理 clp 缓存"""
    if not LANGUAGEPACKS.exists():
        print("  languagepacks.json 不存在, 跳过")
        return
    try:
        data = json.loads(LANGUAGEPACKS.read_text(encoding="utf-8"))
    except Exception:
        print("  languagepacks.json 解析失败, 跳过")
        return
    removed = []
    for lang, entry in list(data.items()):
        exts = entry.get("extensions", [])
        if any(e.get("extensionIdentifier", {}).get("id") == EXT_ID for e in exts):
            del data[lang]
            removed.append(lang)
            clp = USER_DATA / "clp"
            if clp.exists():
                for d in clp.glob(f"{entry.get('hash', '*')}.{lang}"):
                    shutil.rmtree(d, ignore_errors=True)
    LANGUAGEPACKS.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    print(f"  已移除语言条目: {', '.join(removed) if removed else '(无)'}")


def main():
    print("[1/5] 卸载语言包扩展")
    remove_extension()

    print("[2/5] 清理 languagepacks.json 与 clp 缓存")
    remove_languagepack_entry()

    print("[3/5] 还原 argv.json")
    restore_json(ARGV_JSON, "argv.json.bak", remove_if_absent=False)

    print("[4/5] 还原 settings.json")
    restore_json(USER_SETTINGS, "settings.json.bak", remove_if_absent=True)

    print("[5/5] 还原管理器语言偏好")
    restore_defaults()
    cleanup_backup()

    print("完成 ✓  重启 Antigravity IDE 即恢复英文界面")


if __name__ == "__main__":
    main()
