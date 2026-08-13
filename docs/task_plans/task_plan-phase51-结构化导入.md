# Task Plan — Phase 51（清单批3）：攻略结构化导入（住宿 + 预算）

## 背景
「攻略导入协同行程」现在只抽 stops[day,name,note]，把攻略里明确写的**每晚住宿**（酒店/价格/来源）
和**预算拆分**（住宿/交通/餐饮/门票/大交通/其他）都丢了。导入后住宿面板全「未定」、预算面板只有一个
总额输入框。本批让导入把这两类结构也带进来，直接落到住宿面板 + 预算面板。

## 方案（尽量复用现有模型，少加 schema）

### 住宿 → 复用 TravelTripStop 的 🏨 约定
- 攻略里每晚酒店 → 建一条 stop：`name="🏨 {酒店名}"`、`note` 带「住宿 · 来源」、
  `ticket_price=价格/晚`、`location=`该城 geocode（拿不到留空）、`order_no=90+`（排在当天景点后）。
- 住宿面板 `isStay`（note 含🏨/住宿）天然识别 → 「每晚住哪」直接显示酒店名；
  本批再让该行显示 `¥价格/晚`（读 stay stop 的 ticket_price）。
- 无新表：酒店同时出现在时间线和住宿 tab，和 Phase 48 手动订房产物一致。

### 预算拆分 → TravelTrip 新增 budget_breakdown_json
- 新列 `budget_breakdown_json TEXT`（JSON dict：类别→金额，类别限
  住宿/交通/餐饮/门票/大交通/其他）。migrate.py 幂等 ADD COLUMN。
- 导入抽到预算项 → 归一到这 6 类累加落 json；`trip.budget` 未设时置为总额。
- `_trip_detail` 返回 `budget_breakdown`（dict）。
- 前端费用 tab：总额输入框上方渲染「计划预算（按类别）」——每类金额 + 合计，无数据则不显示。
  与 LedgerPanel（实际 AA 记账）并列：一个是计划、一个是实际。

### 抽取
- `TripDraft` 加两个**选填**字段（默认空，seed 链路不受影响）：
  `stays: list[DraftStay]`、`budget_items: list[BudgetItem]`。
  - `DraftStay{day:int, city:str="", hotel:str="", price:float|None, source:str=""}`
  - `BudgetItem{category:str, amount:float}`（category 归一到 6 类，未知→其他）
- `IMPORT_SYSTEM` 增补：让模型只从攻略**明确写出**的住宿/预算里抽，不虚构；没写就留空。
- `_run_import`：景点 stops 逻辑不变；额外 geocode 住宿城市、建 🏨 stops；聚合预算写列。

## 验收
- 后端单测：给带住宿+预算的攻略 → 导入后 detail.stops 含 🏨 酒店（带 ticket_price）、
  detail.budget_breakdown 六类聚合正确、trip.budget=总额；不含住宿/预算的攻略导入不报错、
  budget_breakdown 为空（回归 test_import_from_chat 仍过）。
- 前端：费用 tab 显示「计划预算」分类；住宿 tab「每晚住哪」对应天显示酒店名 + ¥价格。
- 全量 pytest 通过 + 前端构建通过 + 部署线上健康。
