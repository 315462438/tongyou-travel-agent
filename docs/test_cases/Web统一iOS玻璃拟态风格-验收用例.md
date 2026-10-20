# Web 统一 iOS 玻璃拟态风格 · 验收用例

- 日期：2026-10-19
- 计划：`docs/task_plans/Web统一iOS玻璃拟态风格-2026-10-19.md`
- 自动化：`frontend/tests/visual-regressions.test.mjs`（单主题 / 玻璃材质 / 光晕 / 降级）、
  `frontend/tests/interaction-utils.test.mjs`（布局模式，主题函数已随双主题移除）

## 一、单一主题（用户决定）

| # | 用例 | 预期 | 自动化 |
| --- | --- | --- | --- |
| 1 | 顶栏不再出现「现代主题/水墨主题」按钮 | `Home.tsx` 无 `theme-toggle` / `themeMode` / `travel_theme_mode` | ✅ `single glass theme: theme switch removed, iOS glass material in place` |
| 2 | 样式表无 `.theme-ink` 残留 | `index.css` 不含 `.theme-ink` | ✅ 同上 |
| 3 | 水墨背景图不再被引用 | `index.css` 不含 `ink-landscape` | ✅ 同上 |
| 4 | 根节点 class 只含布局模式 | `app view-{layoutMode}`（无 `theme-*`） | 人工 / 构建 |

## 二、玻璃材质与光晕

| # | 用例 | 预期 | 自动化 |
| --- | --- | --- | --- |
| 5 | 玻璃 token 存在 | `--x-glass: rgba(255,255,255,.62)`、`--x-glass-blur: 24px` | ✅ |
| 6 | 工具类可复用 | `.glass` 带 `backdrop-filter: blur(var(--x-glass-blur))`；`.glass-pill` 全圆角；`.glass-input` ≥50px 高；`.glass-primary` sky 渐变 | ✅（`.glass` / `.glass-pill`） |
| 7 | 三色光晕与 iOS 同色 | `--x-aura-sky #2563EB 22%` / `--x-aura-dusk #6B5CF2 16%` / `--x-aura-warm #FA9E5C 14%` | ✅ |
| 8 | 光晕铺满 app 背景 | `.app::before` 含 `radial-gradient` 且 `z-index:-1` | ✅ |
| 9 | 主区透明露出光晕 | `.main { background: transparent }` | 人工（视觉） |

## 三、登录页（iOS `LoginView` 同款）

| # | 用例 | 预期 |
| --- | --- | --- |
| 10 | 结构 | 品牌区（76px 图标 + wordmark + 副标）+ 一枚玻璃卡（分段控件 + 账号/密码/邀请码胶囊输入 + 全宽主按钮） |
| 11 | 交互不变 | 登录/注册分段切换、注册时出现邀请码、错误提示、loading 态、成功后回调 `onAuthed` |
| 12 | 备案号保留 | 页脚「鄂ICP备2026020535号-2」链工信部（工信部硬性要求） |
| 13 | 无 WebGL | 不再引用 `SideRays`；组件文件已删除 |
| 14 | 移动端 | 390px 宽无横向滚动；输入框字号 16px 防 iOS 聚焦缩放 |

## 四、首页空态

| # | 用例 | 预期 |
| --- | --- | --- |
| 15 | 输入卡 | 玻璃卡（`--x-glass` + 30px 圆角 + 白内高光 + sky 投影），focus 时 sky 描边 |
| 16 | 主按钮 | 胶囊 + sky 纵向渐变 + 内高光 |
| 17 | eyebrow / 城市胶囊 | 玻璃胶囊（半透明白 + 14px 模糊） |
| 18 | hero 文字 | 保留原有渐变大标题（`visual-regressions` 断言不变） |

## 五、会话页

| # | 用例 | 预期 |
| --- | --- | --- |
| 19 | 用户气泡 | sky 淡染玻璃 + 22px 圆角（右下小角），半透明 |
| 20 | composer | 玻璃输入条 24px 圆角 + 白内高光，focus sky 描边 |
| 21 | 移动端底栏 | 半透明玻璃 + `env(safe-area-inset-bottom)` 安全区 |
| 22 | 卡片 | 登录墙卡 / 记忆卡 / 来源胶囊 / 候选目的地卡为玻璃 |
| 23 | 思考行 | 展开区左竖线改 sky 淡色（保持轻量，不加大底卡） |

## 六、降级与可访问性

| # | 用例 | 预期 | 自动化 |
| --- | --- | --- | --- |
| 24 | 不支持 backdrop-filter | `@supports not (...)` 提高不透明度到 .94 | ✅ |
| 25 | 减少透明度 | `prefers-reduced-transparency: reduce` 去模糊、改实底 .97 | ✅ |
| 26 | 全屏弹窗 | 必须 portal 到 body（`backdrop-filter` 会改 fixed containing block） | 人工（既有规范） |
| 27 | 减少动效 | `prefers-reduced-motion` 下光晕/卡片动画关闭 | 人工（既有规则） |

## 七、构建与回归

| # | 用例 | 预期 |
| --- | --- | --- |
| 28 | 前端测试 | `npm test` 100/100 通过 |
| 29 | 构建 | `npm run build` 通过（无 TS 错误） |
| 30 | CSS 语法 | `{`/`}` 与 `/*`/`*/` 数量相等 |
| 31 | 死代码 | `.auth-sky` / `.pass-*` / `.stub-*` / `SideRays` 全部移除且无引用 |

## 八、评审后真实浏览器回归

本地 `npm run build && npm run preview -- --host 127.0.0.1 --port 4179`，所有业务请求均 mock，不写实际账号和行程。
设置 `PLAYWRIGHT_MODULE` 为可用 Playwright ESM 路径，分别运行 `npm run test:glass`、`npm run test:workspace`、`npm run test:ledger`。

- `glass-browser.mjs`：390/1440 宽；SVG 加载 naturalWidth > 0；品牌文字与浅色背景对比度 ≥4.5；注册表单错误可见；无横向溢出；减少透明度后共享玻璃与普通弹窗 backdrop-filter 均为 none。
- `workspace-browser.mjs`：390×844 / 1440×1000；日期浮层为 body portal，有背景与描边，桌面靠近触发按钮，宽度不超过 300px；手机不超视口；Escape 恢复焦点，取消与日期保存可用；桌面抽屉 ≥680px，手机贴边；检查内部每个输入/按钮/下拉控件水平边界，避免“外层不溢出、内部已经裁切”漏检；内部滚动后底部操作仍可见。
- `ledger-browser.mjs`：原快速记账、幂等重试、汇率异常、日期分组与删除/退出用例；新增减少透明度下顶栏、总额、账单卡及确认弹窗不模糊。
- 浏览器媒体设置和 React portal 位置更新后等待计算样式/坐标满足实际条件，不用固定 sleep 假定绘制完成。
- 抽屉底部操作除几何边界外，用 elementFromPoint 检查是否被固定导航遮挡；费用单选保持正常尺寸，减少动效模式不播放抽屉入场动画。
