# Phase 63：协同原攻略与图文覆盖验收用例

## 自动化用例

### 后端

1. `test_source_guide_is_visible_to_members_but_private_chat_stays_private`
   - owner 可读取原攻略并得到返回原对话标识。
   - accepted editor 可读取同一份原攻略，但不获得来源会话入口。
   - 非成员仍得到 404。
   - 非 HTTP(S) 来源链接不会被透传。
2. `test_parse_detail_real_shape`
   - 兼容线上 `imageList/urlDefault/urlPre`。
   - HTTP CDN 地址升级为 HTTPS；非法协议丢弃；每篇最多两张。
3. `test_collect_assembles_sources_and_skips_short`
   - 小红书来源把图片整理为统一 `images[{name,url}]`。
4. `test_build_image_context`
   - 高德、携程、小红书三类图片均进入配图上下文并保持分类提示。
5. `test_xhs_fallback_distributes_across_guide_sections`
   - 模型漏放占位符时，小红书灵感图被分散到不同章节。
6. `test_proxy_whitelist`
   - 官方 `xhscdn.com` 放行；伪造后缀、内网地址与任意域名继续拒绝。

### 前端

1. `trip members can read the imported guide without entering the owner private chat`
   - 存在成员只读抽屉、成员接口、GFM 渲染、图片样式和 owner 专属返回入口。
2. 全部交互回归测试、lint、TypeScript/Vite production build 通过。

## 手工/线上验收

1. 创建者打开协同板 → 行程操作 → 查看原攻略：抽屉正常显示 Markdown 表格、配图、来源。
2. 另一账号通过分享链接加入同一行程，执行同样操作：能看原攻略，不出现“回到我的原对话”。
3. 非成员直接请求 source-guide：返回 404。
4. 新生成一份使用小红书来源的攻略：正文至少出现分散的图片，图片能经 `/travel/api/img` 加载。
5. 手机宽度下原攻略抽屉全屏，内容可滚动、图片不横向溢出、关闭按钮可用。

## 执行结果

- 后端针对性测试：78 passed。
- 后端全量测试：457 passed（仅 1 条 TestClient 弃用告警）。
- 前端 Node 测试：15 passed。
- 前端 lint：通过。
- 前端 production build：通过。
- 线上真实成员验收：2 位 editor 均为 `200 / can_open_conversation=false`，owner 为
  `200 / can_open_conversation=true`，三者读取到同一份 3639 字原攻略。
- 线上小红书图片代理：`200 image/webp`（448926 bytes）。
- 线上采集链路：1 篇公开笔记解析 2 张图片，2 张均进入攻略图片上下文。
