#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
build_vsix.py — 构建 Antigravity IDE 简体中文语言包 VSIX

原理:
  Antigravity IDE 是 VS Code 1.107 内核的 fork，其全部界面字符串位于
  /Applications/Antigravity IDE.app/Contents/Resources/app/out/nls.messages.json
  （扁平数组），索引顺序由 out/nls.keys.json（[模块路径, [键名...]]）描述。

  安装了语言包扩展后（contributes.localizations），主进程会按
  「模块路径 + 键名」在语言包的 translations/main.i18n.json 中查找译文，
  查不到则回退英文 —— 因此本方案对任意未来版本都是安全的。

  翻译来源两层:
    1. reference/zhpack-*/  官方 vscode-language-pack-zh-hans（MIT 许可）
       —— 覆盖 ~1289 个上游模块
    2. translations/antigravity-ext.i18n.json  翻译记忆（英文原文 → 中文）
       —— 覆盖 Antigravity 专有模块（官方语言包没有的部分）
       以英文原文为键的好处: IDE 升级后模块路径/键名可能变化，
       但只要英文原文未变，译文仍然自动命中。

输出:
  build/antigravity-ide-zh-hans-<version>.vsix
"""

import json
import shutil
import sys
import zipfile
import hashlib
from pathlib import Path

PROJECT = Path(__file__).resolve().parent.parent
IDE_APP = Path("/Applications/Antigravity IDE.app")
IDE_OUT = IDE_APP / "Contents/Resources/app/out"
REFERENCE = PROJECT / "reference"
TRANSLATIONS = PROJECT / "translations"
BUILD = PROJECT / "build"

EXT_ID = "antigravity-cn.antigravity-ide-zh-hans"
EXT_NAME = "antigravity-ide-zh-hans"
EXT_VERSION = "1.106.0"
ENGINE = "^1.106.0"


def load_json(p: Path):
    with open(p, encoding="utf-8") as f:
        return json.load(f)


def find_reference() -> list[Path]:
    cands = sorted(REFERENCE.glob("zhpack-*"))
    if not cands:
        sys.exit("错误: reference/ 下没有参考语言包，请先运行 scripts/fetch_reference.py")
    # 按版本号排序，低版本在前 —— 合并时高版本覆盖低版本，取长补短
    return sorted(cands, key=lambda p: [int(x) for x in p.name.split("-")[1].split(".")])


def build():
    refs = find_reference()
    print(f"[1/5] 参考语言包: {[r.name for r in refs]}")

    # --- 读取 IDE 当前版本的 NLS 索引 ---
    nls_keys = load_json(IDE_OUT / "nls.keys.json")       # [[module, [key...]], ...]
    nls_msgs = load_json(IDE_OUT / "nls.messages.json")   # [english string, ...]
    total = sum(len(ks) for _, ks in nls_keys)
    print(f"[2/5] IDE 内核字符串: {len(nls_keys)} 个模块 / {total} 条")
    if total != len(nls_msgs):
        sys.exit("错误: nls.keys.json 与 nls.messages.json 数量不一致，版本可能正在更新，稍后重试")

    # --- 合并所有参考(官方)翻译, 高版本覆盖低版本 ---
    ref_main: dict = {}
    for ref in refs:
        ref_main.update(load_json(ref / "translations/main.i18n.json").get("contents", {}))
    memory = load_json(TRANSLATIONS / "antigravity-ext.i18n.json")

    # --- 合并: 官方模块翻译 + 翻译记忆(按英文原文匹配) ---
    contents = {}
    covered = 0
    fork_covered = 0
    missing = []
    ref_untranslated = []

    idx = 0
    for module, keys in nls_keys:
        n = len(keys)
        eng = nls_msgs[idx : idx + n]
        idx += n

        ref_mod = ref_main.get(module)
        out = {}
        found = 0
        for key, src in zip(keys, eng):
            t = None
            if ref_mod is not None:
                t = ref_mod.get(key)
                if t == src:
                    # 官方包对新键偶有漏翻(值=英文原文), 不能算译文, 落到翻译记忆
                    ref_untranslated.append((module, key, src))
                    t = None
            if t is None:
                t = memory.get(src)
            if t is None:
                missing.append((module, key, src))
                continue
            found += 1          # 按出现次数统计(同模块重复键会共用同一条译文)
            out[key] = t
        contents[module] = out
        covered += found

    fork_modules = [m for m in contents.keys() if m not in ref_main]
    fork_covered = sum(len(contents[m]) for m in fork_modules)
    print(f"[3/5] 翻译覆盖: {covered}/{total} 条 "
          f"(官方包覆盖模块 {len(nls_keys) - len(fork_modules)}, "
          f"Antigravity 专有模块 {len(fork_modules)} / 译文 {fork_covered} 条)")
    if ref_untranslated:
        print(f"      官方包漏翻 {len(ref_untranslated)} 处(已由翻译记忆/英文兜底)")

    if missing:
        # 未翻译的字符串回退英文（NLS 本身也如此），列出前 20 条供维护者补充
        print(f"      提示: {len(missing)} 条暂无译文(将显示英文)，样例:")
        for m, k, s in missing[:20]:
            print(f"        [{m}] {k} = {s[:60]!r}")

    # --- 生成 main.i18n.json ---
    # 版本号 patch 位由译文内容 md5 派生: VS Code 的语言包缓存 hash = md5(扩展ID+版本号),
    # 与内容无关 —— 内容一变版本号必须跟着变, 否则 clp 缓存永远不失效, 旧译文无法更新。
    main_i18n_text = json.dumps(
        {"": "Antigravity IDE 简体中文语言包（由 antigravity-cn 项目生成）",
         "version": EXT_VERSION,
         "contents": contents}, ensure_ascii=False, indent=1)
    patch = int(hashlib.md5(main_i18n_text.encode("utf-8")).hexdigest()[:6], 16) % 100000
    ext_version = f"1.106.{patch}"

    out_dir = BUILD / f"{EXT_NAME}-{ext_version}" / "extension"
    tr_dir = out_dir / "translations"
    if out_dir.exists():
        shutil.rmtree(out_dir)
    tr_dir.mkdir(parents=True)

    (tr_dir / "main.i18n.json").write_text(main_i18n_text, encoding="utf-8")

    # --- 复制官方扩展翻译文件(以最高版本为准) ---
    # translations/ 顶层是 main.i18n.json, extensions/ 子目录是各内置扩展的翻译
    # (package.json contributes.localizations 引用的是 extensions/ 下的路径, 缺了会回退英文)
    ref_tr = refs[-1] / "translations"
    for f in ref_tr.glob("*.i18n.json"):
        if f.name != "main.i18n.json":
            shutil.copy2(f, tr_dir / f.name)
    ext_tr = ref_tr / "extensions"
    if ext_tr.exists():
        (tr_dir / "extensions").mkdir(parents=True)
        for f in ext_tr.glob("*.i18n.json"):
            shutil.copy2(f, tr_dir / "extensions" / f.name)

    # --- package.json ---
    ref_pkg = load_json(refs[-1] / "package.json")
    pkg = {
        "name": EXT_NAME,
        "displayName": "Antigravity IDE 简体中文（Simplified Chinese）",
        "description": "Antigravity IDE 简体中文语言包 | 基于 VS Code 官方简体中文语言包 (MIT) + Antigravity 专有界面翻译。",
        "publisher": "antigravity-cn",
        "version": ext_version,
        "engines": {"vscode": ENGINE},
        "license": "MIT",
        "categories": ["Language Packs"],
        "contributes": {"localizations": ref_pkg["contributes"]["localizations"]},
    }
    (out_dir / "package.json").write_text(
        json.dumps(pkg, ensure_ascii=False, indent=2), encoding="utf-8")

    (out_dir / "README.md").write_text(
        "# Antigravity IDE 简体中文语言包\n\n"
        "由 antigravity-cn 项目离线构建。\n\n"
        "- 上游翻译: MS-CEINTL.vscode-language-pack-zh-hans (MIT)\n"
        "- Antigravity 专有界面翻译: 见项目 translations/antigravity-ext.i18n.json\n"
        "- 支持后续 IDE 版本升级: 未命中的键自动回退英文，可运行 scripts/update.py 重新生成\n",
        encoding="utf-8")
    shutil.copy2(ref / "languagepack.png", out_dir / "languagepack.png")

    # --- 打包 VSIX ---
    vsix = BUILD / f"{EXT_NAME}-{ext_version}.vsix"
    if vsix.exists():
        vsix.unlink()
    with zipfile.ZipFile(vsix, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml",
                   '<?xml version="1.0" encoding="utf-8"?>\n'
                   '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">\n'
                   '  <Default Extension="json" ContentType="application/json"/>\n'
                   '  <Default Extension="md" ContentType="text/markdown"/>\n'
                   '  <Default Extension="png" ContentType="image/png"/>\n'
                   '</Types>\n')
        for p in out_dir.rglob("*"):
            if p.is_file():
                z.write(p, "extension/" + str(p.relative_to(out_dir)))

    print(f"[4/5] VSIX 已生成: {vsix.name}  ({vsix.stat().st_size // 1024} KB, 版本 {ext_version})")
    print("[5/5] 完成。安装: python3 scripts/install.py")


if __name__ == "__main__":
    build()
