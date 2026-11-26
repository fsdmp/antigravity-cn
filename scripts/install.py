#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
install.py — 离线安装 Antigravity IDE 简体中文语言包

步骤:
  1. 备份原始状态到 ~/.antigravity-ide/.zh-pack-backup/（供 uninstall.py 精确还原）
  2. 用 IDE 自带 CLI 离线安装 VSIX（不联网、不访问扩展市场）
  3. argv.json 设置 locale=zh-cn（JSONC 文件，保留原有注释）
  4. settings.json 关闭遥测上报（telemetry.telemetryLevel=off）
  5. 为 Antigravity 管理器设置 AppleLanguages 偏好（远程 UI 可能自动切中文）

全程不修改 /Applications 下的任何应用文件 —— 签名、完整性、自动更新都不受影响。
"""

import hashlib
import json
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

PROJECT = Path(__file__).resolve().parent.parent
IDE_CLI = Path("/Applications/Antigravity IDE.app/Contents/Resources/app/bin/antigravity-ide")
DATA_DIR = Path.home() / ".antigravity-ide"
USER_DATA = Path.home() / "Library/Application Support/Antigravity IDE"
LANGUAGEPACKS = USER_DATA / "languagepacks.json"
BACKUP = DATA_DIR / ".zh-pack-backup"
ARGV_JSON = DATA_DIR / "argv.json"
USER_SETTINGS = DATA_DIR / "User" / "settings.json"
MANAGER_BUNDLE = "com.google.antigravity"
EXT_ID = "antigravity-cn.antigravity-ide-zh-hans"

TELEMETRY_KEYS = {
    "telemetry.telemetryLevel": "off",
    "telemetry.enableCrashReporter": False,
    "telemetry.enableTelemetry": False,
}


def find_vsix() -> Path:
    vsixes = sorted(PROJECT.glob("build/*.vsix"))
    if not vsixes:
        sys.exit("错误: build/ 下没有 VSIX，请先运行 python3 scripts/build_vsix.py")
    return vsixes[-1]


def backup_file(p: Path):
    BACKUP.mkdir(parents=True, exist_ok=True)
    dest = BACKUP / (p.name + ".bak")
    if p.exists():
        if not dest.exists():  # 仅首次安装备份; 重复安装不覆盖, 保证回滚点始终是原始状态
            shutil.copy2(p, dest)
        return p.read_text(encoding="utf-8")
    return None


def backup_defaults():
    """记录管理器 AppleLanguages 原始值(仅首次)"""
    if (BACKUP / "applelanguages.txt").exists():
        return
    try:
        out = subprocess.run(
            ["defaults", "read", MANAGER_BUNDLE, "AppleLanguages"],
            capture_output=True, text=True)
        orig = out.stdout.strip() if out.returncode == 0 else ""
        (BACKUP / "applelanguages.txt").write_text(orig, encoding="utf-8")
    except Exception:
        pass


# ---------------- argv.json (JSONC) 编辑 ----------------

def set_locale_in_argv(locale: str = "zh-cn"):
    text = ARGV_JSON.read_text(encoding="utf-8") if ARGV_JSON.exists() else "{}"
    if re.search(r'["\']locale["\']\s*:', text):
        text = re.sub(r'(["\']locale["\']\s*:\s*)["\'][^"\']*["\']',
                      rf'\1"{locale}"', text, count=1)
    else:
        # 在第一个 { 之后插入 locale 键
        m = re.search(r'\{', text)
        insert = f'{m.group(0)}\n\t// 界面语言: 简体中文 (由 antigravity-cn install.py 设置)\n\t"locale": "{locale}",'
        text = text[:m.start()] + insert + text[m.end():]
    ARGV_JSON.write_text(text, encoding="utf-8")
    print(f"  argv.json -> locale = {locale}")


# ---------------- settings.json (JSONC 兼容) 编辑 ----------------

def apply_telemetry_off():
    text = USER_SETTINGS.read_text(encoding="utf-8") if USER_SETTINGS.exists() else "{}"
    m = re.search(r'\{', text)
    if not m:
        text = "{}"
        m = re.search(r'\{', text)
    additions = ""
    for k, v in TELEMETRY_KEYS.items():
        if re.search(rf'["\']{re.escape(k)}["\']\s*:', text):
            text = re.sub(rf'(["\']{re.escape(k)}["\']\s*:\s*)(?:true|false|"[^"]*")',
                          rf'\1{json.dumps(v)}', text, count=1)
        else:
            additions += f'\n\t"{k}": {json.dumps(v)},'
    if additions:
        insert = f'{m.group(0)}{additions}'
        text = text[:m.start()] + insert + text[m.end():]
    USER_SETTINGS.parent.mkdir(parents=True, exist_ok=True)
    USER_SETTINGS.write_text(text, encoding="utf-8")
    print("  settings.json -> 遥测上报已关闭 (telemetryLevel=off)")


def set_manager_language():
    subprocess.run(["defaults", "write", MANAGER_BUNDLE, "AppleLanguages",
                    "-array", "zh-CN", "en"], check=False)
    print("  管理器 AppleLanguages -> zh-CN (远程 UI 将请求中文, 若官方支持则自动切换)")


def install_extension(vsix: Path) -> bool:
    if IDE_CLI.exists():
        print(f"  CLI 安装: {vsix.name}")
        r = subprocess.run([str(IDE_CLI), "--install-extension", str(vsix)],
                           capture_output=True, text=True)
        out = (r.stdout + r.stderr).strip()
        if "successfully installed" in out.lower() or "already installed" in out.lower():
            print("  " + out.splitlines()[-1])
            return True
        print(f"  CLI 安装未成功 (返回码 {r.returncode}), 输出:\n{out[:400]}")
    return False


def vsix_version(vsix: Path) -> str:
    """从 VSIX 的 package.json 读取版本号 (patch 位随译文内容变化)"""
    import zipfile
    with zipfile.ZipFile(vsix) as z:
        pkg = json.loads(z.read("extension/package.json"))
    return pkg["version"]


def manual_install(vsix: Path) -> bool:
    """CLI 失败时的兜底: 直接落盘到用户扩展目录并登记 extensions.json (不联网)"""
    import zipfile
    ext_root = DATA_DIR / "extensions"
    ext_root.mkdir(parents=True, exist_ok=True)
    ver = vsix_version(vsix)
    target = ext_root / f"{EXT_ID}-{ver}"
    # 清理其他版本的残留目录(版本号随内容变化)
    for d in ext_root.glob(f"{EXT_ID}-*"):
        if d != target:
            shutil.rmtree(d, ignore_errors=True)
    if target.exists():
        shutil.rmtree(target)
    with zipfile.ZipFile(vsix) as z:
        z.extractall(target)
    # VSIX 内部结构: extension/<files> -> 展平到 target 根
    inner = target / "extension"
    if inner.exists():
        for p in inner.iterdir():
            shutil.move(str(p), str(target / p.name))
        inner.rmdir()

    reg = ext_root / "extensions.json"
    entries = []
    if reg.exists():
        try:
            entries = json.loads(reg.read_text(encoding="utf-8"))
        except Exception:
            entries = []
    loc = str(target)
    entries = [e for e in entries if e.get("identifier", {}).get("id") != EXT_ID]
    entries.append({
        "identifier": {"id": EXT_ID},
        "version": ver,
        "location": {"$mid": 1, "fsPath": loc, "external": "file://" + loc,
                     "path": loc, "scheme": "file"},
        "relativeLocation": target.name,
        "metadata": {"isMachineScoped": False, "isBuiltin": False,
                     "installedTimestamp": int(time.time() * 1000)},
    })
    reg.write_text(json.dumps(entries, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"  手动安装完成: {target}")
    return True


def update_languagepacks_json():
    """直接维护 languagepacks.json。

    主进程启动时只读这个文件来找语言包, hash = md5(扩展ID + 版本号), 与文件内容无关;
    CLI 安装后此文件未必被立即重写 —— 这里主动写入正确条目, 保证下次启动读到新版本,
    同时清掉旧 hash 对应的 clp 缓存目录(否则旧译文会被一直复用)。
    """
    ext_root = DATA_DIR / "extensions"
    dirs = list(ext_root.glob(f"{EXT_ID}-*"))
    if not dirs:
        print("  跳过 languagepacks.json (未找到已安装的扩展目录)")
        return
    target = dirs[-1]
    ver = target.name[len(EXT_ID) + 1:]
    pkg = json.loads((target / "package.json").read_text(encoding="utf-8"))

    translations = {}
    for loc in pkg.get("contributes", {}).get("localizations", []):
        lang = loc["languageId"]
        for t in loc.get("translations", []):
            p = target / t["path"].lstrip("./")
            if p.exists():
                translations[t["id"]] = str(p)
        entry_hash = hashlib.md5((EXT_ID + ver).encode()).hexdigest()

        data = {}
        if LANGUAGEPACKS.exists():
            try:
                data = json.loads(LANGUAGEPACKS.read_text(encoding="utf-8"))
            except Exception:
                data = {}
        old_hash = (data.get(lang) or {}).get("hash")
        data[lang] = {"hash": entry_hash,
                      "extensions": [{"extensionIdentifier": {"id": EXT_ID},
                                      "version": ver}],
                      "translations": translations}
        LANGUAGEPACKS.parent.mkdir(parents=True, exist_ok=True)
        LANGUAGEPACKS.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")

        # 清掉旧 hash 的 clp 缓存目录, 防止旧译文复用
        clp = USER_DATA / "clp"
        if clp.exists() and old_hash and old_hash != entry_hash:
            for d in clp.glob(f"{old_hash}.{lang}"):
                shutil.rmtree(d, ignore_errors=True)
                print(f"  已清理旧缓存: clp/{d.name}")
        print(f"  languagepacks.json -> {lang} (v{ver}, hash {entry_hash[:12]}…)")


def main():
    vsix = find_vsix()
    print(f"[1/4] 备份原始状态 -> {BACKUP}")
    backup_file(ARGV_JSON)
    backup_file(USER_SETTINGS)
    backup_defaults()

    print("[2/4] 安装语言包 (离线)")
    if not install_extension(vsix):
        manual_install(vsix)

    print("[3/4] 配置语言与隐私")
    set_locale_in_argv()
    apply_telemetry_off()
    set_manager_language()
    update_languagepacks_json()

    print("[4/4] 完成 ✓  重启 Antigravity IDE 后生效")
    print("      回滚: python3 scripts/uninstall.py")


if __name__ == "__main__":
    main()
