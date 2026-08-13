# Phase 64：旧攻略补图与阅读排版验收用例

## 自动化用例

### 后端

1. `test_image_refresh_intent_is_explicit`
   - “补图片/图文版/配图”命中；普通“拍照机位”不命中。
2. `test_refreshed_images_merge_into_old_sources_without_duplicates`
   - 同 URL 补图片不重复，新有图来源追加，空图来源丢弃。
3. `test_collect_revision_with_image_request_forces_xhs_refresh`
   - 多轮修改本可复用来源时，图片意图仍强制调用小红书刷新。
4. `test_xhs_fallback_can_cover_five_day_sections`
   - 六张候选图最多插五张，覆盖五个 Day 章节且不连续堆叠。
5. 原有图片占位符、代理白名单、来源安全和 LangGraph 流程测试继续通过。

### 前端

1. `guide reading view has semantic title, day cards, responsive tables, and large images`
   - 攻略正文使用专用语义类。
   - 标题卡、Day 卡、普通章节层级明确。
   - 表格容器支持横向滚动。
   - 图片使用完整展示而非强制裁切。
2. Node 交互测试、lint、TypeScript 与 production build 全部通过。

## 手工/线上验收

1. 在旧的 0 图攻略后输入“补一下各个行程中的图片”，进度应出现“刷新小红书图片”。
2. 新回复最终 Markdown 图片数应大于 0；五日攻略有足够来源时应有 5 张分散图片。
3. 图片请求经 `/travel/api/img` 返回 200 与正确 `image/*` Content-Type。
4. 当前线上目标消息直接回填后，刷新页面即可看到图片。
5. 桌面端标题、Day、表格、图片层级清晰；手机端表格可滑动，页面不横向溢出。

## 本地执行结果

- 后端针对性测试：43 passed。
- 后端全量测试：461 passed（仅 1 条 TestClient 弃用告警）。
- 前端 Node 测试：16 passed。
- 前端 lint：通过。
- 前端 production build：通过。
- 线上目标回复：候选图片 10 张，Markdown 图片由 0 回填为 5。
- 线上五张图片代理：全部返回 `200 image/webp`，大小分别为
  508212、483220、31518、149982、449608 bytes。
- 线上入口已使用新版排版 CSS：`index-BT3W7hrT.css`。
