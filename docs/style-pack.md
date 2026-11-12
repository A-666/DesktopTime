# `.dtstyle` 样式包格式

`schema` 固定 `desktoptime.style/v1`。**纯数据文件**：不执行脚本、不解析表达式、不加载远程 URL、不加载外部字体文件。

放置位置：`%APPDATA%\DesktopTime\styles\*.dtstyle`，重启设置界面即可在「03 外观样式」里看到。

## 渲染顺序（严格）

```
stack → text → outline → shadow / glow → backdrop → ring → border → effects
```

数组顺序即叠放顺序；同类型可重复；后写盖上层。

## 顶层字段

| 字段 | 取值 | 说明 |
|---|---|---|
| `render` | `text` / `segments` / `analog` / `flip` / `dots` | 主行怎么画，缺省 `text` |
| `face` | `{ fill, opacity }` | 仅 `analog` 用；`opacity = 0` 表示只画一圈表盘线 |
| `card` | `{ fill, edge, radius }` | 仅 `flip` 用；翻页卡的底色 / 描边 / 圆角 |
| `segmentGhost` | HEX 或 `""` | 仅 `segments` 用；未点亮段的残影色，空串不画 |
| `text` | `{ font, size, weight, color }` | 缺项由「极简」补齐 |
| `bg` | `{ enabled, color, padding }` | 整块背景板（内置样式全部关闭） |

五种渲染模式：

- `text` —— 字形轮廓，任意本机字体。
- `segments` —— 七段数码管，逐段绘制（`0-9 . : - 空格`），不依赖字体。
- `analog` —— 圆形表盘 + 12 刻度 + 时分秒三针，不画数字；日期 / 星期居中压在表盘正下方。
- `flip` —— 翻页卡，每位一张卡，中缝横向切断数字，两侧各一个铰链块；几何由 `card` 控制。
- `dots` —— 先按点距的倒数把文字缩绘成小位图，再逐格取样生成圆点，任意字体都能转成 LED 点阵。点距 = 字号 × 0.045，点半径 = 点距 × 0.40。

## decorations[]

| type | 参数 | 约束 |
|---|---|---|
| `border` | `style`(solid/dashed/dotted), `width`, `color`, `padding` | width 1–4；零圆角；`padding` 是框到**字框**的间距，不是画布边距 |
| `outline` | `width`, `color` | width 1–6；比较色，**不跟随字色** |
| `glow` | `color`, `radius`, `opacity` | radius ≤ 24；opacity ≤ 0.6 |
| `shadow` | `color`, `blur`, `offsetX`, `offsetY`, `opacity` | blur ≤ 24；大偏移 + opacity 1 即硬投影 |
| `backdrop` | `color`, `opacity`, `padding`, `inset` | opacity ≤ 0.95 |
| `divider` | `position`(top/bottom/left/right), `width`, `color`, `length` | width 1–3 |
| `ring` | `mode`(progress/second/minute), `width`, `color`, `trackColor`, `size`, `gap` | `size` 实际生效值 = `min(size, 400, 画布高 - 10)` |
| `stack` | `lines`(main/sub), `align`, `gap`, `subFormat`, `subSize`, `subColor` | 最多 2 行 |
| `bracket` | `width`, `length`, `color`, `padding` | 四角 L 形括号；width 1–6，length 4–160 |

### `color: "auto"`

`border` / `bracket` / `divider` / `ring` / `glow` 与 `card.edge` 支持写 `"auto"`，表示跟随 `style.color` —— 用户改文字颜色时，边框、括号、虚线框、进度环、翻页卡描边一起变，不会出现「白字配青框」。

`ring.trackColor: "auto"` 会额外降到 28% 透明度当轨道。

`outline` / `shadow` **不支持** auto：它们是层次不是边框（字幕靠黑描边压住白字、墨字靠白描边衬深字），跟着变等于把层次抹平。

## effects[]

| type | 参数 | 约束 |
|---|---|---|
| `breath` | `duration` 800–6000ms, `minOpacity` 0.3–1, `easing` | |
| `fade` | `duration`, `from`, `to`, `loop` | |
| `pulse` | `duration`, `scale` 1–1.15 | |
| `blink` | `onMs`, `offMs` | |

单文件上限 8 个装饰 + 4 个特效，超限截断并记 warning（不整包拒绝）。动画帧率 ≤ 30fps；不写 `effects` 即无动画。加载失败或校验不通过 → 回落内置「极简」，并在 03 页提示一次。

## 写法建议

- 画布留白要吃掉「会画到字框外」的图层：`pad ≥ max(backdrop.padding, bracket.padding + bracket.width + 2, glow.radius + 6, outline.width + 6, |shadow.offset| + 6)`，否则发光 / 描边 / 投影 / 四角括号会被画布切边。
- 装饰层写 `"auto"` 而不是写死色值，用户换字色时才不会撞色。
- 主行与副行都以较宽那行的宽度为基准居中，不需要自己算偏移。
