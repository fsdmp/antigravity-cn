#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
fetch_reference.py — 下载官方简体中文语言包（MIT 许可）作为翻译底料

用法: python3 scripts/fetch_reference.py [版本号...]
示例: python3 scripts/fetch_reference.py 1.106.0 1.108.0
不传参数则下载当前最新的两个相邻版本。
"""

import json
import subprocess
import sys
import urllib.request
import zipfile
from pathlib import Path

EXT = "MS-CEINTL.vscode-language-pack-zh-hans"
REF = Path(__file__).resolve().parent.parent / "reference"
API = f"https://open-vsx.org/api/{EXT}"


def fetch(version: str):
    dest = REF / f"zhpack-{version}"
    if dest.exists():
        print(f"已存在: {dest.name}")
        return
    vsix_path = REF / f"{EXT}-{version}.vsix"
    url = f"{API}/{version}/file/{EXT}-{version}.vsix"
    print(f"下载 {url}")
    urllib.request.urlretrieve(url, vsix_path)
    with zipfile.ZipFile(vsix_path) as z:
        z.extractall(REF / f"_tmp_{version}")
    inner = REF / f"_tmp_{version}" / "extension"
    inner.rename(dest)
    (REF / f"_tmp_{version}").rmdir()
    vsix_path.unlink()
    print(f"已解包 -> {dest}")


def latest_two():
    with urllib.request.urlopen(API) as r:
        meta = json.load(r)
    versions = sorted(meta["allVersions"], key=lambda v: [int(x) for x in v.split(".")])
    return [v for v in versions if not v.startswith("0")][-2:]


if __name__ == "__main__":
    args = sys.argv[1:]
    for v in (args or latest_two()):
        fetch(v)
