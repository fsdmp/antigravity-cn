#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
zh_hub.py — Antigravity.app 管理器（Hub）中文界面启动器

原理:
  管理器 Hub UI 是本地语言服务器 (language_server) 在 https://127.0.0.1:<动态端口>
  上托管的 Web 应用。官方 Electron 主进程显式兼容 --remote-debugging-port 开关
  (main.js 中检测该开关时会保留 active-port 文件)，因此本工具:

    1. 以 --remote-debugging-port=0 (随机回环端口) 启动管理器;
    2. 从 stderr 读取 "DevTools listening on ws://127.0.0.1:PORT/...";
    3. 通过 CDP 对每个 Hub 页面 (https://127.0.0.1:*) 注入翻译脚本
       (Page.addScriptToEvaluateOnNewDocument, 对后续 reload/导航持续生效);
    4. 后台轮询新窗口, 逐一注入。

  /Applications 内零字节改动 —— 签名、ElectronAsarIntegrity、自动更新全部无感。
  退出本工具或关闭管理器即恢复原状, 无任何持久化状态需要"卸载"。

用法:
  python3 zh_hub.py                 # 前台运行 (终端保持打开)
  python3 zh_hub.py --background    # 后台守护 (日志: /tmp/antigravity-cn-hub/)
  python3 zh_hub.py --stop          # 停止后台守护
  python3 zh_hub.py --relaunch      # 先退出正在运行的管理器, 再以注入模式启动
  python3 zh_hub.py --status        # 查看守护状态

注意:
  - 管理器已在运行时无法注入 (单实例锁): 请先退出, 或使用 --relaunch。
  - 退出确认: 管理器有代理在运行时退出会弹确认框, 需手动确认。
"""

import argparse
import json
import os
import queue
import re
import shutil
import signal
import socket
import struct
import subprocess
import sys
import threading
import time
from pathlib import Path

PROJECT = Path(__file__).resolve().parent.parent.parent
INJECT_JS = Path(__file__).resolve().parent / "inject.js"
HUB_DICT = PROJECT / "translations" / "hub.i18n.json"

APP_BIN = "/Applications/Antigravity.app/Contents/MacOS/Antigravity"
APP_NAME = "Antigravity"
RUNTIME_DIR = Path("/tmp/antigravity-cn-hub")
STDERR_LOG = RUNTIME_DIR / "launch-stderr.log"
DAEMON_LOG = RUNTIME_DIR / "daemon.log"
PID_FILE = RUNTIME_DIR / "daemon.pid"
HUB_URL_RE = re.compile(r"^https://127\.0\.0\.1:\d+")


# ============================================================
# 极简 RFC6455 WebSocket 客户端 (纯 stdlib, 足够承载 CDP)
# ============================================================

class MiniWS:
    def __init__(self, host, port, path):
        self.sock = socket.create_connection((host, port), timeout=10)
        import base64
        key = base64.b64encode(os.urandom(16)).decode()
        req = (f"GET {path} HTTP/1.1\r\nHost: {host}:{port}\r\n"
               "Upgrade: websocket\r\nConnection: Upgrade\r\n"
               f"Sec-WebSocket-Key: {key}\r\nSec-WebSocket-Version: 13\r\n\r\n")
        self.sock.sendall(req.encode())
        buf = b""
        while b"\r\n\r\n" not in buf:
            chunk = self.sock.recv(4096)
            if not chunk:
                raise ConnectionError("handshake EOF")
            buf += chunk
        head, _, rest = buf.partition(b"\r\n\r\n")
        if b"101" not in head.split(b"\r\n")[0]:
            raise ConnectionError(f"upgrade refused: {head[:120]!r}")
        self._buf = rest
        self._id = 0
        self._lock = threading.Lock()
        self._resp = {}
        self._events = queue.Queue()
        self._alive = True
        self._rx = threading.Thread(target=self._recv_loop, daemon=True)
        self._rx.start()

    def _send_frame(self, opcode, payload):
        mask = os.urandom(4)
        n = len(payload)
        if n < 126:
            head = struct.pack("!BB", 0x80 | opcode, 0x80 | n)
        elif n < 65536:
            head = struct.pack("!BBH", 0x80 | opcode, 0x80 | 126, n)
        else:
            head = struct.pack("!BBQ", 0x80 | opcode, 0x80 | 127, n)
        masked = bytes(b ^ mask[i % 4] for i, b in enumerate(payload))
        with self._lock:
            self.sock.sendall(head + mask + masked)

    def _read_exact(self, n):
        data = self._buf
        self._buf = b""
        while len(data) < n:
            chunk = self.sock.recv(65536)
            if not chunk:
                raise ConnectionError("EOF")
            data += chunk
        self._buf = data[n:]
        return data[:n]

    def _recv_frame(self):
        b1, b2 = self._read_exact(2)
        fin, opcode = b1 & 0x80, b1 & 0x0F
        n = b2 & 0x7F
        if n == 126:
            n = struct.unpack("!H", self._read_exact(2))[0]
        elif n == 127:
            n = struct.unpack("!Q", self._read_exact(8))[0]
        return fin, opcode, (self._read_exact(n) if n else b"")

    def _recv_loop(self):
        frags = []
        while self._alive:
            try:
                fin, opcode, payload = self._recv_frame()
            except Exception:
                self._alive = False
                self._events.put(None)
                return
            if opcode == 0x9:                       # ping -> pong
                self._send_frame(0xA, payload)
                continue
            if opcode == 0x8:
                self._alive = False
                self._events.put(None)
                return
            if opcode == 0x0 and frags:
                frags.append(payload)
            else:
                frags = [payload]
            if not fin:
                continue
            data = b"".join(frags)
            frags = []
            try:
                msg = json.loads(data.decode("utf-8"))
            except Exception:
                continue
            if "id" in msg:
                self._resp[msg["id"]] = msg
            else:
                self._events.put(msg)

    def call(self, method, params=None, session_id=None, timeout=15):
        with self._lock:
            self._id += 1
            mid = self._id
        msg = {"id": mid, "method": method, "params": params or {}}
        if session_id:
            msg["sessionId"] = session_id
        self._send_frame(0x1, json.dumps(msg).encode())
        deadline = time.time() + timeout
        while time.time() < deadline:
            if mid in self._resp:
                return self._resp.pop(mid)
            if not self._alive:
                raise ConnectionError("ws closed")
            time.sleep(0.01)
        raise TimeoutError(method)

    @property
    def alive(self):
        return self._alive

    def close(self):
        self._alive = False
        try:
            self._send_frame(0x8, b"")
        except Exception:
            pass
        try:
            self.sock.close()
        except Exception:
            pass


# ============================================================
# 注入守护
# ============================================================

def load_inject_script() -> str:
    if not HUB_DICT.exists():
        sys.exit(f"错误: 词典不存在 {HUB_DICT}\n请先运行 scripts/manager/build_hub_dict.py")
    dict_json = HUB_DICT.read_text(encoding="utf-8")
    tpl = INJECT_JS.read_text(encoding="utf-8")
    return tpl.replace("__DICT_JSON__", dict_json)


class HubInjector:
    POLL_INTERVAL = 2.0

    def __init__(self, inject_script: str, log=print):
        self.ws = None
        self.inject_script = inject_script
        self.log = log
        self.attached = {}      # targetId -> sessionId
        self._stop = threading.Event()

    def _inject_target(self, tid: str):
        try:
            att = self.ws.call("Target.attachToTarget", {"targetId": tid, "flatten": True})
            sid = att["result"]["sessionId"]
            self.ws.call("Page.enable", session_id=sid)
            self.ws.call("Page.addScriptToEvaluateOnNewDocument",
                         {"source": self.inject_script}, session_id=sid, timeout=30)
            # 已加载的页面立即执行一遍 (addScript... 只对之后的文档生效)
            r = self.ws.call("Runtime.evaluate", {"expression": self.inject_script},
                             session_id=sid, timeout=30)
            if "exceptionDetails" in r.get("result", {}):
                self.log(f"  [!] 注入执行异常 target={tid[:8]}…")
                return
            self.attached[tid] = sid
            self.log(f"  [✓] 已注入: target {tid[:8]}…")
        except Exception as e:
            self.log(f"  [!] 注入失败 target={tid[:8]}…: {e}")

    def _poll_targets(self):
        try:
            infos = self.ws.call("Target.getTargets")["result"]["targetInfos"]
        except Exception as e:
            self.log(f"  [!] 轮询失败: {e}")
            return
        live = set()
        for t in infos:
            tid = t["targetId"]
            if t["type"] != "page" or not HUB_URL_RE.match(t["url"]):
                continue
            live.add(tid)
            if tid not in self.attached:
                self.log(f"  发现 Hub 窗口: {t['url']}")
                self._inject_target(tid)
        # 清理已销毁的 target
        for tid in list(self.attached):
            if tid not in live:
                del self.attached[tid]

    def run(self, ws_url: str):
        m = re.match(r"ws://([^:/]+):(\d+)(/.+)", ws_url)
        self.ws = MiniWS(m.group(1), int(m.group(2)), m.group(3))
        ver = self.ws.call("Browser.getVersion")
        prod = ver["result"].get("product", "?")
        self.log(f"已连接 CDP: {prod}")
        self.ws.call("Target.setDiscoverTargets", {"discover": True})

        self._poll_targets()
        if not self.attached:
            # LS 端口就绪前窗口可能还没出现, 多等几轮
            self.log("等待 Hub 窗口出现 (语言服务器启动中)…")
            for _ in range(30):
                if self._stop.wait(1.0):
                    return
                self._poll_targets()
                if self.attached:
                    break

        self.log("注入完成, 进入守护模式 (监听新窗口; Ctrl+C 退出)…")
        while not self._stop.is_set():
            if not self.ws.alive:
                self.log("管理器已退出, 守护结束")
                return
            self._stop.wait(self.POLL_INTERVAL)
            self._poll_targets()

    def stop(self):
        self._stop.set()
        if self.ws:
            self.ws.close()


# ============================================================
# 启动 / 进程管理
# ============================================================

def manager_running() -> bool:
    # 不能用 $ 锚定: 以调试参数启动的实例命令行后面带参数
    r = subprocess.run(["pgrep", "-f", re.escape(APP_BIN)],
                       capture_output=True, text=True)
    return r.returncode == 0


def quit_manager(timeout=15.0):
    subprocess.run(["osascript", "-e",
                    f'tell application "{APP_NAME}" to quit'], capture_output=True)
    deadline = time.time() + timeout
    while time.time() < deadline:
        if not manager_running():
            return True
        time.sleep(0.3)
    return False


def launch_with_debug() -> str:
    """启动管理器并返回浏览器级 ws url"""
    RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
    err = open(STDERR_LOG, "wb")
    try:
        proc = subprocess.Popen([APP_BIN, "--remote-debugging-port=0"], stderr=err)
    finally:
        err.close()
    print(f"已启动管理器 (pid {proc.pid}), 等待调试端口…")
    deadline = time.time() + 30
    while time.time() < deadline:
        try:
            text = STDERR_LOG.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            text = ""
        m = re.search(r"DevTools listening on (ws://127\.0\.0\.1:\d+/devtools/browser/\S+)", text)
        if m:
            return m.group(1)
        if proc.poll() is not None:
            sys.exit("错误: 管理器进程意外退出 (可能已有实例在运行)")
        time.sleep(0.2)
    sys.exit("错误: 30 秒内未捕获到 DevTools 端口")


def daemon_pid():
    if PID_FILE.exists():
        try:
            pid = int(PID_FILE.read_text().strip())
            os.kill(pid, 0)
            return pid
        except Exception:
            pass
    return None


def cmd_stop():
    pid = daemon_pid()
    if not pid:
        print("没有正在运行的后台守护")
        return
    os.kill(pid, signal.SIGTERM)
    print(f"已停止后台守护 (pid {pid})")


def cmd_status():
    pid = daemon_pid()
    if pid:
        print(f"后台守护运行中 (pid {pid})")
    elif manager_running():
        print("管理器在运行, 但未通过本工具启动 (无注入)")
    else:
        print("未运行")


def serve_forever(ws_url: str, inject_script: str):
    try:
        sys.stdout.reconfigure(line_buffering=True)
        sys.stderr.reconfigure(line_buffering=True)
    except Exception:
        pass
    RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
    PID_FILE.write_text(str(os.getpid()))
    inj = HubInjector(inject_script)
    signal.signal(signal.SIGTERM, lambda *_: inj.stop())

    def hup(*_):
        inj.stop()
    signal.signal(signal.SIGINT, hup)

    try:
        inj.run(ws_url)
    finally:
        PID_FILE.unlink(missing_ok=True)
        inj.stop()


def main():
    ap = argparse.ArgumentParser(description="Antigravity 管理器中文界面启动器 (CDP 注入, 零文件修改)")
    ap.add_argument("--background", action="store_true", help="后台守护运行")
    ap.add_argument("--relaunch", action="store_true", help="先退出正在运行的管理器再启动")
    ap.add_argument("--stop", action="store_true", help="停止后台守护")
    ap.add_argument("--status", action="store_true", help="查看状态")
    ap.add_argument("--ws-url", help=argparse.SUPPRESS)       # 内部: --background 子进程用
    ap.add_argument("--background-child", action="store_true",
                    help=argparse.SUPPRESS)                   # 内部: 标记子进程
    args = ap.parse_args()

    # --background 拉起的子进程: 直接服务, 跳过启动/检查逻辑
    if args.ws_url:
        serve_forever(args.ws_url, load_inject_script())
        return

    if args.status:
        return cmd_status()
    if args.stop:
        return cmd_stop()

    inject_script = load_inject_script()

    if manager_running():
        if args.relaunch:
            print("正在退出管理器 (若有代理在运行请留意确认框)…")
            if not quit_manager():
                sys.exit("错误: 管理器未能退出")
            time.sleep(1.0)
        else:
            sys.exit("错误: 管理器已在运行 (单实例锁, 无法注入)。\n"
                     "  先手动退出 Antigravity 再运行本工具, 或: python3 zh_hub.py --relaunch")

    ws_url = launch_with_debug()
    print(f"调试端口就绪: {ws_url}")

    if args.background:
        RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
        logf = open(DAEMON_LOG, "ab", buffering=0)
        logf.write(f"\n===== {time.strftime('%Y-%m-%d %H:%M:%S')} 启动 =====\n".encode())
        subprocess.Popen(
            [sys.executable, str(Path(__file__).resolve()),
             "--background-child", "--ws-url", ws_url],
            stdout=logf, stderr=logf, stdin=subprocess.DEVNULL,
            start_new_session=True)
        print(f"后台守护已拉起, 日志: {DAEMON_LOG}")
        print("停止: python3 zh_hub.py --stop")
        return

    serve_forever(ws_url, inject_script)


if __name__ == "__main__":
    main()
