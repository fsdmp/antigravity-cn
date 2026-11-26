#!/usr/bin/env python3
"""integrity_check.py — 验证 Antigravity 应用未被修改（纯 stdlib，只读）

验证三层完整性，全部通过说明 /Applications 下的应用与官方发布物逐字节一致：
  1. codesign --verify --deep --strict   代码签名封签（含所有资源）
  2. ElectronAsarIntegrity               Info.plist 记录的 asar 目录头 SHA256
                                         （注意: 记录的是 asar 头部 JSON 区, 不是整文件）
  3. Gatekeeper (spctl -a)               系统级评估（仅管理器）

用法: python3 scripts/manager/integrity_check.py [应用路径 ...]
      缺省检查 /Applications/Antigravity.app 与 /Applications/Antigravity IDE.app
"""
import hashlib
import json
import struct
import subprocess
import sys
from pathlib import Path

DEFAULT_APPS = [
    Path("/Applications/Antigravity.app"),
    Path("/Applications/Antigravity IDE.app"),
]


def check_signature(app: Path) -> bool:
    r = subprocess.run(["codesign", "--verify", "--deep", "--strict", str(app)],
                       capture_output=True, text=True)
    if r.returncode == 0:
        print(f"  [✓] 代码签名完整 ({app.name})")
        return True
    print(f"  [✗] 签名校验失败: {r.stderr.strip() or r.returncode}")
    return False


def check_gatekeeper(app: Path) -> bool:
    r = subprocess.run(["spctl", "-a", "-t", "exec", str(app)], capture_output=True)
    if r.returncode == 0:
        print(f"  [✓] Gatekeeper 接受 ({app.name})")
        return True
    print(f"  [✗] Gatekeeper 拒绝 (exit {r.returncode})")
    return False


def check_asar_integrity(app: Path) -> bool:
    """对比 Info.plist ElectronAsarIntegrity 记录的哈希与 asar 实际目录头哈希。

    asar 头部布局: [u32 pickle总长][u32 头pickle长][u32 json长度][u32 json长度] + JSON
    Electron 记录的 hash = SHA256(从偏移 16 起的 JSON 区)。
    """
    plist = app / "Contents" / "Info.plist"
    if not plist.exists():
        print(f"  [-] 无 Info.plist, 跳过 ({app.name})")
        return True
    out = subprocess.run(["plutil", "-convert", "json", "-o", "-", str(plist)],
                         capture_output=True, text=True)
    if out.returncode != 0:
        print(f"  [✗] Info.plist 读取失败: {out.stderr.strip()}")
        return False
    integ = json.loads(out.stdout).get("ElectronAsarIntegrity")
    if not integ:
        print(f"  [-] 无 ElectronAsarIntegrity 记录, 跳过 ({app.name})")
        return True

    ok = True
    for name, meta in sorted(integ.items()):
        p = app / "Contents" / name
        if not p.exists():
            # 官方 Info.plist 可能记录了实际未随包发布的条目（如 IDE 无 default_app.asar）
            print(f"  [-] {name} 官方记录存在但未随包发布, 视为官方原状")
            continue
        raw = p.read_bytes()
        js_size = struct.unpack("<I", raw[12:16])[0]
        actual = hashlib.sha256(raw[16:16 + js_size]).hexdigest()
        if actual == meta.get("hash"):
            print(f"  [✓] {name} 与官方哈希一致")
        else:
            print(f"  [✗] {name} 哈希不符 → 文件被改动过！")
            ok = False
    return ok


def main() -> int:
    apps = [Path(a) for a in sys.argv[1:]] or [a for a in DEFAULT_APPS if a.exists()]
    if not apps:
        print("未找到待检查的应用路径")
        return 1
    all_ok = True
    for app in apps:
        print(f"== {app} ==")
        all_ok &= check_signature(app)
        all_ok &= check_asar_integrity(app)
        if app.name == "Antigravity.app":
            all_ok &= check_gatekeeper(app)
    print("结论: 全部通过, 应用未被修改 ✓" if all_ok else "结论: 存在完整性问题 ✗")
    return 0 if all_ok else 1


if __name__ == "__main__":
    sys.exit(main())
