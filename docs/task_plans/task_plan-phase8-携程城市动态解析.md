# Task Plan — Phase 8：携程城市 ID 动态解析（任意城市上携程）

> 创建：2026-07-06　状态：已完成并上线

## 背景（用户反馈）

「酒店怎么选择」（目的地开封）没有触发携程——静态城市 ID 表只覆盖 14 个
人工验证的大城市，开封等地级市直接静默回退搜索。

## 方案演进（记录探索路径，供后来者避坑）

1. ❌ UI 自动化点建议下拉：携程反爬脚本校验 `event.isTrusted`，合成 click/
   pointer/keyboard 事件全部无效；a11y 树里建议项是 StaticText（不可交互节点），
   mcp 原生 click 过不了 puppeteer 可交互性检查；fill 尾随 `\n` 的 Enter 也无效。
2. ✅ **接口直调**：劫持页面 fetch 抓到城市建议接口
   `POST m.ctrip.com/restapi/soa2/34951/getHotelKeywords`（CORS 允许
   hotels.ctrip.com 源），载荷格式简单（keyword + head 元数据）。
   在携程页面上下文 `evaluate_script` 直调，响应里 `typeName=城市` 条目的
   `keywordId` 即列表页 `?city=` 的数字 ID（开封=331，已验证 city=331 页面
   即开封酒店列表）。

## 最终实现

- `BrowserTool.resolve_ctrip_city(city)`：打开任一携程列表页（提供源/cookie）→
  页面内 fetch 建议接口 → 解析城市条目 keywordId。
- 三级解析：`CTRIP_CITY_IDS` 静态表 → `travel_ctrip_city` DB 缓存 →
  动态解析（成功即落库，一个城市只解析一次）。
- 解析失败：progress 明确提示「携程暂无法定位，改用公开搜索来源」（不再静默）。

## 验收

- 线上「开封酒店 预算300」：定位开封 → 抓 8 家带实价酒店（¥277-456，
  清明上河园商圈）→ DB 缓存 `开封=331`。88 tests passed 无回归。

## 同批稳定性修复

- MCP 三层自愈：45s 调用超时 → 重建会话重试 → （远程模式）杀常驻 Chrome
  由 systemd 拉起新实例再重试（反复 attach 会把 Chrome 本体搞僵）。
- 进程级 MCP 串行锁：并发 MCP 客户端连同一浏览器会互相搞死 CDP 会话。
- 必应导航异常时不再跳过 360 兜底。
