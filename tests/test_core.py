# -*- coding: utf-8 -*-
"""核心逻辑单元测试（不依赖 Qt，可用任意 Python 3.10+ 运行）。"""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core import clock, store, stylepack
from core.monitors import (Monitor, anchor_origin, clamp_to_screen,
                           compute_origin, monitor_at)
from core.profiles import ProfileManager, safe_name
from core.settings import (DEFAULTS, POSITION_PRESETS, PRESET_ANCHOR, Settings,
                           coerce, defaults)

_NOW = datetime(2026, 11, 11, 14, 35, 8)  # 星期三


class IsolatedStore:
    """把 store 的运行时路径重定向到临时目录，避免污染真实配置。"""

    KEYS = ("APP_DIR", "SETTINGS_FILE", "PROFILES_DIR", "STYLES_DIR",
            "SNAPSHOTS_DIR", "LOGS_DIR", "SNAPSHOT_FILE", "LOG_FILE")

    def __enter__(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.orig = {k: getattr(store, k) for k in self.KEYS}
        base = Path(self.tmp.name)
        store.APP_DIR = base
        store.SETTINGS_FILE = base / "settings.json"
        store.PROFILES_DIR = base / "profiles"
        store.STYLES_DIR = base / "styles"
        store.SNAPSHOTS_DIR = base / "snapshots"
        store.LOGS_DIR = base / "logs"
        store.SNAPSHOT_FILE = store.SNAPSHOTS_DIR / "last_switch.json"
        store.LOG_FILE = store.LOGS_DIR / "desktoptime.log"
        store.ensure_dirs()
        return base

    def __exit__(self, *_args):
        for k, v in self.orig.items():
            setattr(store, k, v)
        self.tmp.cleanup()


class TestSettings(unittest.TestCase):
    def test_defaults_complete(self):
        d = defaults()
        for group in ("display", "time", "style", "position", "app", "tray", "window"):
            self.assertIn(group, d)
        self.assertEqual(d["schema"], "desktoptime.config/v1")

    def test_coerce_partial_and_unknown(self):
        data, warns = coerce({"time": {"format": "HH:mm"}, "bogus": 1,
                              "style": {"color": "#FF0000", "unknown": "x"}})
        self.assertEqual(data["time"]["format"], "HH:mm")
        self.assertEqual(data["time"]["showSeconds"], True)      # 缺项补默认
        self.assertEqual(data["style"]["color"], "#FF0000")
        self.assertNotIn("bogus", data)
        self.assertNotIn("unknown", data["style"])

    def test_coerce_bad_types(self):
        data, warns = coerce({"style": {"size": "abc", "opacity": "x"},
                              "time": {"showSeconds": "yes"}})
        self.assertEqual(data["style"]["size"], 60)   # 默认字号 60
        self.assertEqual(data["style"]["opacity"], 1.0)
        self.assertIs(data["time"]["showSeconds"], True)
        self.assertTrue(warns)

    def test_clamp_ranges(self):
        data, _ = coerce({"style": {"size": 999, "opacity": -1,
                                    "recentColors": [f"#11111{i}" for i in range(9)]},
                          "position": {"margin": 999}})
        self.assertEqual(data["style"]["size"], 200)
        self.assertEqual(data["style"]["opacity"], 0.2)
        self.assertEqual(data["position"]["margin"], 200)
        self.assertEqual(len(data["style"]["recentColors"]), 4)

    def test_enum_fallback(self):
        data, _ = coerce({"position": {"preset": "nope"}, "tray": {"onClose": "nope"}})
        self.assertEqual(data["position"]["preset"], POSITION_PRESETS[0])
        self.assertEqual(data["tray"]["onClose"], "minimize")

    def test_hex_color(self):
        data, _ = coerce({"style": {"color": "red"}})
        self.assertEqual(data["style"]["color"], "#1F2328")

    def test_nine_grid_anchor_regression(self):
        """回归：top/left/right/bottom/center 不含连字符，曾被 split('-') 误判为居中。"""
        self.assertEqual(len(PRESET_ANCHOR), 9)
        self.assertEqual(set(PRESET_ANCHOR), set(POSITION_PRESETS))
        self.assertEqual(PRESET_ANCHOR["top"], ("center", "top"))
        self.assertEqual(PRESET_ANCHOR["bottom"], ("center", "bottom"))
        self.assertEqual(PRESET_ANCHOR["left"], ("left", "middle"))
        self.assertEqual(PRESET_ANCHOR["right"], ("right", "middle"))
        self.assertEqual(PRESET_ANCHOR["center"], ("center", "middle"))

    def test_settings_set_get(self):
        s = Settings()
        s.set("display.index", 2)
        s.set("style.color", "#ABCDEF")
        self.assertEqual(s.get("display.index"), 2)
        self.assertEqual(s.get("style.color"), "#ABCDEF")
        self.assertTrue(s.get("updatedAt"))


class TestClock(unittest.TestCase):
    def test_24h(self):
        self.assertEqual(clock.apply_format("HH:mm:ss", _NOW), "14:35:08")

    def test_12h(self):
        self.assertEqual(clock.apply_format("hh:mm tt", _NOW, True), "02:35 PM")

    def test_tokens(self):
        expected = f"2026-11-11 {clock.WEEKDAY_CN[_NOW.weekday()]}"
        self.assertEqual(clock.apply_format("yyyy-MM-dd dddd", _NOW), expected)

    def test_token_prefix_not_swallowed(self):
        self.assertEqual(clock.apply_format("HH:mm", _NOW), "14:35")

    def test_build_lines_sub(self):
        cfg = {"time": {"format": "HH:mm:ss", "showDate": True, "showWeekday": True,
                        "showSeconds": True, "hour12": False, "custom": ""}}
        main, sub = clock.build_lines(_NOW, cfg)
        self.assertEqual(main, "14:35:08")
        self.assertEqual(sub, "2026-11-11  星期三")

    def test_build_lines_no_seconds(self):
        cfg = {"time": {"format": "HH:mm:ss", "showSeconds": False, "custom": ""}}
        main, sub = clock.build_lines(_NOW, cfg)
        self.assertEqual(main, "14:35")
        self.assertIsNone(sub)


class TestStylePack(unittest.TestCase):
    def test_builtin_twenty(self):
        expect = {"minimal", "lcd", "analog", "tech", "neon", "pop", "flip", "matrix",
                  "serif", "mono", "amber", "glitch", "caption", "float", "ink",
                  "ring", "frame", "dash", "twin", "thin"}
        self.assertEqual(set(stylepack.BUILTIN), expect)
        for name in stylepack.BUILTIN:
            pack, warns = stylepack.validate_pack(stylepack.get_builtin(name))
            self.assertEqual(warns, [])
            self.assertEqual(pack["effects"], [])

    def test_builtin_has_no_background(self):
        """用户明确要求：桌面上只允许出现时间文字，不允许任何背景板。

        踩过的坑：切预设时把 style.background.enabled 顺着预设打开，
        桌面先干净一秒、随后冒出一块半透明灰底。现在预设一律不带底色。
        """
        for name, pack in stylepack.BUILTIN.items():
            self.assertFalse(pack.get("bg", {}).get("enabled"), f"{name} 仍启用背景板")
            types = [d.get("type") for d in pack.get("decorations", [])]
            self.assertNotIn("backdrop", types, f"{name} 仍有 backdrop 底色层")
        # 指针不铺表盘面、翻页卡只描边不填充
        self.assertEqual(stylepack.BUILTIN["analog"]["face"]["opacity"], 0.0)
        self.assertEqual(stylepack.BUILTIN["flip"]["card"]["fill"], "none")

    def test_unknown_type_dropped(self):
        pack, warns = stylepack.validate_pack({"decorations": [
            {"type": "evil_script"}, {"type": "border", "width": 1}]})
        self.assertEqual(len(pack["decorations"]), 1)
        self.assertEqual(pack["decorations"][0]["type"], "border")
        self.assertTrue(warns)

    def test_limits(self):
        pack, warns = stylepack.validate_pack({
            "decorations": [{"type": "glow", "radius": 999}] * 12,
            "effects": [{"type": "breath"}] * 9,
        })
        self.assertEqual(len(pack["decorations"]), stylepack.MAX_DECORATIONS)
        self.assertEqual(len(pack["effects"]), stylepack.MAX_EFFECTS)
        self.assertEqual(pack["decorations"][0]["radius"], 24)
        self.assertTrue(warns)

    def test_no_effects_means_no_animation(self):
        pack, _ = stylepack.validate_pack({"text": {"size": 40}})
        self.assertEqual(pack["effects"], [])

    def test_bad_root_falls_back(self):
        pack, warns = stylepack.validate_pack([1, 2, 3])
        self.assertEqual(pack["name"], "极简")
        self.assertTrue(warns)

    def test_resolve_missing_pack(self):
        with IsolatedStore() as base:
            (base / "builtin").mkdir(exist_ok=True)
            cfg = defaults()
            cfg["style"]["packRef"] = "missing.dtstyle"
            pack, warns, notice = stylepack.resolve(cfg, store.STYLES_DIR, base / "builtin")
            self.assertIsNotNone(notice)
            self.assertEqual(pack["name"], "极简")

    def test_resolve_user_decorations_override(self):
        with IsolatedStore() as base:
            cfg = defaults()
            cfg["style"]["decorations"] = [{"type": "divider"}]
            pack, _, _ = stylepack.resolve(cfg, store.STYLES_DIR, base / "builtin")
            self.assertEqual(pack["decorations"][0]["type"], "divider")

    def test_export_and_reload(self):
        with IsolatedStore() as base:
            target = base / "builtin"
            stylepack.export_builtin_files(target)
            self.assertEqual(len(list(target.glob("*.dtstyle"))), 20)
            loaded, warns = stylepack.load_pack(target / "lcd.dtstyle")
            self.assertEqual(loaded["name"], "电子表")
            self.assertEqual(loaded["render"], "segments")
            self.assertEqual(warns, [])
            # 翻页卡配色同样是开放接口的一部分；"none" 表示只描边不填充
            flip, flip_warns = stylepack.load_pack(target / "flip.dtstyle")
            self.assertEqual(flip["render"], "flip")
            self.assertEqual(flip["card"]["fill"], "none")
            self.assertEqual(flip_warns, [])
            dots, dots_warns = stylepack.load_pack(target / "matrix.dtstyle")
            self.assertEqual(dots["render"], "dots")
            self.assertEqual(dots_warns, [])


class TestMonitors(unittest.TestCase):
    def setUp(self):
        self.mons = [
            Monitor(0, "DISPLAY1", 0, 0, 1920, 1080, 0, 0, 1920, 1040, 96, True),
            Monitor(1, "DISPLAY2", 1920, 0, 3200, 720, 1920, 0, 3200, 680, 144, False),
        ]
        self.cfg = defaults()
        self.cfg["position"]["margin"] = 24
        self.w, self.h = 300, 80

    def test_nine_positions_distinct(self):
        origins = {}
        for preset in POSITION_PRESETS:
            self.cfg["position"]["preset"] = preset
            origins[preset] = compute_origin(self.cfg, self.mons, self.w, self.h, 0)
        self.assertEqual(len(set(origins.values())), 9)

    def test_top_is_not_center(self):
        self.cfg["position"]["preset"] = "top"
        x, y = compute_origin(self.cfg, self.mons, self.w, self.h, 0)
        self.assertEqual(y, 0 + 24)  # rcWork.top + margin
        self.cfg["position"]["preset"] = "bottom"
        _, y2 = compute_origin(self.cfg, self.mons, self.w, self.h, 0)
        self.assertEqual(y2, 1040 - self.h - 24)

    def test_scale_on_second_monitor(self):
        self.cfg["position"]["preset"] = "top-left"
        _, y = compute_origin(self.cfg, self.mons, self.w, self.h, 1)
        self.assertEqual(y, 36)  # 24 * 1.5

    def test_clamp_and_monitor_at(self):
        self.assertLessEqual(clamp_to_screen(-500, -500, 100, 50, self.mons)[0], 0)
        self.assertEqual(monitor_at(2500, 300, self.mons), 1)

    def test_logical_origin_on_scaled_monitor(self):
        """回归：混合 DPI 定位必须用 Qt 逻辑工作区，物理坐标直给 move() 会二次缩放。

        实测双屏：#1 物理 work=(1920,0)-(3840,1008)@150%，
        Qt 逻辑 avail=(1920,0)-(3200,672)。旧 compute_origin 给 (2764,466)，
        Qt 映射后真实落点 (3186,699)，偏 (422,233)。
        """
        rects = [(0, 0, 1920, 1032), (1920, 0, 3200, 672)]
        scales = [1.0, 1.0]        # margin 落盘为逻辑像素，逻辑坐标系不乘 dpr
        divisors = [1.0, 1.5]      # 落盘物理偏移 ÷ dpr → 逻辑
        cfg = defaults()
        cfg["position"]["preset"] = "center"
        cfg["position"]["margin"] = 0
        x, y = anchor_origin(cfg, rects, scales, 231, 76, 1, divisors)
        self.assertEqual((x, y), (2444, 298))
        self.assertNotEqual(x, 2764)

    def test_custom_position_lands_where_dropped(self):
        """自定义落点存的是「相对该屏工作区左上角」的逻辑像素，两种坐标系都要还原。"""
        rects_logical = [(0, 0, 1920, 1032), (1920, 0, 3200, 672)]
        rects_phys = [(0, 0, 1920, 1032), (1920, 0, 3840, 1008)]
        cfg = defaults()
        cfg["position"]["mode"] = "custom"
        cfg["position"]["custom"] = {"x": 100, "y": 40}
        # Qt 逻辑坐标系：scales 全 1.0，原样相加
        self.assertEqual(anchor_origin(cfg, rects_logical, [1.0, 1.0], 231, 76, 1),
                         (1920 + 100, 0 + 40))
        # 物理坐标系：scales 传 dpr，逻辑像素 × dpr 才是物理距离
        self.assertEqual(anchor_origin(cfg, rects_phys, [1.0, 1.5], 231, 76, 1),
                         (1920 + 150, 0 + 60))

    def test_preset_anchor_is_immutable(self):
        """预设位置永久不变：切到 custom 再切回来，锚点必须分毫不动。

        旧实现把拖动位移塞进 offsetX/offsetY，锚点会被推走 —— 用户报的 bug。
        """
        rects = [(0, 0, 1920, 1032), (1920, 0, 3200, 672)]
        cfg = defaults()
        cfg["position"]["preset"] = "center"
        cfg["position"]["margin"] = 0
        before = anchor_origin(cfg, rects, [1.0, 1.0], 231, 76, 1)
        # 模拟一次自定义拖动，再切回预设
        cfg["position"]["mode"] = "custom"
        cfg["position"]["custom"] = {"x": 37, "y": 91}
        self.assertNotEqual(anchor_origin(cfg, rects, [1.0, 1.0], 231, 76, 1), before)
        cfg["position"]["mode"] = "preset"
        self.assertEqual(anchor_origin(cfg, rects, [1.0, 1.0], 231, 76, 1), before)

    def test_custom_mode_ignores_margin(self):
        """自定义落点是绝对位置，边距只服务预设锚点。"""
        rects = [(0, 0, 1920, 1032)]
        cfg = defaults()
        cfg["position"]["mode"] = "custom"
        cfg["position"]["custom"] = {"x": 10, "y": 20}
        cfg["position"]["margin"] = 200
        self.assertEqual(anchor_origin(cfg, rects, [1.0], 100, 50, 0), (10, 20))

    def test_logical_clamp_and_monitor_at(self):
        rects = [(0, 0, 1920, 1032), (1920, 0, 3200, 672)]
        self.assertEqual(monitor_at(2500, 300, self.mons, rects), 1)
        # 逻辑虚拟桌面外接框 = (0,0)-(3200,1032)
        self.assertEqual(clamp_to_screen(9999, 9999, 231, 76, self.mons, rects),
                         (3200 - 231, 1032 - 76))


class TestProfiles(unittest.TestCase):
    def test_safe_name(self):
        self.assertEqual(safe_name('a/b:c*d?'), "a_b_c_d_")

    def test_switch_and_undo(self):
        with IsolatedStore():
            pm = ProfileManager()
            current = defaults()
            current["time"]["format"] = "HH:mm"
            pm.save("会议", defaults())
            self.assertEqual(len(pm.list()), 1)
            new_data, _ = pm.switch("会议", current, "当前配置")
            self.assertEqual(new_data["time"]["format"], DEFAULTS["time"]["format"])
            self.assertTrue(pm.can_undo())
            restored, _ = pm.undo()
            self.assertEqual(restored["time"]["format"], "HH:mm")
            self.assertFalse(pm.can_undo())
            self.assertIsNone(pm.undo())

    def test_snapshot_full_not_delta(self):
        with IsolatedStore():
            pm = ProfileManager()
            current = defaults()
            current["position"]["offsetX"] = 777
            pm.save("A", defaults())
            pm.switch("A", current, "当前配置")
            info = pm.undo_info()
            self.assertEqual(info["snapshot"]["position"]["offsetX"], 777)
            self.assertIn("display", info["snapshot"])

    def test_invalidate_and_delete(self):
        with IsolatedStore():
            pm = ProfileManager()
            pm.save("B", defaults())
            pm.switch("B", defaults(), "当前配置")
            self.assertTrue(pm.invalidate("改动设置"))
            self.assertFalse(pm.can_undo())
            pm.delete("B")
            self.assertEqual(pm.list(), [])

    def test_duplicate_rename(self):
        with IsolatedStore():
            pm = ProfileManager()
            pm.save("C", defaults())
            new = pm.duplicate("C")
            self.assertTrue(new.startswith("C 副本"))
            pm.rename("C", "C2")
            names = [r["name"] for r in pm.list()]
            self.assertIn("C2", names)
            self.assertNotIn("C", names)


class TestStore(unittest.TestCase):
    def test_atomic_write(self):
        with IsolatedStore():
            store.atomic_write_json(store.SETTINGS_FILE, {"中文": "值"})
            self.assertEqual(store.read_json(store.SETTINGS_FILE)["中文"], "值")

    def test_corrupt_backup(self):
        with IsolatedStore():
            store.SETTINGS_FILE.write_text("{bad json", encoding="utf-8")
            data, error = store.load_raw_settings()
            self.assertIsNone(data)
            self.assertIn("已备份", error)
            self.assertEqual(len(list(store.APP_DIR.glob("*.corrupt-*"))), 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
