# Task Plan — Phase 52（清单批5）：日期追问 + 实时数据可信度

## 背景（用户反馈）
弱模型在没有出发/入住日期时，会一本正经地编具体房价、车次时刻、机票价格，看着像实时其实是幻觉。
需求：酒店/火车/航班「实时查询」前必问出发日期；无日期一律标「参考价（非实时）」；预算作硬过滤
（超预算进「上浮备选」）；交通结果带来源 + 查询日期。

## 方案：可信度守卫（纯函数）+ 生成侧 prompt 注入（不伪造数据）

### 新模块 `app/agent/realtime_guard.py`（纯函数、可测）
- `realtime_kind(text)` → 'hotel' / 'transport' / ''：本轮是否问实时价格/时刻类（交通词优先）。
- `extract_travel_date(text, today)` → ISO 日期 / ''：抽 YYYY-MM-DD、X月X日/号、MM-DD、
  今天/明天/后天/大后天、周末、(下)周X；过去月份按明年。
- `resolve_date(*texts)`：本轮 user_text 优先，回退上下文（历史）里的日期。
- `credibility_directive(text, context, today)` → 注入 system prompt 的纪律串：
  - 非实时类 → 空串（不干扰普通攻略）；
  - 实时类**无日期** → 「①先追问日期 ②价格标『参考价（非实时）』 ③只给参考区间，别编具体房态/车次」；
  - 实时类**有日期** → 「标注『查询日期 X』+ 数据来源（携程 / 12306 航空），无可靠来源就给区间说明是估算」。

### 生成侧接线（orchestrator）
- `generate_guide_streaming`：base = HOTEL/ITINERARY_SYSTEM + `credibility_directive(user_text,
  context=历史)` → 酒店/交通轮自动带纪律。
- `run_direct_answer`：DIRECT_SYSTEM + `credibility_directive(user_text)` → 快答问酒店/交通同样守纪律。
- `HOTEL_SYSTEM` 静态补「预算硬约束」：预算内正常推荐，缺预算内好选择才单列「## 上浮备选」并注明
  超出多少，不把超预算的混进正常推荐。

## 取舍
- **不给 amap 板上酒店做预算过滤**：高德 POI 无价格字段，过滤无从谈起；预算硬过滤落在有价格的
  对话酒店推荐（携程实价/参考价）里，用 prompt 纪律实现。
- **不接真·铁路/航空数据源**（本批不引入 12306/航司抓取）：诚实标注「参考·非实时」+ 引导补日期后
  走深度推理/携程接管实时链路，而不是假装有实时票务。这符合「宁可说不知道，也不编」。
- 日期解析靠正则相对词，未覆盖「农历/节假日名」等；抽不到就走「无日期」分支（更保守，不会错标实时）。

## 验收
- `test_realtime_guard.py`：kind 判定、显式/相对日期解析、resolve 优先级、directive 三分支（无日期
  酒店 / 有日期交通 / 非实时空串 / 用上下文日期）——9 例全过。
- 全量 pytest 通过；线上健康。
- 人工验证（线上）：快答「帮我查成都酒店」→ 回复先问日期 + 标参考价；「8月2号成都酒店」→ 标查询日期。
