"""两次评估快照对照（2026-08-04）。

    .venv/bin/python -m evals.compare evals/runs/before.json evals/runs/after.json

只回答一个问题：**这次改动让什么变好了、什么变坏了。**
新增硬伤是回归信号；耗时/来源数的显著变化是需要解释的现象（不一定是坏事，
比如来源复用会让耗时大降、xhs 抓取数为 0——那是预期内的）。
"""

from __future__ import annotations

import json
import pathlib
import sys

# 指标变化超过这个比例才提示，避免每次都被抖动刷屏
_SIGNIFICANT = 0.25


def _load(p: str) -> dict[str, dict]:
    data = json.loads(pathlib.Path(p).read_text(encoding="utf-8"))
    return {r["id"]: r for r in data["results"]}


def _codes(r: dict) -> set[str]:
    """一条结果的全部「问题码」——三层都算进来。

    修复 2026-08-04：原先只读 `findings`（即质量层/checks.py），于是**过程层的回归根本
    进不了对照闸门**——而复用降级、无证据风控归因这些恰恰是这套评估集最想守的东西。

    `qual_*` 有意排除：质量层就是按维度重新归类 findings，纳入会把同一个问题数两遍。
    """
    codes = {f["code"] for f in r.get("findings", []) if f["level"] == "error"}
    codes |= {c for c in ((r.get("verification") or {}).get("codes") or [])
              if not c.startswith("qual_")}
    return codes


def _warnings(r: dict) -> set[str]:
    return set((r.get("verification") or {}).get("warnings") or [])


def main() -> int:
    if len(sys.argv) != 3:
        print(__doc__)
        return 2
    before, after = _load(sys.argv[1]), _load(sys.argv[2])

    print(f"# 对照：{sys.argv[1]} → {sys.argv[2]}\n")
    fixed, broke, changed, warns, stale = [], [], [], [], []
    for qid in sorted(set(before) | set(after)):
        b, a = before.get(qid), after.get(qid)
        if not b or not a:
            print(f"- ⚠️ `{qid}` 只在一侧存在，跳过")
            continue
        # 老快照没有 verification 字段：过程层的码在 before 里恒为空，会把「一直存在的
        # 过程违规」误报成新增。宁可提示不可比，也不给假回归信号。
        if ("verification" in b) != ("verification" in a):
            stale.append(qid)
        bc, ac = _codes(b), _codes(a)
        for w in sorted(_warnings(a) - _warnings(b)):
            warns.append(f"{qid}: {w}")
        for c in sorted(bc - ac):
            fixed.append(f"{qid}: {c}")
        for c in sorted(ac - bc):
            broke.append(f"{qid}: {c}")
        for key in ("elapsed_s", "chars", "sources_n", "xhs_n"):
            bv, av = (b.get("metrics") or {}).get(key), (a.get("metrics") or {}).get(key)
            if not isinstance(bv, (int, float)) or not isinstance(av, (int, float)) or not bv:
                continue
            if abs(av - bv) / bv >= _SIGNIFICANT:
                changed.append(f"{qid}.{key}: {bv} → {av} ({(av - bv) / bv:+.0%})")

    if stale:
        print(f"\n> ⚠️ {'、'.join(stale)} 两侧的三层验证字段不齐（有一侧是接入三层前的老快照），"
              "过程/结果层的对照结果不可比，请重跑基线。\n")

    print("## 🔴 新增硬伤（回归）\n")
    print("\n".join(f"- {x}" for x in broke) or "- 无\n")
    print("\n## 🟢 已修复\n")
    print("\n".join(f"- {x}" for x in fixed) or "- 无\n")
    if warns:
        print("\n## ⚠️ 新增告警（不判失败，但需要看一眼）\n")
        print("\n".join(f"- {x}" for x in warns))
    print(f"\n## 📊 指标显著变化（≥{_SIGNIFICANT:.0%}）\n")
    print("\n".join(f"- {x}" for x in changed) or "- 无")
    return 1 if broke else 0


if __name__ == "__main__":
    raise SystemExit(main())
