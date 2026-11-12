# -*- coding: utf-8 -*-
"""应用编排：唯一真源、即时生效链路、方案切换、撤销、刷新节拍。"""
from __future__ import annotations

import sys
import time
from pathlib import Path
from typing import Any

from PySide6.QtCore import QObject, QTimer, QTime, Signal
from PySide6.QtGui import QFontDatabase

from . import store, stylepack
from .monitors import Monitor, enum_monitors, set_dpi_awareness
from .profiles import ProfileManager
from .renderer import Renderer
from .settings import Settings, defaults, now_iso

# 打包后资源随 bundle 解压到 sys._MEIPASS；源码运行时按工程根目录定位
_BASE_DIR = (Path(sys._MEIPASS) if getattr(sys, "frozen", False)
             else Path(__file__).resolve().parent.parent)
BUILTIN_DIR = _BASE_DIR / "resources" / "styles" / "builtin"
RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
RUN_NAME = "DesktopTime"


class AppController(QObject):
    settingsChanged = Signal(str, object)   # path, value
    settingsReplaced = Signal()             # 整组切换 / 撤销 / 重置
    profilesChanged = Signal()
    undoStateChanged = Signal(bool)
    monitorsChanged = Signal()
    packChanged = Signal()
    dragRequested = Signal()                # 04 页「自定义拖动」
    positionSyncRequested = Signal()        # 04 页「更新位置」：把当前落点记成自定义位置
    identifyRequested = Signal()            # 01 页「识别显示器」
    rebuildRequested = Signal()             # 显式重建时间窗口
    notice = Signal(str)                    # 一次性提示（样式包回落等）
    tick = Signal(int)                     # now_ms，所有时钟窗口共享
    closeBehaviorChanged = Signal()

    def __init__(self, parent=None, dpi_mode: str | None = None):
        super().__init__(parent)
        store.ensure_dirs()
        # 由 app.py 在 QApplication 之前设置后传入，避免重复调用 DPI API
        self.dpi_mode = dpi_mode or set_dpi_awareness()
        raw, error = store.load_raw_settings()
        if error:
            store.log(error, "WARN")
        self.settings = Settings(raw)
        if raw is None:
            store.save_settings(self.settings.as_dict())
        for w in self.settings.warnings:
            store.log(f"配置归一: {w}", "WARN")

        # 字体归一：配置里存了本机未安装的字体时回落 Consolas，
        # 避免「配置字体名 ≠ 实际渲染字体」（旧配置 / 换机器场景）
        fam = str(self.get("style.font") or "")
        if fam and not QFontDatabase.hasFamily(fam):
            self.settings.set("style.font", "Consolas")
            store.save_settings(self.settings.as_dict())
            store.log(f"字体 {fam} 未安装，已回落 Consolas", "WARN")

        # 旧版本切「科技/电子表」会把 style.background.enabled 写成 True，
        # 于是桌面上常驻一块半透明板。现在内置预设全无底色，这里迁移一次清掉。
        if not self.get("style.packRef") and self.get("style.background.enabled", False):
            self.settings.set("style.background.enabled", False)
            store.save_settings(self.settings.as_dict())
            store.log("已关闭历史遗留的背景板（内置预设不再使用背景）")

        self.profiles = ProfileManager()
        self.renderer = Renderer()
        self.monitors: list[Monitor] = enum_monitors()
        self.current_label = "当前配置"
        self.pack: dict = {}
        self.pack_warnings: list[str] = []

        # 定时器必须先于 refresh_pack 建立：后者会按特效有无调整节拍
        self._save_timer = QTimer(self)
        self._save_timer.setSingleShot(True)
        self._save_timer.timeout.connect(self._flush_settings)
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._on_tick)
        self._aligned = False

        self.refresh_pack()
        # 重启后回滚点一律失效
        self.profiles.invalidate("应用重启")
        self.start_clock()

    # ---- 配置读写 ----

    def data(self) -> dict:
        return self.settings.as_dict()

    def get(self, path: str, default: Any = None) -> Any:
        return self.settings.get(path, default)

    def set(self, path: str, value: Any) -> None:
        self.settings.set(path, value)
        if self.profiles.invalidate(f"设置项 {path} 已改动"):
            self.undoStateChanged.emit(False)
        self._save_timer.start(150)
        if path in ("style.preset", "style.packRef", "style.decorations", "style.effects"):
            self.refresh_pack()
        if path == "display.index" or path == "display.all":
            pass  # 窗口定位由 rebuild 统一处理
        if path == "app.autoStart":
            self.apply_autostart(bool(value))
        self.settingsChanged.emit(path, value)

    def set_position_preset(self, key: str) -> None:
        """点九宫格：回到预设模式。预设锚点永久固定，不吃任何偏移。"""
        self.settings.set("position.preset", key)
        self.settings.set("position.mode", "preset")
        self.profiles.invalidate("位置预设已切换")
        self._save_timer.start(150)
        self.settingsChanged.emit("position.preset", key)

    def set_custom_position(self, index: int, dx: int, dy: int) -> None:
        """自定义落点（逻辑像素，相对该屏工作区左上角）。

        一次性写完显示器 / 坐标 / 模式再广播一次 —— 逐个 set() 会中途用旧坐标
        重排一遍，窗口会先跳一下再落位。
        """
        self.settings.set("display.index", int(index))
        self.settings.set("position.custom.x", int(dx))
        self.settings.set("position.custom.y", int(dy))
        self.settings.set("position.mode", "custom")
        self.profiles.invalidate("自定义位置已更新")
        self._save_timer.start(150)
        self.settingsChanged.emit("position.custom", (int(dx), int(dy)))

    def _flush_settings(self) -> None:
        self.settings.data["updatedAt"] = now_iso()
        store.save_settings(self.settings.as_dict())
        store.log("settings.json 已落盘")

    def flush_pending(self) -> None:
        """退出前把去抖窗口内（150ms）还没写的改动立刻落盘。"""
        if self._save_timer.isActive():
            self._save_timer.stop()
            self._flush_settings()
            store.log("退出前补写 1 次配置")

    def replace_all(self, raw: Any, label: str = "当前配置") -> None:
        warnings = self.settings.replace(raw)
        for w in warnings:
            store.log(f"方案载入: {w}", "WARN")
        self.current_label = label
        self.refresh_pack()
        self._flush_settings()
        self.settingsReplaced.emit()

    def refresh_pack(self) -> None:
        self.pack, self.pack_warnings, notice = stylepack.resolve(
            self.settings.as_dict(), store.STYLES_DIR, BUILTIN_DIR
        )
        for w in self.pack_warnings:
            store.log(f"样式包: {w}", "WARN")
        if notice:
            self.notice.emit(notice)
        self.packChanged.emit()
        self._retune_timer()

    # ---- 样式 ----

    def set_preset(self, name: str) -> None:
        """切换预设只换 text / decorations / effects，不动格式、位置、显示器。

        注意：**不再联动「背景板」开关**。内置预设一律不画底色，若这里按预设值
        去写 style.background.enabled，用户在深色壁纸上会凭空多出一块半透明灰底
        （正是「刚开始没有背景、过一秒冒出来」的来源：最后一步 set 才把开关打开）。
        """
        preset = stylepack.get_builtin(name)
        self.set("style.preset", name)
        self.set("style.packRef", "")
        self.set("style.decorations", [])
        self.set("style.effects", [])
        self.set("style.font", preset["text"].get("font", self.get("style.font")))
        self.set("style.size", preset["text"].get("size", self.get("style.size")))
        self.set("style.weight", preset["text"].get("weight", self.get("style.weight")))
        self.set("style.color", preset["text"].get("color", self.get("style.color")))

    def import_pack(self, path: str) -> tuple[bool, str]:
        p = Path(path)
        try:
            pack, warnings = stylepack.load_pack(p)
        except (OSError, ValueError) as exc:
            return False, f"样式包加载失败：{exc}"
        # 复制到用户样式目录，配置只存引用
        dest = store.STYLES_DIR / p.name
        store.atomic_write_json(dest, pack)
        self.set("style.packRef", p.name)
        msg = f"已载入样式包「{pack.get('name')}」"
        if warnings:
            msg += f"（{len(warnings)} 条校验提示）"
        return True, msg

    def clear_pack(self) -> None:
        self.set("style.packRef", "")
        self.set("style.decorations", [])
        self.set("style.effects", [])

    def push_recent_color(self, color: str) -> None:
        recent = list(self.get("style.recentColors", []) or [])
        recent = [c for c in recent if c.upper() != color.upper()]
        recent.insert(0, color.upper())
        self.set("style.recentColors", recent[:4])

    # ---- 方案 / 撤销 ----

    def save_profile(self, name: str) -> str:
        self.profiles.save(name, self.settings.as_dict())
        self.current_label = name
        self.profilesChanged.emit()
        return name

    def duplicate_profile(self, name: str) -> str:
        new_name = self.profiles.duplicate(name)
        self.profilesChanged.emit()
        return new_name

    def rename_profile(self, old: str, new: str) -> str:
        target = self.profiles.rename(old, new)
        self.profilesChanged.emit()
        self.undoStateChanged.emit(self.profiles.can_undo())
        return target

    def delete_profile(self, name: str) -> None:
        self.profiles.delete(name)
        self.profilesChanged.emit()
        self.undoStateChanged.emit(self.profiles.can_undo())

    def switch_profile(self, name: str) -> bool:
        try:
            data, warnings = self.profiles.switch(name, self.settings.as_dict(), self.current_label)
        except (OSError, ValueError) as exc:
            store.log(f"切换方案失败: {exc}", "ERROR")
            self.notice.emit(f"方案「{name}」读取失败：{exc}")
            return False
        self.replace_all(data, label=name)
        self.undoStateChanged.emit(True)
        self.notice.emit(f"已切换到「{name}」")
        return True

    def undo(self) -> bool:
        result = self.profiles.undo()
        if result is None:
            return False
        data, _ = result
        self.replace_all(data, label="撤销后的配置")
        self.undoStateChanged.emit(False)
        self.notice.emit("已撤销上一次切换")
        return True

    def undo_info(self) -> dict | None:
        return self.profiles.undo_info()

    def can_undo(self) -> bool:
        return self.profiles.can_undo()

    def reset_defaults(self) -> None:
        self.replace_all(defaults(), label="当前配置")
        self.undoStateChanged.emit(False)
        self.notice.emit("全部设置已恢复为出厂值（方案与样式包保留）")

    # ---- 显示器 ----

    def refresh_monitors(self) -> None:
        self.monitors = enum_monitors()
        idx = int(self.get("display.index", 0))
        if idx >= len(self.monitors):
            store.log("目标显示器已拔出，回落主屏", "WARN")
            primary = next((m for m in self.monitors if m.primary), None)
            self.settings.set("display.index", primary.index if primary else 0)
        self.settings.set("display.layout", [m.as_dict() for m in self.monitors])
        self.monitorsChanged.emit()
        self.settingsChanged.emit("display.layout", self.get("display.layout"))

    # ---- 时钟节拍（全局唯一 QTimer） ----

    def start_clock(self) -> None:
        if self._aligned:
            self._retune_timer()
            return
        self._aligned = True
        delay = 1000 - QTime.currentTime().msec()
        QTimer.singleShot(max(30, delay), self._aligned_start)

    def _aligned_start(self) -> None:
        self._on_tick()
        self._retune_timer()

    def _retune_timer(self) -> None:
        if not hasattr(self, "_timer"):
            return
        has_effects = bool(self.pack.get("effects"))
        interval = 33 if has_effects else 1000   # ≤30fps
        if self._timer.interval() != interval or not self._timer.isActive():
            self._timer.setInterval(interval)
            self._timer.start(interval)

    def _on_tick(self) -> None:
        self.tick.emit(int(time.monotonic() * 1000))

    # ---- 开机自启 ----

    def apply_autostart(self, enabled: bool) -> None:
        try:
            import winreg
            target = f'"{Path(sys.executable).resolve()}"'
            if getattr(sys, "frozen", False):
                cmd = target
            else:
                cmd = f'{target} "{Path(sys.argv[0]).resolve()}"'
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0,
                                winreg.KEY_SET_VALUE | winreg.KEY_READ) as key:
                if enabled:
                    winreg.SetValueEx(key, RUN_NAME, 0, winreg.REG_SZ, cmd)
                else:
                    try:
                        winreg.DeleteValue(key, RUN_NAME)
                    except FileNotFoundError:
                        pass
                # 写后读回校验
                try:
                    actual, _ = winreg.QueryValueEx(key, RUN_NAME)
                    if enabled and actual != cmd:
                        store.log("开机自启注册表读回不一致", "WARN")
                except FileNotFoundError:
                    if enabled:
                        store.log("开机自启注册表写入后未读到", "WARN")
        except OSError as exc:
            store.log(f"开机自启设置失败: {exc}", "WARN")
            self.notice.emit(f"开机自启设置失败：{exc}")

    def close_requested(self) -> str:
        return str(self.get("tray.onClose", "ask"))
