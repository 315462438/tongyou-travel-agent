# 踩坑：后端生成的资源 URL 要相对于前端 `API` 常量，不能自己带 "/api" 前缀

Phase 27c 加沙箱产物下载链接时，第一版后端直接拼了
`f"/api/sandbox-artifacts/{batch_key}/{name}"` 存进 `meta.artifacts[].url`，本地开发看起来
没问题，但线上会 404——生产环境经 nginx 反代在 `/travel/` 路径下（见 CLAUDE.md「线上体验
地址」），前端 `frontend/src/api.ts` 里 `API = '/travel/api'` 已经包含了 `/api` 这一段，
所有现有用法都是 `` `${API}/xxx` ``（比如 handoff-screenshot 是
`` `${API}/chat/${cid}/handoff-screenshot` ``）——如果后端存的 `url` 字段自己也带
`/api/` 前缀，拼出来就变成 `/travel/api/api/sandbox-artifacts/...`，路径多了一段
`api`，请求 404。

## 解法
后端存的 URL 字段只放**相对于 `API` 常量的那一段**（不带 `/api` 前缀，比如
`/sandbox-artifacts/{batch_key}/{name}`），前端固定用 `` `${API}${item.url}` `` 拼出
完整地址，跟项目里其余"后端生成路径片段、前端拼 API 前缀"的用法保持一致。

## 推广
前后端分离项目里，如果后端要把"指向自己某个端点的路径"写进返回数据（而不是完整 URL），
必须跟前端约定好这个路径片段到底是"相对站点根"还是"相对某个已经包含部分前缀的 base
常量"——两边对不齐的这类 bug 在本地开发（没有反代前缀）时完全测不出来，只有部署到带
反代路径前缀的生产环境才会暴露，建议新增此类字段时直接去翻一下前端已有的同类用法
（比如全局搜索 `${API}`）照抄用法，而不是凭直觉自己拼。
