# Phase 1 验收用例

> 更新日期：2026-07-03
> 对应 `docs/task_plans/task_plan-phase1-最小可用版本.md` 第 6 节
> 单测：`cd backend && .venv/bin/python -m pytest tests/ -q`（23 passed）

## 单元测试用例（tests/）

| 文件 | 覆盖 | 结果 |
|---|---|---|
| `test_action_guard.py` | 用例 4/5：三层判定、无误报、支付拦截、登录接管 | ✅ 17 passed |
| `test_browser_tool.py` | 用例 6：超长页面截断、title/url 提取、uid 定位 | ✅ 6 passed |

## 端到端用例（真实站点，线上环境）

| # | 用例 | 输入 | 预期 | 实测结果 |
|---|---|---|---|---|
| 1 | 酒店公开页抽取 | Booking 酒店页 | HotelInfo（页面为搜索错误页时字段空属正常） | ✅ done，page_type=hotel |
| 2 | 攻略/百科页抽取 | 百度百科「东京都」 | TravelNote，含景点 | ✅ done，spots=[富士山,东京塔,浅草寺,明治神宫,皇居,银座] |
| 2b | 攻略/百科页抽取 | 百度百科「大阪」 | TravelNote，含景点 | ✅ done（线上外网提交） |
| 3 | 登录墙识别 | 小红书未登录正文页 | need_user_handoff（login_wall） | ✅ need_user_handoff：当前页面为 login_wall |
| 3b | 验证码/风控识别 | 马蜂窝攻略页 | need_user_handoff | ✅ need_user_handoff：当前页面为 captcha |
| 4 | 支付动作拦截 | 含「立即支付」按钮点击 | Action Guard BLOCK | ✅ 单测覆盖 |
| 5 | 无误报 | 整页含登录按钮但点普通元素 | ALLOW | ✅ 单测覆盖 |
| 6 | 超长页面截断 | >30k chars snapshot | 截断生效不报错 | ✅ 单测覆盖 |
| 7 | 结构化输出校验 | DeepSeek 抽取 | 通过 Pydantic 校验 | ✅ parse() 实测通过 |

## 结论

Phase 1 **初步完整**：单测全过 + 端到端在本地和线上环境均跑通，
Action Guard 三层判定、登录墙/验证码识别、结构化抽取全部符合预期。

## 已知边界（非阻塞，留待后续 Phase）

- Booking 直链常跳转搜索错误页（反爬）→ Phase 2 走保底路径（搜索引擎 + 地图）
- 马蜂窝/携程有验证码风控 → 已正确识别为 need_user_handoff，符合安全设计
- 攻略类页面 tips/restaurants 抽取依赖页面本身信息密度，百科页偏结构化、tips 常为空
