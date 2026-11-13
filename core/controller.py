# -*- coding: utf-8 -*-
"""应用编排：唯一真源、即时生效链路、方案切换、撤销、刷新节拍。"""
from __future__ import annotations

import copy
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
from .settings import (Settings, clamp_scope, defaults, normalize_monitor_entry,
                       now_iso)

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
    editTargetChanged = Signal(int)        # 03 / 04 页切换了「正在编辑的显示器」

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
        # 避免「配置字体名 ≠ 实际渲染字体」（旧配置 / 换机器场景）。
        # 每屏的独立配置也要过一遍，否则换台机器只有一块屏会变成方框。
        styles = [self.settings.data["style"]]
        styles += [b["style"] for b in (self.settings.data.get("perMonitor") or {}).values()
                   if isinstance(b, dict) and isinstance(b.get("style"), dict)]
        font_fixed = False
        for st in styles:
            fam = str(st.get("font") or "")
            if fam and not QFontDatabase.hasFamily(fam):
                st["font"] = "Consolas"
                font_fixed = True
                store.log(f"字体 {fam} 未安装，已回落 Consolas", "WARN")
        if font_fixed:
            store.save_settings(self.settings.as_dict())

        # 旧版本切「科技/电子表」会把 style.background.enabled 写成 True，
        # 于是桌面上常驻一块半透明板。现在内置预设全无底色，这里迁移一次清掉。
        if not self.get("style.packRef") and self.get("style.background.enabled", False):
            self.settings.set("style.background.enabled", False)
            store.save_settings(self.settings.as_dict())
            store.log("已关闭历史遗留的背景板（内置预设不再使用背景）")

        self.profiles = ProfileManager()
        self.renderer = Renderer()
        self.monitors: list[Monitor] = enum_monitors()
        # 单屏模式：正在编辑的那台必须就是时钟所在的那台，否则 03 / 04 页在改
        # 一块根本没有时钟的屏，改完「没反应」。
        if not self.get("display.all", False):
            self.settings.set("display.editIndex", int(self.get("display.index", 0)))
        self.current_label = "当前配置"
        self.pack: dict = {}
        self._global_pack: dict = {}       # 全局那份；没有独立配置的屏走它
        self.pack_warnings: list[str] = []
        self._pack_cache: dict[str, dict] = {}     # 每屏独立样式包，按显示器序号缓存

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

    # 只有这两块能按显示器独立；时间格式、窗口行为、托盘等仍全局共享
    PER_MONITOR_PREFIXES = ("style.", "position.")

    def data(self) -> dict:
        return self.settings.as_dict()

    def edit_index(self) -> int:
        """03 / 04 页当前编辑的显示器序号（唯一主键）。"""
        try:
            return max(0, int(self.get("display.editIndex", 0)))
        except (TypeError, ValueError):
            return 0

    def _bucket_mode(self) -> bool:
        """是否真的按屏分家：只有「所有显示器同时显示」且确实有多台时才成立。

        单屏模式下渲染的是同一条配置，若此时也往 perMonitor 里写，会立刻出现
        「页面显示 A、桌面渲染 B」的分叉 —— 所以宁可让它继续写全局。
        """
        return bool(self.get("display.all", False)) and len(self.monitors) > 1

    def _route(self, index: int, create: bool = False) -> dict | None:
        """要写哪份配置：已有该屏的独立块就用它；允许新建时按需创建；否则写全局。"""
        bucket = self.monitor_bucket(index)
        if bucket is not None:
            return bucket
        if create and self._bucket_mode():
            return self._ensure_bucket(index)
        return None

    def monitor_bucket(self, index: int) -> dict | None:
        """取某台显示器自己的 style / position；None = 跟随全局。"""
        try:
            key = str(int(index))
        except (TypeError, ValueError):
            return None
        buckets = self.settings.data.get("perMonitor") or {}
        bucket = buckets.get(key)
        return bucket if isinstance(bucket, dict) else None

    def _ensure_bucket(self, index: int) -> dict:
        """第一次给某台屏单独设置：以「此刻看到的全局配置」为底，避免闪回出厂值。"""
        key = str(int(index))
        buckets = self.settings.data.setdefault("perMonitor", {})
        bucket = buckets.get(key)
        if not isinstance(bucket, dict):
            bucket = {"style": copy.deepcopy(self.settings.data["style"]),
                      "position": copy.deepcopy(self.settings.data["position"])}
            buckets[key] = bucket
            store.log(f"显示器 {int(index) + 1} 已建立独立配置")
        return bucket

    def _dig_bucket(self, bucket: dict, path: str, default: Any) -> Any:
        node: Any = bucket
        for key in path.split("."):
            if not isinstance(node, dict) or key not in node:
                return default
            node = node[key]
        return node

    def _assign_bucket(self, bucket: dict, path: str, value: Any) -> None:
        keys = path.split(".")
        node = bucket
        for key in keys[:-1]:
            node = node.setdefault(key, {})
        node[keys[-1]] = value
        clamp_scope(bucket["style"], bucket["position"])

    def get(self, path: str, default: Any = None) -> Any:
        if path.startswith(self.PER_MONITOR_PREFIXES):
            bucket = self.monitor_bucket(self.edit_index())
            if bucket is not None:
                return self._dig_bucket(bucket, path, default)
        return self.settings.get(path, default)

    def set(self, path: str, value: Any) -> None:
        if path == "display.all" and not value:
            # 关掉「所有显示器同时显示」后只剩一个窗口：让它落在正在编辑的那台屏上，
            # 否则会出现「页面在编辑 2 号屏、桌面却按 1 号屏渲染」的分叉
            self.settings.set("display.index", self.edit_index())
        self._write_silent(path, value)
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

    def _write_silent(self, path: str, value: Any, index: int | None = None) -> None:
        """只写不广播：一次交互要改多个字段时用，避免中途用旧值重排一遍。"""
        bucket = None
        if path.startswith(self.PER_MONITOR_PREFIXES):
            target = self.edit_index() if index is None else int(index)
            bucket = self._route(target, create=True)
        if bucket is not None:
            self._assign_bucket(bucket, path, value)
            self.settings.data["updatedAt"] = now_iso()
        else:
            self.settings.set(path, value)

    # ---- 每屏独立配置 ----

    def set_edit_index(self, index: int) -> None:
        """切换「正在编辑的显示器」：03 / 04 页随即换成该屏的样式与位置。"""
        try:
            index = max(0, int(index))
        except (TypeError, ValueError):
            return
        changed = index != self.edit_index()
        if changed:
            self.settings.set("display.editIndex", index)
        if not self.get("display.all", False) and int(self.get("display.index", 0)) != index:
            # 单屏模式下「编辑哪台」等于「时钟显示在哪台」，否则改的是一块看不见的屏
            self.settings.set("display.index", index)
            self.settingsChanged.emit("display.index", index)
            changed = True
        if not changed:
            return
        self._save_timer.start(150)
        # 这一页要显示的样式包跟着换人，但不重建时间窗口（各自渲染各自的包）
        self._resolve_pack()
        self._retune_timer()
        self.editTargetChanged.emit(index)

    def config_for(self, index: int) -> dict:
        """某台显示器实际生效的配置：全局打底，style / position 用该屏自己的覆盖。"""
        bucket = self.monitor_bucket(index)
        if bucket is None:
            return self.settings.data
        cfg = dict(self.settings.data)          # 浅拷贝即可：渲染层只读，改不动源头
        cfg["style"] = bucket["style"]
        cfg["position"] = bucket["position"]
        return cfg

    def pack_for(self, index: int) -> dict:
        """某台显示器实际生效的样式包（该屏可以引用不同的 .dtstyle）。"""
        bucket = self.monitor_bucket(index)
        if bucket is None:
            return self._global_pack
        key = str(int(index))
        cached = self._pack_cache.get(key)
        if cached is None:
            cached, warns, _notice = stylepack.resolve(
                {"style": bucket["style"]}, store.STYLES_DIR, BUILTIN_DIR)
            for w in warns:
                store.log(f"显示器 {int(index) + 1} 样式包: {w}", "WARN")
            self._pack_cache[key] = cached
        return cached

    def apply_style_to_all(self) -> None:
        """把当前编辑屏的样式 + 位置复制给其他所有屏。"""
        src_idx = self.edit_index()
        src = self.monitor_bucket(src_idx)
        if src is None:
            src = {"style": copy.deepcopy(self.settings.data["style"]),
                   "position": copy.deepcopy(self.settings.data["position"])}
        buckets = self.settings.data.setdefault("perMonitor", {})
        for m in self.monitors:
            if int(m.index) == src_idx:
                continue
            buckets[str(int(m.index))] = copy.deepcopy(src)
        self._pack_cache.clear()
        self._save_timer.start(150)
        self.settingsReplaced.emit()
        self.notice.emit(f"已把显示器 {src_idx + 1} 的样式与位置应用到全部显示器")

    def set_edit_monitor_standalone(self, enabled: bool) -> None:
        """勾上 / 取消 03 / 04 页的「本屏单独设置」复选框。

        勾上 = 以此刻生效的配置为底，为这台屏存一份，之后改动只影响它；
        取消 = 删掉这一份，改回和其他显示器一样。
        """
        idx = self.edit_index()
        if not enabled:
            self.reset_edit_monitor()
            return
        if not self._bucket_mode():
            # 单屏模式下只有一份配置，分家会立刻出现「页面显示 A、桌面渲染 B」
            self.notice.emit("单屏模式下只有一份配置，先在 01 页打开「所有显示器同时显示」")
            return
        if self.monitor_bucket(idx) is not None:
            return
        self._ensure_bucket(idx)
        self._pack_cache.pop(str(idx), None)
        self._save_timer.start(150)
        self.refresh_pack()          # 编辑目标的样式包换成了它自己那份
        self.settingsReplaced.emit()
        self.notice.emit(f"显示器 {idx + 1} 已开启单独设置")

    def reset_edit_monitor(self) -> None:
        """放弃该屏的单独设置，改回和其他显示器一样。"""
        idx = self.edit_index()
        buckets = self.settings.data.setdefault("perMonitor", {})
        if buckets.pop(str(idx), None) is None:
            self.notice.emit(f"显示器 {idx + 1} 本来就没有单独设置")
            return
        self._pack_cache.pop(str(idx), None)
        self._save_timer.start(150)
        self.settingsReplaced.emit()
        self.notice.emit(f"显示器 {idx + 1} 已取消单独设置，改回和其他显示器一样")

    def set_position_preset(self, key: str) -> None:
        """点九宫格：回到预设模式。预设锚点永久固定，不吃任何偏移。"""
        self._write_silent("position.preset", key)
        self._write_silent("position.mode", "preset")
        self.profiles.invalidate("位置预设已切换")
        self._save_timer.start(150)
        self.settingsChanged.emit("position.preset", key)

    def set_custom_position(self, index: int, dx: int, dy: int) -> None:
        """自定义落点（逻辑像素，相对该屏工作区左上角）。

        一次性写完显示器 / 坐标 / 模式再广播一次 —— 逐个 set() 会中途用旧坐标
        重排一遍，窗口会先跳一下再落位。
        """
        idx = int(index)
        self._write_silent("display.index", idx)
        self._write_silent("position.custom.x", int(dx), idx)
        self._write_silent("position.custom.y", int(dy), idx)
        self._write_silent("position.mode", "custom", idx)
        self.profiles.invalidate("自定义位置已更新")
        self._save_timer.start(150)
        self.settingsChanged.emit("position.custom", (int(dx), int(dy)))
        # 拖动哪台屏，03 / 04 页就跟着看哪台：否则「更新位置」后还要手动切屏才对得上
        if self._bucket_mode() and idx != self.edit_index():
            self.settings.set("display.editIndex", idx)
            self._resolve_pack()
            self._retune_timer()
            self.editTargetChanged.emit(idx)

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

    def _resolve_pack(self) -> None:
        """解析样式包。

        `self.pack` 是「当前编辑那台屏」的包（页面标签、节拍看它）；
        `self._global_pack` 是全局那份（没有独立配置的屏一律走它）。
        两者分开，才不会出现「没定制过的屏被别人的预设带跑」。
        """
        self._pack_cache.clear()          # 样式一改，每屏缓存的包全部作废
        self._global_pack, _gw, _gn = stylepack.resolve(
            self.settings.data, store.STYLES_DIR, BUILTIN_DIR)
        if self.monitor_bucket(self.edit_index()) is None:
            self.pack, self.pack_warnings, notice = self._global_pack, _gw, _gn
        else:
            self.pack, self.pack_warnings, notice = stylepack.resolve(
                self.config_for(self.edit_index()), store.STYLES_DIR, BUILTIN_DIR
            )
        for w in self.pack_warnings:
            store.log(f"样式包: {w}", "WARN")
        if notice:
            self.notice.emit(notice)

    def refresh_pack(self) -> None:
        self._resolve_pack()
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
        # 编辑目标也要跟着钳制，否则拔掉显示器后 03 / 04 页在编辑一块不存在的屏
        if self.edit_index() >= len(self.monitors):
            self.settings.set("display.editIndex", max(0, len(self.monitors) - 1))
            self.editTargetChanged.emit(self.edit_index())
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
        if not has_effects:
            # 别的屏可能挂着特效包：只要有一台要高频，整体就高频，
            # 否则那台屏的特效会按 1fps 抖成幻灯片
            has_effects = any(bool(self.pack_for(int(m.index)).get("effects"))
                              for m in self.monitors)
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
