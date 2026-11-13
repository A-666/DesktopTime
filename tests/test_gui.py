# -*- coding: utf-8 -*-
"""GUI 冒烟测试：需要 PySide6，用 offscreen 平台运行。

运行示例（Windows）：
  set PYTHONPATH=<site-packages>;<项目根>
  set QT_QPA_PLATFORM=offscreen
  python tests/test_gui.py -v
"""
from __future__ import annotations

import os
import sys
import unittest
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication  # noqa: E402

from test_core import IsolatedStore  # noqa: E402

from core import clock, store, stylepack  # noqa: E402
from core.controller import AppController  # noqa: E402
from core.renderer import Renderer  # noqa: E402
from core.settings import defaults  # noqa: E402
from ui.clock_window import ClockWindow  # noqa: E402
from ui.main_window import MainWindow  # noqa: E402

app = QApplication.instance() or QApplication([])


def fake_monitors(n: int = 2):
    """多屏测试用：不依赖测试机真实插了几台显示器。"""
    from core.monitors import Monitor
    return [Monitor(index=i, name=f"\\\\.\\DISPLAY{i + 1}",
                    left=i * 1920, top=0, right=i * 1920 + 1920, bottom=1080,
                    wl=i * 1920, wt=0, wr=i * 1920 + 1920, wb=1032,
                    dpi=96, primary=(i == 0)) for i in range(n)]


class TestRenderer(unittest.TestCase):
    def setUp(self):
        self.r = Renderer()
        self.cfg = defaults()

    def test_all_presets_render(self):
        for key in stylepack.BUILTIN:
            pack = stylepack.get_builtin(key)
            img = self.r.render(datetime(2026, 11, 11, 14, 35, 8), self.cfg, pack, 0)
            self.assertGreater(img.width(), 40)
            self.assertGreater(img.height(), 20)
            self.assertFalse(img.isNull())

    def test_all_eight_decorations(self):
        decs = [
            {"type": "stack", "gap": 6}, {"type": "backdrop", "color": "#1F2328"},
            {"type": "shadow", "color": "#000000", "blur": 8},
            {"type": "glow", "color": "#2F6DF6", "radius": 8},
            {"type": "outline", "width": 1, "color": "#FFFFFF"},
            {"type": "border", "style": "dashed", "width": 1, "color": "#C9413A"},
            {"type": "divider", "position": "bottom", "width": 1},
            {"type": "ring", "mode": "second", "width": 2},
        ]
        effs = [{"type": "breath", "duration": 2400}, {"type": "fade", "duration": 1200},
                {"type": "pulse", "scale": 1.05}, {"type": "blink", "onMs": 600, "offMs": 400}]
        pack, warns = stylepack.validate_pack({"decorations": decs, "effects": effs})
        self.assertEqual(len(pack["decorations"]), 8)
        self.assertEqual(len(pack["effects"]), 4)
        for ms in (0, 33, 600, 1200, 2400):
            img = self.r.render(datetime.now(), self.cfg, pack, ms)
            self.assertFalse(img.isNull())

    def test_broken_layer_does_not_crash(self):
        pack = {"text": {"size": 40}, "decorations": [{"type": "glow", "radius": "bad"}],
                "effects": []}
        img = self.r.render(datetime.now(), self.cfg, pack, 0)
        self.assertFalse(img.isNull())

    def test_cache_without_effects(self):
        pack = stylepack.get_builtin("minimal")
        a = self.r.render(datetime(2026, 11, 11, 14, 35, 8), self.cfg, pack, 0)
        b = self.r.render(datetime(2026, 11, 11, 14, 35, 8), self.cfg, pack, 999)
        self.assertIs(a, b)  # 无动画且文本未变时复用上一帧

    def test_sub_line_inside_canvas(self):
        """回归：日期/星期副行曾被画到画布之外，整行裁掉（基线多叠了一个 ascent）。

        断言画布下半部分必须有墨迹 —— 只看 build_lines() 是查不出这个 bug 的。
        """
        cfg = defaults()
        cfg["time"]["showDate"] = True
        cfg["time"]["showWeekday"] = True
        cfg["style"]["size"] = 60
        pack = stylepack.get_builtin("minimal")
        img = self.r.render(datetime(2026, 11, 11, 22, 52, 11), cfg, pack, 0)

        main_text, sub_text = clock.build_lines(datetime(2026, 11, 11, 22, 52, 11), cfg)
        self.assertTrue(sub_text)
        band_top = img.height() // 2
        ink = 0
        for y in range(band_top, img.height()):
            for x in range(0, img.width(), 2):
                if img.pixelColor(x, y).alpha() > 24:
                    ink += 1
        self.assertGreater(ink, 0, "副行没有任何像素落在画布内")

    def test_dpr_scales_bitmap_not_logical_size(self):
        """回归：1x 位图在 150% 屏上被 Qt 放大 1.5 倍，文字边缘发毛。"""
        pack = stylepack.get_builtin("minimal")
        now = datetime(2026, 11, 11, 14, 35, 8)
        base = self.r.render(now, self.cfg, pack, 0, 1.0)
        hidpi = Renderer().render(now, self.cfg, pack, 0, 1.5)

        self.assertAlmostEqual(hidpi.devicePixelRatio(), 1.5, places=3)
        self.assertAlmostEqual(base.devicePixelRatio(), 1.0, places=3)
        # 逻辑尺寸不变，物理像素按 dpr 放大
        self.assertEqual(hidpi.width(), round(base.width() * 1.5))
        self.assertEqual(hidpi.height(), round(base.height() * 1.5))
        self.assertEqual(round(hidpi.width() / hidpi.devicePixelRatio()), base.width())

    def test_twenty_presets_have_distinct_looks(self):
        """20 套预设必须真的长得不一样，不能只是换了名字。"""
        packs = {k: stylepack.get_builtin(k) for k in stylepack.BUILTIN}
        self.assertEqual(len(packs), 20)
        self.assertEqual(packs["lcd"]["render"], "segments")
        self.assertEqual(packs["analog"]["render"], "analog")
        self.assertEqual(packs["flip"]["render"], "flip")
        self.assertEqual(packs["matrix"]["render"], "dots")
        # 指针不再铺白色表盘面：只留外环 + 刻度 + 三针（要求「只允许时间文字」）
        self.assertEqual(packs["analog"]["face"]["opacity"], 0.0)
        # 反白 / 细体已下线，深色底一律不许再出现
        self.assertNotIn("panel", packs)
        self.assertNotIn("hairline", packs)

        now = datetime(2026, 11, 11, 10, 9, 36)
        sizes = set()
        for key, pack in packs.items():
            img = self.r.render(now, self.cfg, pack, 0, 1.0)
            self.assertFalse(img.isNull())
            sizes.add((img.width(), img.height()))
        # 画布尺寸种类足够多，说明版式确实有区别（不是同一张图换色）；
        # 五种绘制模式都得有预设用到，否则新加的渲染分支等于死代码
        self.assertGreaterEqual(len(sizes), 8)
        self.assertEqual({p["render"] for p in packs.values()},
                         {"text", "segments", "analog", "flip", "dots"})

    def test_flip_and_dots_really_draw(self):
        """翻页 / 点阵是新增的绘制模式，必须真的画出墨迹，而不是空白画布。"""
        cfg = defaults()
        cfg["time"].update({"format": "HH:mm", "custom": "", "showSeconds": False,
                            "hour12": False, "showDate": False, "showWeekday": False})
        for key in ("flip", "matrix"):
            pack = stylepack.get_builtin(key)
            img = self.r.render(datetime(2026, 11, 11, 10, 9, 0), cfg, pack, 0, 1.0)
            ink = sum(1 for y in range(img.height()) for x in range(img.width())
                      if img.pixelColor(x, y).alpha() > 40)
            self.assertGreater(ink, 400, f"{key} 几乎没有墨迹")

    def test_default_font_size_is_60(self):
        self.assertEqual(defaults()["style"]["size"], 60)

    def test_preset_painter_never_touches_canvas_edge(self):
        """回归：装饰图层画到画布边缘会被切掉一半。

        `border` 曾按 `width/2` 直接贴边画，虚线的框四面各丢半像素；
        留白必须吃掉 `padding + width + 2`。20 套逐个量 alpha 边界。
        """
        now = datetime(2026, 11, 11, 10, 9, 36)
        clipped = []
        for key in stylepack.BUILTIN:
            img = self.r.render(now, self.cfg, stylepack.get_builtin(key), 0, 1.0)
            w, h = img.width(), img.height()
            edge = max(
                max(img.pixelColor(x, 0).alpha() for x in range(w)),
                max(img.pixelColor(x, h - 1).alpha() for x in range(w)),
                max(img.pixelColor(0, y).alpha() for y in range(h)),
                max(img.pixelColor(w - 1, y).alpha() for y in range(h)),
            )
            if edge > 8:
                clipped.append((key, edge))
        self.assertFalse(clipped, f"这些预设的图形贴边被裁：{clipped}")

    def test_analog_second_hand_moves(self):
        """回归：analog 不产生文字，缓存键曾漏掉时间，秒针会停死在第一帧。"""
        pack = stylepack.get_builtin("analog")
        r = Renderer()
        a = r.render(datetime(2026, 11, 11, 10, 9, 10), self.cfg, pack, 0)
        b = r.render(datetime(2026, 11, 11, 10, 9, 40), self.cfg, pack, 0)
        self.assertNotEqual(a.constBits().tobytes(), b.constBits().tobytes())

    def test_frame_color_follows_text_color(self):
        """回归：改文字颜色，边框/括号/虚线框要跟着变（用户报「白字配青框」）。"""
        for key in ("tech", "frame", "dash", "twin"):
            pack = stylepack.get_builtin(key)
            cfg = defaults()
            cfg["style"].update({"color": "#FF3B30", "textStyles": []})
            img = Renderer().render(datetime(2026, 11, 11, 10, 9, 0), cfg, pack, 0, 1.0)
            others = 0
            inks = 0
            for y in range(0, img.height(), 2):
                for x in range(0, img.width(), 2):
                    c = img.pixelColor(x, y)
                    if c.alpha() < 200:
                        continue
                    inks += 1
                    # 只允许字色本身（红色系），不许残留预设的青色 / 灰白色
                    if not (c.red() > 180 and c.green() < 120 and c.blue() < 120):
                        others += 1
            self.assertGreater(inks, 50, f"{key} 几乎没画出东西")
            self.assertEqual(others, 0, f"{key} 里有 {others} 个像素没跟随字色")

    def test_date_line_is_centered_under_time(self):
        """回归：日期 / 星期必须压在时间正中。

        旧实现只给指针 / 翻页模式居中，文本模式一行 `sub_x = tx` 直接左对齐，
        于是「18:20:13」下面那条日期贴着左边，看着整块歪掉。
        """
        cases = (("minimal", "HH:mm"), ("tech", "HH:mm:ss"), ("serif", "HH:mm:ss"))
        for key, fmt in cases:
            pack = stylepack.get_builtin(key)
            cfg = defaults()
            cfg["style"].update({"color": "#FFFFFF", "size": 58, "textStyles": []})
            cfg["time"].update({"format": fmt, "showSeconds": "ss" in fmt,
                                "showDate": True, "showWeekday": True})
            img = Renderer().render(datetime(2026, 11, 12, 18, 20, 13), cfg, pack, 0, 1.0)
            w, h = img.width(), img.height()
            spans = []
            for y in range(h):
                xs = [x for x in range(w) if img.pixelColor(x, y).alpha() > 40]
                spans.append((min(xs), max(xs)) if xs else None)
            half = h // 2
            top = [sp for sp in spans[:half] if sp]
            bot = [sp for sp in spans[half:] if sp]
            self.assertTrue(top and bot, f"{key} 主行或副行没画出东西")
            ct = (min(a for a, _ in top) + max(b for _, b in top)) / 2
            cb = (min(a for a, _ in bot) + max(b for _, b in bot)) / 2
            self.assertLessEqual(abs(cb - ct), 3, f"{key} 日期行偏离中线 {cb - ct:+.1f}px")

    def test_flush_tolerates_missing_streams(self):
        """回归：`console=False` 双击启动时 sys.stdout / sys.stderr 都是 None。

        旧实现 `sys.stdout.flush()` 直怼，抛的是 AttributeError，而 except 只兜
        (OSError, ValueError) —— 异常冲出 main() 后被 PyInstaller 引导器接住，
        弹「Unhandled exception in script」，且弹窗阻塞，进程要等用户点关闭才死。
        """
        import app as entry            # 入口模块，导入即完成 Qt 路径补全

        saved = sys.stdout, sys.stderr
        try:
            sys.stdout = None
            sys.stderr = None
            entry._flush_streams()     # 不得抛异常
        finally:
            sys.stdout, sys.stderr = saved

        # 有正常流时也不能吞掉真实错误：关闭的流要照旧安静
        class ClosedIO:
            def flush(self):
                raise ValueError("I/O operation on closed file")

        try:
            sys.stdout, sys.stderr = ClosedIO(), ClosedIO()
            entry._flush_streams()
        finally:
            sys.stdout, sys.stderr = saved

    def test_ring_track_follows_text_color(self):
        """计时环：弧与轨道都写 auto，轨道自动降透明度但同色系。"""
        pack = stylepack.get_builtin("ring")
        cfg = defaults()
        cfg["style"].update({"color": "#22CC88", "textStyles": []})
        img = Renderer().render(datetime(2026, 11, 11, 10, 9, 30), cfg, pack, 0, 1.0)
        greens = sum(1 for y in range(0, img.height(), 2) for x in range(0, img.width(), 2)
                     if img.pixelColor(x, y).alpha() > 60
                     and img.pixelColor(x, y).green() > img.pixelColor(x, y).red())
        self.assertGreater(greens, 200)

    def test_segments_mode_draws_digits(self):
        """七段码模式：数字必须落在画布内，而不是空白。"""
        pack = stylepack.get_builtin("lcd")
        img = Renderer().render(datetime(2026, 11, 11, 10, 9, 36), self.cfg, pack, 0)
        ink = sum(1 for y in range(0, img.height(), 3)
                  for x in range(0, img.width(), 3)
                  if img.pixelColor(x, y).alpha() > 24)
        self.assertGreater(ink, 50)


class TestControllerAndUI(unittest.TestCase):
    def setUp(self):
        self.iso = IsolatedStore()
        self.base = self.iso.__enter__()
        self.c = AppController(dpi_mode="TEST")
        self.win = MainWindow(self.c)

    def tearDown(self):
        self.c._timer.stop()
        # 避免 closeEvent 弹出「每次询问」模态框阻塞 offscreen 测试
        self.c.settings.set("tray.onClose", "exit")
        self.win.close()
        self.iso.__exit__(None, None, None)

    def test_monitor_preview_grows_for_stacked_layout(self):
        """回归：多屏竖排时缩略图要长高，不能把方块压扁到看不清。

        6 台 2 列 × 3 层时虚拟桌面很高，固定 170px 会把每块压到 79×44，
        而块里那行 `1920×1032` 需要 70px 宽 —— 几乎贴边。改为按
        「方块不低于 56px」反推高度，上限 240px。
        """
        from core.monitors import Monitor
        from ui.widgets import MonitorPreview

        def mk(i, x, y):
            return Monitor(index=i, name=f"M{i}", left=x, top=y,
                           right=x + 1920, bottom=y + 1080,
                           wl=x, wt=y, wr=x + 1920, wb=y + 1032,
                           dpi=96, primary=(i == 0))

        stacked = MonitorPreview()
        stacked.resize(680, MonitorPreview.BASE_H)
        stacked.set_monitors([mk(i, (i % 2) * 1920, (i // 2) * 1080) for i in range(6)])
        self.assertGreater(stacked.height(), MonitorPreview.BASE_H,
                           "竖排 3 层应该长高，否则方块被压扁")
        self.assertLessEqual(stacked.height(), MonitorPreview.MAX_H,
                             "不得超过上限，否则会把下面的卡片顶出首屏")

        # 常规双屏横排必须保持原高度 —— 不能为了极端场景牺牲默认观感
        flat = MonitorPreview()
        flat.resize(680, MonitorPreview.BASE_H)
        flat.set_monitors([mk(0, 0, 0), mk(1, 1920, 0)])
        self.assertEqual(flat.height(), MonitorPreview.BASE_H)

    def test_seven_pages(self):
        self.assertEqual(self.win.stack.count(), 7)
        self.assertEqual(self.win.nav.count(), 7)
        for i in range(7):
            self.win.nav.setCurrentRow(i)
            self.assertEqual(self.win.stack.currentIndex(), i)

    def test_clock_window_created(self):
        w = ClockWindow(self.c, None)
        self.assertIsNotNone(w._image)
        self.assertGreater(w.width(), 40)
        self.assertGreater(w.height(), 20)
        w.close()

    def test_grid_click_returns_to_preset_mode(self):
        """点九宫格 = 回到预设模式；自定义落点保留，随时可以再切回去。"""
        self.c.set_custom_position(0, 120, 80)
        self.assertEqual(self.c.get("position.mode"), "custom")
        self.c.set_position_preset("bottom-right")
        self.assertEqual(self.c.get("position.mode"), "preset")
        self.assertEqual(self.c.get("position.preset"), "bottom-right")
        # 自定义落点没有被清掉
        self.assertEqual(self.c.get("position.custom.x"), 120)
        self.assertEqual(self.c.get("position.custom.y"), 80)

    def test_custom_position_never_touches_preset(self):
        """回归：拖动 / 更新位置把预设强写成 center 并把位移塞进 offsetX，
        导致「预设位置被改坏」。现在只写 custom，preset 分毫不动。"""
        self.c.set_position_preset("top-left")
        before = self.c.get("position.preset")
        self.c.set_custom_position(1, 333, 222)
        self.assertEqual(self.c.get("position.preset"), before)
        self.assertEqual(self.c.get("display.index"), 1)
        self.assertEqual(self.c.data()["position"].get("offsetX"), None)

    def test_drag_commit_then_preset_snaps_back(self):
        """端到端：拖动落点 → 记成自定义 → 点预设 → 回到原锚点，分毫不差。"""
        w = ClockWindow(self.c, None)
        w.show()
        self.c.set_position_preset("center")
        w._reposition()
        anchor_pos = (w.x(), w.y())
        # 模拟一次拖动结束
        w.move(anchor_pos[0] + 60, anchor_pos[1] + 40)
        w.commit_current_position()
        self.assertEqual(self.c.get("position.mode"), "custom")
        self.assertEqual(self.c.get("position.preset"), "center")
        moved = (w.x(), w.y())
        self.assertNotEqual(moved, anchor_pos)
        w._reposition()                       # 重排后仍停在自定义落点
        self.assertEqual((w.x(), w.y()), moved)
        # 点九宫格「居中」→ 必须精确回到锚点
        self.c.set_position_preset("center")
        w._reposition()
        self.assertEqual((w.x(), w.y()), anchor_pos)
        w.close()

    def test_position_page_uses_custom_fields(self):
        page = self.win.pages[3]
        for name in ("cx", "cy", "margin", "grid", "drag", "snap", "lock"):
            self.assertTrue(hasattr(page, name), f"04 页缺少控件 {name}")
        self.assertFalse(hasattr(page, "ox"), "旧的 X 偏移控件应已移除")
        # 自定义模式下九宫格不应高亮任何格子（一眼看出当前不是预设位）
        self.c.set_custom_position(0, 200, 120)
        page.sync_all()
        self.assertFalse(any(b.isChecked() for b in page.grid.buttons))
        # 点回预设则恢复高亮
        self.c.set_position_preset("bottom")
        page.sync_all()
        self.assertTrue(page.grid.buttons[7].isChecked())

    def test_switch_and_undo(self):
        original = self.c.get("time.format")
        self.c.set("time.format", "HH:mm")
        self.c.save_profile("会议模式")
        self.c.set("time.format", "HH:mm:ss")
        self.assertTrue(self.c.switch_profile("会议模式"))
        self.assertEqual(self.c.get("time.format"), "HH:mm")
        self.assertTrue(self.c.can_undo())
        self.assertTrue(self.c.undo())
        self.assertEqual(self.c.get("time.format"), "HH:mm:ss")
        self.assertFalse(self.c.can_undo())

    def test_setting_change_invalidates_undo(self):
        self.c.save_profile("演示模式")
        self.c.switch_profile("演示模式")
        self.assertTrue(self.c.can_undo())
        self.c.set("style.size", 60)
        self.assertFalse(self.c.can_undo())

    def test_preset_switch_keeps_position(self):
        self.c.set("position.offsetX", 321)
        self.c.set_preset("tech")
        self.assertEqual(self.c.get("style.preset"), "tech")
        self.assertEqual(self.c.get("position.offsetX"), 321)
        self.assertEqual(len(self.c.pack["decorations"]), 2)

    def test_preset_switch_never_enables_background(self):
        """回归：切预设曾顺手打开「背景板」，桌面会先干净一秒再冒出一块灰底。"""
        self.c.set("style.background.enabled", False)
        for key in stylepack.BUILTIN:
            self.c.set_preset(key)
            self.assertFalse(self.c.get("style.background.enabled"),
                             f"切到 {key} 后背景板被打开了")
            self.assertFalse(self.c.pack.get("bg", {}).get("enabled"))

    def test_style_page_has_scroll_area(self):
        """20 套预设必须放在固定两行高的滚动区里，不能把下面几块顶走。"""
        from PySide6.QtWidgets import QScrollArea
        from ui.widgets import PresetCard
        self.win.nav.setCurrentRow(2)
        page = self.win.pages[2]
        self.assertEqual(len(page.cards), 20)
        boxes = page.findChildren(QScrollArea, "presetscroll")
        self.assertEqual(len(boxes), 1)
        self.assertEqual(boxes[0].height(), PresetCard.HEIGHT * 2 + 10)

    def test_style_cards_are_same_size(self):
        """回归：20 张样式卡的宽高必须一致。

        原来网格只给「尾列」设了 stretch，前 4 列各按自己的 sizeHint 分配，
        而 sizeHint 又被标题文字和缩略图像素宽度撑 —— 实测出 128/157/144/176
        四种列宽，用户一眼就看出列不齐。现在 4 列均分，卡宽只由视口宽度决定。
        """
        from ui.widgets import PresetCard
        self.win.nav.setCurrentRow(2)
        page = self.win.pages[2]
        self.win.show()
        try:
            for win_w in (1000, 1280):
                self.win.resize(win_w, 720)
                for _ in range(4):
                    self.win.layout().activate()
                    page.layout().activate()
                    app.processEvents()
                widths = {c.width() for c in page.cards}
                heights = {c.height() for c in page.cards}
                self.assertEqual(heights, {PresetCard.HEIGHT}, f"{win_w}: 高度不齐")
                # 均分是整数分配，窄窗口下允许 1px 取整差，但不能出现 2px 以上的差
                self.assertLessEqual(max(widths) - min(widths), 1,
                                     f"{win_w}: 宽度差 {max(widths) - min(widths)}px {sorted(widths)}")
        finally:
            self.win.hide()

    def test_reset_keeps_profiles(self):
        self.c.save_profile("保留我")
        self.c.set("style.color", "#C9413A")
        self.c.reset_defaults()
        self.assertEqual(self.c.get("style.color"), "#1F2328")
        self.assertEqual(len(self.c.profiles.list()), 1)

    def test_color_palette_pick(self):
        self.win.nav.setCurrentRow(2)
        page = self.win.pages[2]
        page._pick_color("#2F6DF6")
        self.assertEqual(self.c.get("style.color"), "#2F6DF6")
        self.assertEqual(self.c.get("style.recentColors")[0], "#2F6DF6")

    # ---- 每屏独立样式 / 位置 ----

    def test_per_monitor_style_isolated(self):
        """03 页选不同显示器，改的是各自那一份，互不串味。"""
        self.c.monitors = fake_monitors(2)
        self.c.set("display.all", True)
        base = self.c.config_for(0)["style"]["color"]
        self.c.set_edit_index(1)
        self.c.set("style.color", "#C9413A")
        self.c.set("style.size", 88)
        self.assertEqual(self.c.get("style.color"), "#C9413A")      # 页面看到的是自己改的
        self.assertEqual(self.c.config_for(1)["style"]["size"], 88)
        self.assertEqual(self.c.config_for(0)["style"]["color"], base)
        self.assertEqual(self.c.config_for(0)["style"]["size"], 60)
        self.c.set_edit_index(0)
        self.assertEqual(self.c.get("style.color"), base)             # 切回去就是原来那份

    def test_per_monitor_position_isolated(self):
        self.c.monitors = fake_monitors(2)
        self.c.set("display.all", True)
        self.c.set_edit_index(0)
        self.c.set_position_preset("top-left")
        self.c.set_edit_index(1)
        self.c.set_position_preset("bottom-right")
        self.assertEqual(self.c.config_for(0)["position"]["preset"], "top-left")
        self.assertEqual(self.c.config_for(1)["position"]["preset"], "bottom-right")

    def test_per_monitor_pack_follows_preset(self):
        """换预设连带换样式包：装饰层要按那台屏自己的配置解析。"""
        self.c.monitors = fake_monitors(2)
        self.c.set("display.all", True)
        self.c.set_edit_index(1)
        self.c.set_preset("tech")
        self.assertEqual(len(self.c.pack_for(1)["decorations"]), 2)
        self.assertEqual(len(self.c.pack_for(0)["decorations"]), 0)

    def test_apply_to_all_and_follow_global(self):
        self.c.monitors = fake_monitors(3)
        self.c.set("display.all", True)
        self.c.set_edit_index(1)
        self.c.set("style.color", "#0969DA")
        self.c.apply_style_to_all()
        for i in range(3):
            self.assertEqual(self.c.config_for(i)["style"]["color"], "#0969DA")
        self.c.set_edit_index(2)
        self.c.reset_edit_monitor()
        self.assertIsNone(self.c.monitor_bucket(2))
        self.assertEqual(self.c.config_for(2)["style"]["color"],
                         self.c.data()["style"]["color"])

    def test_apply_to_all_from_global_clears_per_monitor(self):
        """源屏本来跟随全局时，「应用到全部」应清空独立配置而不是发副本 ——
        副本看着一样，但之后改全局不会跟着变，就不是真的「统一」了。"""
        self.c.monitors = fake_monitors(3)
        self.c.set("display.all", True)
        self.c.set_edit_index(1)
        self.c.set("style.size", 40)
        self.c.set_edit_index(2)
        self.c.set("style.size", 90)
        self.assertEqual(set(self.c.data()["perMonitor"]), {"1", "2"})

        self.c.set_edit_index(0)          # 0 号屏没有独立配置，跟随全局
        self.c.apply_style_to_all()
        self.assertEqual(self.c.settings.data.get("perMonitor"), {})
        for i in range(3):
            self.assertEqual(self.c.config_for(i)["style"]["size"],
                             self.c.data()["style"]["size"])

    def test_single_mode_writes_global(self):
        """单屏模式不能偷偷建 perMonitor，否则「页面显示 A、桌面渲染 B」。"""
        self.c.monitors = fake_monitors(2)
        self.c.set("display.all", False)
        self.c.set("style.size", 72)
        self.assertEqual(self.c.data()["perMonitor"], {})
        self.assertEqual(self.c.data()["style"]["size"], 72)

    def test_monitor_picker_shows_number_and_resolution(self):
        self.c.monitors = fake_monitors(2)
        self.win.nav.setCurrentRow(2)
        page = self.win.pages[2]
        page.sync_all()
        combo = page.picker.combo
        self.assertEqual(combo.count(), 2)
        self.assertEqual(combo.itemData(0), 0)
        self.assertEqual(combo.itemData(1), 1)
        self.assertIn("1920", combo.itemText(0))
        self.assertIn("1080", combo.itemText(0))
        # 04 页用同一个控件、同一个编辑目标
        self.win.nav.setCurrentRow(3)
        self.assertEqual(self.win.pages[3].picker.combo.count(), 2)

    def test_edit_target_survives_switch(self):
        """切屏 → 页面值同步换人（03 页样式与 04 页位置一起换）。"""
        self.c.monitors = fake_monitors(2)
        self.c.set("display.all", True)
        self.c.set_edit_index(0)
        self.c.set("style.size", 40)
        self.c.set_edit_index(1)
        self.c.set("style.size", 90)
        self.win.nav.setCurrentRow(2)
        page = self.win.pages[2]
        self.assertEqual(page.size.value(), 90)
        self.c.set_edit_index(0)
        self.assertEqual(page.size.value(), 40)

    def test_nine_grid_click(self):
        self.win.nav.setCurrentRow(3)
        page = self.win.pages[3]
        page.grid._pick("bottom")
        self.assertEqual(self.c.get("position.preset"), "bottom")

    # ---------- 每屏编辑目标 ----------

    def _picker(self, row: int = 2):
        self.win.nav.setCurrentRow(row)
        picker = self.win.pages[row].picker
        picker.sync()
        return picker

    def test_picker_only_has_combo_and_apply_all(self):
        """03 / 04 页顶部只留「显示器下拉 + 应用到全部」，不再挂单独设置的开关。"""
        self.c.monitors = fake_monitors(2)
        self.c.set("display.all", True)
        picker = self._picker()
        self.assertFalse(hasattr(picker, "standalone"))
        self.assertEqual(picker.combo.count(), 2)
        self.assertTrue(picker.apply_btn.isEnabled())
        self.assertIn("单独设置", picker.hint.text())

    def test_single_mode_still_writes_global(self):
        """没有开关也不等于能在单屏模式分家：改设置仍然只落全局。"""
        self.c.monitors = fake_monitors(1)
        self.c.set("display.all", False)
        self._picker()
        self.c.set("style.size", 66)
        self.assertEqual(self.c.settings.data.get("perMonitor"), {})

    # ---------- 06 方案页的右键菜单 ----------

    def test_profile_menu_on_item(self):
        from PySide6.QtWidgets import QListWidgetItem

        self.win.nav.setCurrentRow(5)
        page = self.win.pages[5]
        item = QListWidgetItem("我的配置")
        page.list.addItem(item)
        texts = [a.text() for a in page._build_menu(item).actions() if not a.isSeparator()]
        self.assertEqual(texts, ["保存当前设置", "另存为…", "重命名…", "删除"])

    def test_profile_menu_on_blank_area_only_offers_save_as(self):
        self.win.nav.setCurrentRow(5)
        page = self.win.pages[5]
        texts = [a.text() for a in page._build_menu(None).actions() if not a.isSeparator()]
        self.assertEqual(texts, ["另存为…"])

    def test_profile_list_keeps_selection_after_refresh(self):
        """右键保存 / 重命名都会重建列表，选中项不能丢。"""
        self.win.nav.setCurrentRow(5)
        page = self.win.pages[5]
        for name in ("Alpha", "Beta", "Gamma"):
            self.c.save_profile(name)
        page.sync_all()
        row = next(i for i in range(page.list.count())
                   if page.list.item(i).text() == "Beta")
        page.list.setCurrentRow(row)
        page._refresh_list()
        self.assertEqual(page._current_name(), "Beta")

    # ---------- 字体列表与 Qt 日志噪音 ----------

    def test_font_list_excludes_bitmap_fonts(self):
        """Windows 位图字体不能进字体下拉。

        DirectWrite 只认 TrueType/OpenType，为 raster 字体建面必然失败，
        Qt 会按字体数刷出几十行「CreateFontFaceFromHDC() failed」。
        """
        from PySide6.QtGui import QFontDatabase

        # offscreen 平台没有真实字体后端（families() 只有 1 个且全部判为不可缩放），
        # 在这里断言等于测空集，得用 windows 平台跑才有意义
        if len(QFontDatabase.families()) <= 50:
            self.skipTest("当前无真实字体后端（offscreen），字体列表不具参考性")

        self.win.nav.setCurrentRow(2)
        page = self.win.pages[2]
        families = [page.font.itemData(i) for i in range(page.font.count())]
        bad = [f for f in families if not QFontDatabase.isSmoothlyScalable(f)]
        self.assertEqual(bad, [], f"这些位图字体不该出现在列表里: {bad}")
        self.assertNotIn("MS Sans Serif", families)
        self.assertIn("Consolas", families)

    def test_qt_log_filter_scope_is_narrow(self):
        """日志过滤器只该吞「位图字体建不出面」这一种，别的 Qt 消息不能连坐。"""
        from app import _should_swallow_qt_message as swallow

        noise = ("DirectWrite: CreateFontFaceFromHDC() failed "
                 "(指示输入文件 (例如字体文件) 中的错误。) for QFontDef(Family=\"System\")")
        self.assertTrue(swallow("qt.qpa.fonts", noise))
        self.assertFalse(swallow("qt.qpa.fonts", "某个别的字体告警"))
        self.assertFalse(swallow("qt.qpa.gl", noise))
        self.assertFalse(swallow("", noise))
        self.assertFalse(swallow("default", "普通消息"))


class TestTrayBubble(unittest.TestCase):
    """回归：非首次启动的托盘气泡曾因 type= 关键字导致 exe 启动即崩。"""

    def test_show_message_positional_args(self):
        from PySide6.QtWidgets import QSystemTrayIcon
        icon = QSystemTrayIcon()
        icon.showMessage("标题", "内容", QSystemTrayIcon.MessageIcon.Information, 3000)

    def test_app_source_uses_positional_args(self):
        src = (ROOT / "app.py").read_text(encoding="utf-8")
        self.assertNotIn("type=tray.icon.MessageIcon", src)
        self.assertIn("QSystemTrayIcon.MessageIcon.Information, 3000", src)


if __name__ == "__main__":
    unittest.main(verbosity=2)
