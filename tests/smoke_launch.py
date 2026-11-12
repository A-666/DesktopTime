# -*- coding: utf-8 -*-
"""真机启动冒烟：启动 app.py → 桌面抓屏 → 检查进程与日志 → 收尾。

仅在真实 Windows 桌面平台运行，不使用 offscreen。
"""
from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from PySide6.QtWidgets import QApplication  # noqa: E402

env = os.environ.copy()
env["QT_QPA_PLATFORM"] = "windows"
env["PYTHONPATH"] = os.pathsep.join(filter(None, [
    env.get("PYTHONPATH", ""), str(ROOT),
]))

app = QApplication([])
proc = subprocess.Popen(
    [sys.executable, str(ROOT / "app.py")],
    cwd=str(ROOT), env=env,
    stdout=subprocess.PIPE, stderr=subprocess.PIPE,
)
time.sleep(4.5)
alive = proc.poll() is None

shot_path = Path(os.environ.get("TEMP", ".")) / "dt_smoke.png"
try:
    pm = app.primaryScreen().grabWindow(0)
    ok = pm.save(str(shot_path))
    print(f"SCREENSHOT {shot_path} {pm.width()}x{pm.height()} saved={ok}")
except Exception as exc:
    print(f"SCREENSHOT FAILED {exc}")

print(f"PROCESS_ALIVE {alive}  (pid={proc.pid})")
log = Path(os.environ.get("APPDATA", ".")) / "DesktopTime" / "logs" / "desktoptime.log"
if log.exists():
    tail = log.read_text(encoding="utf-8", errors="replace").splitlines()[-25:]
    print("---- LOG TAIL ----")
    print("\n".join(tail))
else:
    print("LOG MISSING", log)

proc.terminate()
try:
    proc.wait(timeout=6)
except subprocess.TimeoutExpired:
    proc.kill()
    proc.wait(timeout=3)
out = proc.stdout.read().decode("utf-8", errors="replace")
err = proc.stderr.read().decode("utf-8", errors="replace")
print("---- STDOUT ----")
print(out[-800:] or "(empty)")
print("---- STDERR ----")
print(err[-2000:] or "(empty)")
