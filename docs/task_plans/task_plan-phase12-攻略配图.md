# Task Plan — Phase 12：攻略中插入图片（景点图 + 酒店图）

> 创建：2026-07-07　状态：已完成并上线（验收见 docs/test_cases/phase12-验收用例.md）

## 需求

在生成的攻略/酒店推荐里插入相关图片（风景图、酒店图）。

## 图源（均已验证可热链，无需 referer，本地/服务器都能取）

- **景点图**：高德 POI `photos` 字段（每个 POI 3 张，`store.is.autonavi.com` /
  `aos-comment.amap.com`，http/https）。
- **酒店图**：携程卡片 `<img>`（`dimg04.c-ctrip.com` webp，https）。

## 方案

### 图片注入用「占位符」而非让 LLM 写网址

长 URL 让模型直接写进 Markdown 易被截断/幻觉。改为：
1. 收集图片清单 `[{name, url}]`（景点来自高德、酒店来自携程卡片）。
2. 生成 prompt 追加「可插入图片」清单（只给名称），系统提示指示模型在相关位置插
   `[[img:名称]]` 占位符（名称须完全一致，禁止写网址）。
3. 生成后（含流式每次 flush）后处理 `_embed_images`：把 `[[img:名称]]` 替换为
   `![名称](/travel/api/img?u=<代理URL>)`（精确匹配→包含匹配，匹配不到则删占位符）；
   流式中额外剥掉行尾未闭合的 `[[img:` 残片，避免闪烁。

### 图片代理（同源 + 导出长图可用 + 防 SSRF）

新增 `GET /api/img?u=<url>`：仅放行 autonavi.com/amap.com/c-ctrip.com/tripcdn.com
（host 后缀白名单），流式转发图片字节 + 一天缓存。作用：
- 高德是 http 图，走同源代理避免将来 https 混合内容；
- html2canvas 导出长图时图片同源，不污染 canvas（否则 toDataURL 抛异常）。

## 涉及模块

- `app/tools/amap.py`：build_amap_source 附带 `images`（POI 首图）。
- `app/tools/browser_tool.py`：CTRIP_CARDS_JS 增加 `img` 字段。
- `app/agent/site_router.py`：携程来源附带 `images`（酒店卡首图，过滤广告）。
- `app/agent/orchestrator.py`：聚合各来源 images → prompt 清单 + `_embed_images`
  后处理（流式 flush/终稿都过）；系统提示加占位符规则。
- `app/api/img_api.py`（新）+ `app/main.py` 注册。
- 前端 `index.css`：`.md img` 样式；`Home.tsx`：html2canvas `useCORS: true`。

## 验收标准

1. 「黄山路线」类查询：攻略正文内嵌 ≥2 张景点图，图片正常显示。
2. 含酒店的查询：酒店推荐处内嵌对应酒店图。
3. 导出长图包含图片（不再因跨域空白/报错）。
4. 图片代理拒绝白名单外域名（防 SSRF）。
5. 无图片可用时攻略正常生成（占位符全清、无残留）。
6. 单测：占位符替换（精确/模糊/无匹配/流式残片）、代理白名单、amap/ctrip images 组装；存量不回归。
