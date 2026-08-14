# 本体抽取评估 · extract-baseline

| 样本 | 结论 | 耗时 | 天 | 停留点 | 开销 | 人数 | lanes |
| --- | --- | --- | --- | --- | --- | --- | --- |
| tiantangzhai_3d_short | ✅ | 108.2s | 3 | 10 | 10 | 2 | cost+itinerary |
| wuhan_3d | ✅ | 96.4s | 3 | 15 | 13 | 2 | cost+itinerary |
| chongqing_5d_drive | ✅ | 117.2s | 5 | 23 | 16 | 3 | cost+itinerary |
| malaysia_7d_overseas | ✅ | 124.7s | 7 | 34 | 29 | 2 | cost+itinerary |
| yushu_10d_long | ✅ | 150.1s | 10 | 43 | 30 | 2 | cost+itinerary |

## 明细

### tiantangzhai_3d_short　<sub>最短样本（3.8k 字）。守单次调用路径与最短正文下的逐日覆盖。</sub>
- 全部检查通过

### wuhan_3d　<sub>单城 3 天。预算表标题写「2人3天」而表身是总额——守人数被认出来。</sub>
- 全部检查通过

### chongqing_5d_drive　<sub>自驾多点 5 天，「两大一小」。守 3 人被认出（不是 2，也不是 1）。</sub>
- 全部检查通过

### malaysia_7d_overseas　<sub>海外多城 7 天，12k 字——**超过 ontology_single_call_max_days(6)，走分块路径**。
Day 6 正文里有「路线A/路线B」二选一分支，守分支不把一天拆成两天。
</sub>
- 全部检查通过

### yushu_10d_long　<sub>最长天数（10 天跨 3 地）。守分块路径不丢天、failed_days 为空。</sub>
- 全部检查通过
