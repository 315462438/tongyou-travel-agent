# 本体抽取评估 · extract-fix

| 样本 | 结论 | 耗时 | 天 | 停留点 | 开销 | 人数 | lanes |
| --- | --- | --- | --- | --- | --- | --- | --- |
| tiantangzhai_3d_short | ✅ | 91.7s | 3 | 8 | 11 | 2 | cost+itinerary |
| malaysia_7d_overseas | ✅ | 154.0s | 7 | 38 | 34 | 2 | cost+itinerary |

## 明细

### tiantangzhai_3d_short　<sub>最短样本（3.8k 字）。守单次调用路径、守「人均口径的表 + 两人同行」不被混为一谈。</sub>
- 全部检查通过

### malaysia_7d_overseas　<sub>海外多城 7 天，12k 字——**超过 ontology_single_call_max_days(6)，走分块路径**。
Day 6 正文里有「路线A/路线B」二选一分支，守分支不把一天拆成两天。
</sub>
- 全部检查通过
