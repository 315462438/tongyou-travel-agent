# 路由分类评估 · routes-baseline

严格准确率 **94.3%**（33/35 跑成的条目），硬错 0 条，软错（允许的降级）2 条。

⚠️ **摇摆条目**（多次跑结果不一致）：d_traffic、d_visa_free_known

## 混淆矩阵（行=期望，列=实际）

| 期望＼实际 | direct | guide | research |
| --- | --- | --- | --- |
| **direct** | 12 | 1 | 1 |
| **guide** | 0 | 15 | 0 |
| **research** | 0 | 0 | 6 |

## 判错明细

- △ 软错 `d_visa_free_known` 期望 **direct** → 实际 **research**（票：research/research/direct）　<sub>去香港需要港澳通行证吗｜稳定的证件常识。判 research 会绕一大圈。</sub>
- △ 软错 `b_long_but_direct` 期望 **direct** → 实际 **guide**　<sub>我下个月要带父母去旅游，他们腿脚不太好走不了太多路，也不太能吃辣，我想问一下这种｜长文本但要的是经验建议，没提目的地。守「长 ≠ 规划」。</sub>
