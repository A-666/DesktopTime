# -*- coding: utf-8 -*-
"""桌面时间无边框窗口：离屏贴图、九宫格定位、拖动、显示器角标。"""
from __future__ import annotations

from datetime import datetime

from PySide6.QtCore import QPoint, Qt
from PySide6.QtGui import QColor, QFont, QImage, QPainter
from PySide6.QtWidgets import QWidget

from core import store
from .screens import build_screen_map


class ClockWindow(QWidget):
    def __init__(self, controller, monitor_index: int | None = None):
        super().__init__()
        self.controller = controller
        self.monitor_index = monitor_index
        self._image: QImage | None = None
        self._drag_mode = False
        self._drag_offset: QPoint | None = None
        self._now_ms = 0
        self._dpr = 1.0

        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        self.setMouseTracking(False)
        self._apply_flags()

        controller.tick.connect(self.on_tick)
        controller.settingsChanged.connect(self.on_settings_changed)
        controller.settingsReplaced.connect(self.rebuild)
        controller.monitorsChanged.connect(self.rebuild)
        controller.packChanged.connect(self.rebuild)
        self._dpr = self._resolve_dpr()
        self.on_tick(0)
        self.rebuild()
        self.show()

    def _apply_flags(self) -> None:
        cfg = self.cfg()
        flags = Qt.WindowType.FramelessWindowHint | Qt.WindowType.Tool
        if cfg["window"]["alwaysOnTop"]:
            flags |= Qt.WindowType.WindowStaysOnTopHint
        if cfg["window"]["clickThrough"] and not self._drag_mode:
            flags |= Qt.WindowType.WindowTransparentForInput
        was_visible = self.isVisible()
        self.setWindowFlags(flags)
        if was_visible:
            self.show()

    def cfg(self) -> dict:
        """本窗口所在显示器实际生效的配置（全局 + 该屏的独立样式/位置）。"""
        return self.controller.config_for(self._target_index())

    def on_settings_changed(self, path: str, _value) -> None:
        if path.startswith(("window.", "display.", "position.")):
            self.rebuild()
        elif path.startswith(("style.", "time.")):
            self.repaint_now()

    def repaint_now(self) -> None:
        self.on_tick(self._now_ms)

    def rebuild(self) -> None:
        self._apply_flags()
        self._dpr = self._resolve_dpr()
        self.repaint_now()
        self._reposition()

    def _resolve_dpr(self) -> float:
        """目标屏的 devicePixelRatio：位图按它生成物理像素，避免被 Qt 二次放大。"""
        mons = self.controller.monitors
        if not mons:
            return 1.0
        idx = max(0, min(self._target_index(), len(mons) - 1))
        try:
            return build_screen_map(mons).dpr(idx)
        except Exception as exc:  # 屏幕枚举异常不应影响显示
            store.log(f"dpr 解析失败: {exc}", "WARN")
            return 1.0

    def on_tick(self, now_ms: int) -> None:
        self._now_ms = now_ms
        try:
            idx = self._target_index()
            img = self.controller.renderer.render(
                datetime.now(), self.controller.config_for(idx),
                self.controller.pack_for(idx), now_ms, self._dpr
            )
        except Exception as exc:  # 渲染层任何异常都不允许拖垮应用
            store.log(f"渲染失败: {exc}", "ERROR")
            return
        self._image = img
        # 位图是物理像素，窗口按逻辑尺寸排布
        ratio = img.devicePixelRatio() or 1.0
        lw = max(1, int(round(img.width() / ratio)))
        lh = max(1, int(round(img.height() / ratio)))
        if lw != self.width() or lh != self.height():
            self.resize(lw, lh)
            self._reposition()
        self.update()

    def _target_index(self) -> int:
        if self.monitor_index is not None:
            return self.monitor_index
        return int(self.controller.get("display.index", 0))

    def _reposition(self) -> None:
        """全部在 Qt 逻辑(DIP)坐标系计算，避免物理坐标被 dpr 二次缩放。"""
        if self._image is None or not self.controller.monitors:
            return
        cfg = self.cfg()
        monitors = self.controller.monitors
        # 时间文本 + 装饰留白的实际窗口尺寸（逻辑像素）
        w, h = self.width(), self.height()
        smap = build_screen_map(monitors)
        # autoRelocate=false：保持当前逻辑坐标，仅做逻辑边界钳制
        if not cfg["window"]["autoRelocate"] and getattr(self, "_has_positioned", False):
            x, y = smap.clamp(self.x(), self.y(), w, h, monitors)
            self.move(x, y)
            return
        idx = max(0, min(self._target_index(), len(monitors) - 1))
        x, y = smap.origin(cfg, w, h, idx)
        x, y = smap.clamp(x, y, w, h, monitors)
        self.move(x, y)
        self._has_positioned = True

    def paintEvent(self, _event) -> None:
        if self._image is None:
            return
        p = QPainter(self)
        p.drawImage(0, 0, self._image)
        if self._drag_mode:
            from PySide6.QtGui import QPen
            p.setPen(QPen(QColor("#2F6DF6"), 1, Qt.PenStyle.DashLine))
            p.drawRect(0, 0, self.width() - 1, self.height() - 1)
        p.end()

    # ---- 拖动 ----

    def set_drag_mode(self, enabled: bool) -> None:
        if self._drag_mode == enabled:
            return
        self._drag_mode = enabled
        self._drag_offset = None
        self._apply_flags()
        self.update()

    def mousePressEvent(self, event) -> None:
        if self._drag_mode and event.button() == Qt.MouseButton.LeftButton:
            self._drag_offset = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
            event.accept()

    def mouseMoveEvent(self, event) -> None:
        if self._drag_offset is not None:
            self.move(event.globalPosition().toPoint() - self._drag_offset)
            event.accept()

    def mouseReleaseEvent(self, event) -> None:
        if self._drag_offset is None:
            return
        self._drag_offset = None
        if self.cfg()["position"]["lockPosition"]:
            self._reposition()
            return
        self.commit_current_position()

    def commit_current_position(self) -> None:
        """把窗口当前所在位置记成「自定义位置」。

        只写 `position.custom` 与 `position.mode`，**绝不改 `position.preset`**：
        九宫格预设是相对桌面的固定锚点，拖动/更新位置不能把它挪走
        （旧实现把预设强写成 center 再把位移塞进 offsetX/Y，于是预设位置被改坏）。
        """
        w, h = self.width(), self.height()
        pos = self.pos()                       # Qt 逻辑坐标
        mons = self.controller.monitors
        if not mons:
            return
        smap = build_screen_map(mons)
        idx = smap.which(pos.x() + w // 2, pos.y() + h // 2, mons)
        l, t, r, b = smap.rects[idx]
        # 落盘为「相对该屏工作区左上角」的逻辑像素，换屏 / 改缩放都还站得住
        dx = max(0, min(pos.x() - l, max(0, (r - l) - w)))
        dy = max(0, min(pos.y() - t, max(0, (b - t) - h)))
        self.controller.set_custom_position(idx, dx, dy)
        store.log(f"自定义位置 -> 显示器 {idx} ({dx},{dy})")


class IdentifyOverlay(QWidget):
    """01 页「识别显示器」：每屏中央短暂显示序号，不抢焦点。"""

    def __init__(self, monitor, number: int, work_rect: tuple[int, int, int, int] | None = None):
        super().__init__()
        self.number = number
        size = 120
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.Tool
                            | Qt.WindowType.WindowStaysOnTopHint
                            | Qt.WindowType.WindowTransparentForInput)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        self.setFixedSize(size, size)
        # work_rect 必须是 Qt 逻辑工作区，物理坐标会在高 DPI 屏上再被缩放一次
        l, t, r, b = work_rect or (monitor.wl, monitor.wt, monitor.wr, monitor.wb)
        cx = (l + r) // 2
        cy = (t + b) // 2
        self.move(cx - size // 2, cy - size // 2)

    def paintEvent(self, _event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        p.fillRect(self.rect(), QColor(47, 109, 246, 230))
        p.setPen(QColor("#FFFFFF"))
        f = QFont("Consolas")
        f.setPixelSize(64)
        f.setBold(True)
        p.setFont(f)
        p.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, str(self.number))
        p.end()
