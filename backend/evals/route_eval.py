"""路由分类评估执行器（2026-08-14）。

用法（backend/ 下）：

    .venv/bin/python -m evals.route_eval --tag before
    .venv/bin/python -m evals.route_eval --tag after --repeat 3

`--repeat` 是这个集子特有的：分类走的是快模型，同一句话两次跑出不同结果是真实存在的。
**摇摆的条目比稳定判错的更危险**——稳定错能一次修掉，摇摆的会随机复发，
所以报表把「不稳定」单列，不混进准确率里。

判错分两级（见 routes.yaml 头部）：
    硬错  落在 tolerate 之外，用户直接感知
    软错  设计允许的保守降级（「拿不准一律 guide」）
闸门只看硬错——把软错也当失败会逼着我们去「优化」一个本来就正确的降级。
"""

from __future__ import annotations

import argparse
import json
import pathlib
import sys
import time
from collections import Counter
from dataclasses import dataclass, field

ROOT = pathlib.Path(__file__).parent
RUNS = ROOT / "runs"
KINDS = ("direct", "guide", "research")


@dataclass
class RouteCase:
    id: str
    text: str
    expect: str
    tolerate: list[str] = field(default_factory=list)
    note: str = ""


def load_cases(only: str = "") -> list[RouteCase]:
    import yaml

    rows = yaml.safe_load((ROOT / "routes.yaml").read_text(encoding="utf-8")) or []
    cases = [RouteCase(**r) for r in rows]
    if only:
        wanted = {x.strip() for x in only.split(",")}
        cases = [c for c in cases if c.id in wanted or c.expect in wanted]
    return cases


def grade(case: RouteCase, got: str) -> str:
    """一次分类的结论：hit / soft / hard / error。"""
    if got == "run_error":
        return "error"
    if got == case.expect:
        return "hit"
    return "soft" if got in case.tolerate else "hard"


def classify_once(text: str, llm) -> str:
    """复刻 `decide_route` 的结构，但**不把异常吞成 guide**。

    生产里那个 `except: return "guide"` 是对的——分类挂了也得让用户拿到东西。
    但在评估里它是灾难：**一次网络失败长得和「模型判成 guide」一模一样**，
    准确率被污染却不留痕迹。

    立集当天就踩到了：跑评估的环境连不上 api.deepseek.com，35 条全走了兜底分支，
    报表打出「严格准确率 42.9%」——一个完全由连接失败构成的数字，
    而且看上去非常像一个「模型偏向 guide」的真实结论。

    所以评估侧必须自己接住异常并标成 `run_error`，让它在报表里现形。
    """
    from app.agent.context_security import is_explicit_itinerary_request
    from app.agent.deep_research import ROUTE_SYSTEM

    text = (text or "").strip()
    if not text:
        return "guide"
    # 生产里的确定性短路，评估要一并复刻，否则测的不是线上那条路径
    if is_explicit_itinerary_request(text):
        return "guide"

    from pydantic import BaseModel

    class _Route(BaseModel):
        kind: str

    r = llm.classify(text[:500], _Route, system=ROUTE_SYSTEM)
    kind = (r.kind or "").strip().lower()
    return kind if kind in KINDS else "guide"


def run_case(case: RouteCase, llm, repeat: int) -> dict:
    votes, t0 = [], time.monotonic()
    for _ in range(repeat):
        votes.append(classify_once(case.text, llm))
    elapsed = (time.monotonic() - t0) / max(1, repeat)
    tally = Counter(votes)
    majority = tally.most_common(1)[0][0]
    return {
        "id": case.id, "text": case.text, "note": case.note,
        "expect": case.expect, "tolerate": case.tolerate,
        "votes": votes, "got": majority,
        "grade": grade(case, majority),
        "stable": len(tally) == 1,
        "elapsed_s": round(elapsed, 2),
    }


def summarize(results: list[dict]) -> dict:
    """准确率的分母是**跑成了的条数**，不是总条数。

    跑挂的条目（网络/鉴权）既不算对也不算错——把它们摊进分母，报表会给出一个
    「模型变差了」的假象；摊进分子更糟。它们只说明这一轮不可信，单独列出来。
    """
    grades = Counter(r["grade"] for r in results)
    scored = [r for r in results if r["grade"] != "error"]
    n = len(scored) or 1
    confusion: dict[str, Counter] = {k: Counter() for k in KINDS}
    for r in scored:
        if r["expect"] in confusion:
            confusion[r["expect"]][r["got"]] += 1
    return {
        "total": len(results),
        "scored": len(scored),
        "hit": grades["hit"], "soft": grades["soft"], "hard": grades["hard"],
        "errors": grades["error"],
        "error_ids": [r["id"] for r in results if r["grade"] == "error"],
        "accuracy": round(grades["hit"] / n, 3),
        "hard_rate": round(grades["hard"] / n, 3),
        "unstable": [r["id"] for r in scored if not r["stable"]],
        "confusion": {k: dict(v) for k, v in confusion.items()},
    }


def render(tag: str, results: list[dict], summary: dict) -> str:
    lines = [f"# 路由分类评估 · {tag}", "",
             f"严格准确率 **{summary['accuracy']:.1%}**"
             f"（{summary['hit']}/{summary['scored']} 跑成的条目），"
             f"硬错 {summary['hard']} 条，软错（允许的降级）{summary['soft']} 条。", ""]
    if summary["errors"]:
        lines += [f"> 🚨 **{summary['errors']} 条没跑成**（网络/鉴权），"
                  f"这一轮的数字不可用于前后对照：{'、'.join(summary['error_ids'][:8])}"
                  f"{' …' if summary['errors'] > 8 else ''}", ""]
    if summary["unstable"]:
        lines += [f"⚠️ **摇摆条目**（多次跑结果不一致）：{'、'.join(summary['unstable'])}", ""]

    lines += ["## 混淆矩阵（行=期望，列=实际）", "",
              "| 期望＼实际 | direct | guide | research |", "| --- | --- | --- | --- |"]
    for k in KINDS:
        row = summary["confusion"].get(k, {})
        lines.append(f"| **{k}** | " + " | ".join(str(row.get(c, 0)) for c in KINDS) + " |")

    lines += ["", "## 判错明细", ""]
    bad = [r for r in results if r["grade"] != "hit"]
    if not bad:
        lines.append("无。")
    for r in bad:
        mark = "❌ 硬错" if r["grade"] == "hard" else "△ 软错"
        lines.append(f"- {mark} `{r['id']}` 期望 **{r['expect']}** → 实际 **{r['got']}**"
                     f"{'（票：' + '/'.join(r['votes']) + '）' if len(set(r['votes'])) > 1 else ''}"
                     f"　<sub>{r['text'][:40]}｜{r['note']}</sub>")
    return "\n".join(lines) + "\n"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", default="", help="按 id 或期望通道逗号分隔筛选")
    # 立集当天实测：连跑两次 --repeat 1，准确率都是 91.4%，但**错的不是同一批条目**
    # （一次 0 硬错 3 软错，一次 2 硬错 1 软错）。单次跑不能当基线——拿它做前后对照，
    # 会把模型的抖动读成「改动带来的回归」。定基线一律 --repeat 3 起。
    ap.add_argument("--repeat", type=int, default=1, help="每条跑几次；定基线用 3 起")
    ap.add_argument("--tag", default="run")
    args = ap.parse_args()

    from evals.runlock import single_run

    with single_run("routes"):
        return _run_all(args)


def _run_all(args) -> int:
    from app.llm.client import get_llm

    cases = load_cases(args.only)
    if not cases:
        print("没有匹配的用例", file=sys.stderr)
        return 2

    llm = get_llm()
    results = []
    for i, c in enumerate(cases, 1):
        try:
            r = run_case(c, llm, max(1, args.repeat))
        except Exception as e:  # noqa: BLE001 — 跑挂标成 error，绝不混进准确率
            r = {"id": c.id, "text": c.text, "note": c.note, "expect": c.expect,
                 "tolerate": c.tolerate, "votes": [], "got": "run_error",
                 "grade": "error", "stable": True, "elapsed_s": 0,
                 "error": str(e)[:200]}
        results.append(r)
        mark = {"hit": "✓", "soft": "△", "hard": "✗", "error": "🚨"}[r["grade"]]
        print(f"[{i}/{len(cases)}] {mark} {r['id']:22} {r['expect']:9}→ {r['got']:9}"
              f" {r['elapsed_s']}s", flush=True)

    summary = summarize(results)
    RUNS.mkdir(parents=True, exist_ok=True)
    tag = f"routes-{args.tag}"
    (RUNS / f"{tag}.json").write_text(
        json.dumps({"tag": tag, "summary": summary, "results": results},
                   ensure_ascii=False, indent=2), encoding="utf-8")
    (RUNS / f"{tag}.md").write_text(render(tag, results, summary), encoding="utf-8")
    print(f"\n严格准确率 {summary['accuracy']:.1%}（{summary['hit']}/{summary['scored']}）"
          f"　硬错 {summary['hard']}　软错 {summary['soft']}")
    if summary["unstable"]:
        print(f"⚠️ 摇摆：{'、'.join(summary['unstable'])}")
    print(f"报告：{RUNS / f'{tag}.md'}")
    if summary["errors"]:
        # 退出码 2 ≠ 1：「跑不出来」和「跑出来不合格」是两回事，
        # 当闸门用时前者要求人去看环境，后者才是模型/prompt 的问题
        print(f"🚨 {summary['errors']} 条没跑成，本轮不可用于对照", file=sys.stderr)
        return 2
    return 1 if summary["hard"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
