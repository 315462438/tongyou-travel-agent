# Task Plan — Phase 53（清单批6）：P2 收尾 + admin 口令强改（P1）

清单最后一批是 P2 杂项集合 + 一个 P1 安全项。按价值/自成一体挑了 5 项做，2 项显式延后。

## 已完成

### admin 默认口令强改（P1 安全）
- `auth_api._must_change_password(user)`：is_admin 且当前口令仍等于引导默认 `admin123` → True。
- `_issue`/`me` 返回 `must_change_password`；新增 `POST /api/auth/change-password`
  （校验旧口令、新口令≥6位、admin 新口令不得仍为默认；改密后清其它会话、返回新 token）。
- 前端：`AdminPasswordBanner` 顶部横幅（仅 must_change 时显示），内联「原/新密码」表单 → 改密成功
  换 token + 横幅消失（App 的 onPasswordChanged 置 must_change=false）。token/must_change 透传
  App↔Auth↔Home。

### 高原/健康建议去绝对化（P2 安全）
- `context_security.HEALTH_POLICY`：涉及高反/身体/饮食/风险活动的建议不绝对化（禁「绝对安全/一定
  没事/保证不高反」），说明因人而异、给通用预防、提醒基础病/孕老幼及不适就医、不替代专业医疗。
  追加到 ITINERARY/HOTEL/DIRECT 三个 system prompt。

### 历史会话标题去重（P2）
- `chat_api.list_conversations`：同名会话从第 2 个起附 `· MM-DD` 区分，侧栏不再一片同名。

### 地图默认中心 = 首个有坐标的日（P2）
- `Trips.tsx`：首次载入用 `didInitDay` ref 把 `selectedDay` 定位到第一个有坐标的地点所在天，
  避免开局选中无坐标的 Day1 → 地图空白/居中在别处。

### 长行程左栏折叠非当前日（P2）
- `Trips.tsx`：timeline 只展开当前日的地点+加点框，其余天折叠成日头（计数带 ▸，点击展开）；
  拖拽仍可落到折叠日（section onDrop 不受影响）。15 天行程不再是一条巨长滚动。

## 显式延后（价值相对低 / UI 工作量大，单开一轮再做）
- **阶段进度条**：把 progress 文本流升级成分阶段进度条（解析→搜索→生成→自检）。需要后端给每条
  progress 打 stage 标签 + 前端进度条组件，改动面大，收益是观感，暂缓。
- **携程侧抽屉回板**：携程实价查询做成板内侧抽屉、查完一键回协同板。现走「新会话 askInChat」已可用，
  侧抽屉是体验优化，暂缓。

## 验收
- `test_auth.py`：must_change 标志（默认口令/改后/非 admin）、change_password（旧密错/短/仍默认/正常）、
  标题去重——全过。
- 全量 pytest 399 通过；前端 tsc 通过、构建通过；线上部署健康。
- 说明：server 若已在 .env 设了自定义 ADMIN_PASSWORD，横幅不显示（正确）；仍用 admin123 才提示。
