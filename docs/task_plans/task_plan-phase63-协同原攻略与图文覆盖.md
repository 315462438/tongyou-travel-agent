# Phase 63：协同原攻略与图文覆盖

## 目标

1. 协同行程的所有已加入成员都能查看导入该行程的原攻略，不再跳入仅创建者有权限的私人会话。
2. 创建者仍可从原攻略预览返回自己的来源对话。
3. 小红书笔记图片进入攻略配图库，让新生成的攻略稳定获得更丰富的正文配图。
4. 图片代理保持域名白名单与内容类型校验，不把服务变成开放代理。

## 方案

### 协同原攻略

- 新增行程成员权限下的只读原攻略接口，只返回被导入的 assistant 消息正文、引用来源与必要标识。
- 协同板把“回到来源对话”改为“查看原攻略”，在板内打开 Markdown 预览抽屉。
- 仅创建者在预览中额外看到“回到原对话”；普通成员不会访问创建者的私人聊天接口。
- 原攻略缺失时返回明确的 404 文案，不暴露其他会话信息。

### 小红书配图

- 解析小红书详情返回的图片列表，过滤非 HTTP(S)、去重并限制每篇数量。
- 将图片以 `source.images` 形式接入现有 `_build_image_context`，并标记为“小红书灵感图”。
- 图片代理白名单加入小红书官方 CDN 域名；代理请求补充必要请求头。
- 调整配图提示与终稿兜底：优先在对应主题/来源相关段落插入，限制总数，避免堆图和错配。

## 涉及模块

- `backend/app/api/trip_api.py`
- `backend/app/tools/xhs_mcp.py`
- `backend/app/api/img_api.py`
- `backend/app/agent/orchestrator.py`
- `frontend/src/pages/Trips.tsx`
- `frontend/src/index.css`
- `backend/tests/test_trip_collab.py`
- `backend/tests/test_xhs_mcp.py`
- `backend/tests/test_images.py`
- `frontend/tests/visual-regressions.test.mjs`

## 验收标准

1. owner 与 editor 均可通过协同板读取同一份原攻略。
2. editor 无法读取或切换到 owner 的私人会话；非成员仍返回 404。
3. 原攻略预览能正确渲染 GFM 表格、图片和来源链接，并可关闭。
4. 小红书详情含图片时，来源对象带经过限制与去重的 `images`；无图或结构异常时正常降级。
5. 小红书 CDN 图片可通过同源代理加载，非白名单域名继续拒绝。
6. 后端相关自动化测试、前端 Node 测试、lint 与 production build 全部通过。

## 完成记录

- 已完成成员级只读原攻略接口与响应字段收敛；owner/editor/非成员权限测试通过。
- 已完成协同板原攻略抽屉、GFM 表格/图片/来源渲染和移动端适配。
- 已按线上真实样本接入小红书 `imageList/urlDefault`，并完成限量、HTTPS、白名单代理和分散兜底。
- 后端全量 457 项、前端 15 项、lint 与 production build 全部通过。
- 已部署到线上；真实 owner/editor 权限、公开笔记采图和图片代理均验证通过。
