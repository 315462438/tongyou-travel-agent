# Task Plan — Phase 54：真实使用回归问题收敛

## 目标

根据武汉→拉萨 15 天真实使用回归，修复“攻略生成完整但导入后信息断层”的核心问题，
并统一路线检查、住宿判断和前端展示的数据口径。

## 问题与方案

### 1. 标准规划误入快速通道

- `direct` 继续走快速回答；`guide` 无论深度开关是否开启，都走联网攻略流水线；
- `research` 仍由深度开关控制，关闭时快速回答并显示一键深度重试。
- 对“天数 + 路线/酒店/预算”的完整单方案规划增加确定性识别，分类模型即使误判为 `direct`
  也强制进入 `guide`；多目的地对比仍保留 `research` 语义。
- 当前用户消息优先于历史/长期记忆，明确的目的地、天数、预算、交通方式不得被旧记忆覆盖，
  未在本轮出现的兴趣不得进入搜索词或正文；完整新规划会在注入前过滤旧“当前行程”和兴趣记忆。

### 2. 攻略结构化导入补全

- `DraftStop` 增加 `transport`，表示从上一地点到当前地点的交通方式；
- `TripDraft` 增加：
  - `day_plans[day,type,overnight_required,overnight_city]`；
  - `hotel_options[city,hotel,price,source,note]`；
- 导入读取完整攻略（上限提高），要求 Day 范围拆成逐日结构并覆盖全部明确地点；
- 行程保存 `day_plan_json`、`hotel_recommendations_json`，住宿面板按结构化过夜城市判断，
  不再用“当天最后一个景点所在城市”猜住宿；
- 明确入住的酒店仍落 `🏨 stop`，备选酒店进入“攻略推荐酒店”，用户可一键加入当前日。

### 3. 路线检查统一交通口径

- 抽出统一的逐腿交通推断：目标 stop 明确交通优先，否则 ≤3km 步行、>3km 驾车；
- `segment-times` 与检查中心共同复用；
- 步行告警只累计实际判定为步行的腿，详情展示交通方式，不再把驾车里程计入步行。

### 4. 预算与交互显示

- “门票合计”改为“景点票价已录入”，与“计划门票”区分；
- 导入后给出持续可见的成功状态；
- 行程操作弹层邀请区域改为 grid，按钮不得超出弹层或视口。

### 5. 健康建议

- 系统提示明确禁止主动推荐具体药物、保健品以及“几天不能洗澡”等绝对规则；
- 只给渐进适应、减少剧烈活动、观察症状、必要时下撤/就医等通用建议。

## 涉及模块

- `backend/app/agent/deep_research.py`
- `backend/app/agent/context_security.py`
- `backend/app/agent/orchestrator.py`
- `backend/app/agent/trip_planner.py`
- `backend/app/api/trip_api.py`
- `backend/app/db/models.py`、`backend/app/db/migrate.py`
- `frontend/src/pages/Home.tsx`、`frontend/src/pages/Trips.tsx`
- `frontend/src/index.css`

## 验收标准

1. 普通模式提交“15 天路线+酒店+预算”直接进入 `guide`，不再出现快速模式提示；
2. 导入后预算分类、酒店候选、逐日过夜城市和交通方式保留；火车过夜/返程日不查酒店；
3. 羊湖一日游返回拉萨时，住宿城市仍为拉萨；
4. “步行 3km + 驾车 6.9km”不产生 10km 步行告警；
5. 计划门票与已录入景点票价标签无歧义；
6. 1280px 宽度下邀请按钮完整位于弹层内；
7. 新增自动化测试通过，后端全量 pytest、前端 test/lint/build 全部通过。
