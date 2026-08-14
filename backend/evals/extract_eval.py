"""本体抽取评估执行器（2026-08-14）。

用法（backend/ 下）：

    .venv/bin/python -m evals.fetch_samples            # 先拉样本（校验哈希）
    .venv/bin/python -m evals.extract_eval --tag before
    # …改 prompt / 换模型 / 调 lane 切分…
    .venv/bin/python -m evals.extract_eval --tag after
    .venv/bin/python -m evals.compare evals/runs/extract-before.json evals/runs/extract-after.json

与 `runner.py` 的关键差别：**这里不跑流水线，只跑 `build_trip_object`**。
输入是磁盘上固定的攻略正文，所以每次跑的输入完全一致——出现差异必定来自
抽取侧（prompt / 模型 / lane 切分），不会跟浏览器抓到什么搅在一起。
一轮 5 条样本 × 两路，实测量级是分钟与几分钱，可以随手跑。
"""

from __future__ import annotations

import argparse
import asyncio
import json
import pathlib
import sys
import time

from evals.extract_checks import Sample, run_extract_checks

ROOT = pathlib.Path(__file__).parent
SAMPLES = ROOT / "samples"
RUNS = ROOT / "runs"


def load_samples(only: str = "") -> list[Sample]:
    import yaml

    rows = yaml.safe_load((ROOT / "extract.yaml").read_text(encoding="utf-8")) or []
    out = [Sample(**r) for r in rows]
    if only:
        wanted = {x.strip() for x in only.split(",")}
        out = [s for s in out if s.id in wanted]
    return out


def read_sample(s: Sample) -> str:
    path = SAMPLES / f"{s.id}.md"
    if not path.exists():
        raise FileNotFoundError(f"{path} 不存在——先跑 `python -m evals.fetch_samples`")
    text = path.read_text(encoding="utf-8")
    from evals.fetch_samples import digest

    got = digest(text)
    if s.sha256 and got != s.sha256:
        # 输入漂了而期望没改 = 评估结果全部失真，且是最难查的那种失真
        raise ValueError(f"{s.id} 哈希不符：{got} ≠ {s.sha256}")
    return text


async def run_one(s: Sample) -> dict:
    from app.llm.client import get_llm
    from app.ontology.extract import ALL_LANES, build_trip_object

    guide = read_sample(s)
    t0 = time.monotonic()
    trip = await build_trip_object(get_llm(), guide, lanes=ALL_LANES)
    elapsed = time.monotonic() - t0
    findings = run_extract_checks(trip, s)
    return {
        "id": s.id, "note": s.note,
        "elapsed_s": round(elapsed, 1),
        "metrics": {
            "days": len(trip.days),
            "stops": len(trip.stops),
            "expenses": len(trip.expenses),
            "lodgings": len(trip.lodgings),
            "foods": len(trip.foods),
            "reservations": len(trip.reservations),
            "headcount": trip.headcount,
            "lanes": list(trip.lanes),
            "failed_days": list(trip.failed_days),
        },
        "findings": [{"code": f.code, "detail": f.detail, "level": f.level} for f in findings],
        "passed": not any(f.level == "error" for f in findings),
    }


async def _main(args) -> int:
    from evals.runlock import single_run

    with single_run("extract"):
        return await _run_all(args)


async def _run_all(args) -> int:
    samples = load_samples(args.only)
    if not samples:
        print("没有匹配的样本", file=sys.stderr)
        return 2

    results = []
    for i, s in enumerate(samples, 1):
        print(f"[{i}/{len(samples)}] {s.id} …", flush=True)
        try:
            r = await run_one(s)
        except Exception as e:  # noqa: BLE001 — 单条失败不中断整轮
            r = {"id": s.id, "note": s.note, "elapsed_s": 0, "metrics": {},
                 "findings": [{"code": "run_error", "detail": str(e)[:200], "level": "error"}],
                 "passed": False}
        results.append(r)
        m = r["metrics"]
        errs = [f["code"] for f in r["findings"] if f["level"] == "error"]
        print(f"    {'✓ 通过' if r['passed'] else '✗ ' + '、'.join(errs)}"
              f"  |  {r['elapsed_s']}s  {m.get('days', 0)}天 "
              f"{m.get('stops', 0)}点 {m.get('expenses', 0)}项", flush=True)

    RUNS.mkdir(parents=True, exist_ok=True)
    tag = f"extract-{args.tag}"
    (RUNS / f"{tag}.json").write_text(
        json.dumps({"tag": tag, "results": results}, ensure_ascii=False, indent=2),
        encoding="utf-8")
    (RUNS / f"{tag}.md").write_text(render(tag, results), encoding="utf-8")
    n_bad = sum(1 for r in results if not r["passed"])
    print(f"\n快照：{RUNS / f'{tag}.json'}\n报告：{RUNS / f'{tag}.md'}"
          f"\n{len(results) - n_bad}/{len(results)} 条通过")
    return 1 if n_bad else 0


def render(tag: str, results: list[dict]) -> str:
    lines = [f"# 本体抽取评估 · {tag}", "",
             "| 样本 | 结论 | 耗时 | 天 | 停留点 | 开销 | 人数 | lanes |",
             "| --- | --- | --- | --- | --- | --- | --- | --- |"]
    for r in results:
        m = r.get("metrics") or {}
        lines.append(
            f"| {r['id']} | {'✅' if r['passed'] else '❌'} | {r.get('elapsed_s', '-')}s "
            f"| {m.get('days', '-')} | {m.get('stops', '-')} | {m.get('expenses', '-')} "
            f"| {m.get('headcount', '-')} | {'+'.join(m.get('lanes') or []) or '-'} |")
    lines += ["", "## 明细", ""]
    for r in results:
        lines.append(f"### {r['id']}　<sub>{r['note']}</sub>")
        if r["findings"]:
            lines += [f"- {'❌' if f['level'] == 'error' else '⚠️'} `{f['code']}` {f['detail']}"
                      for f in r["findings"]]
        else:
            lines.append("- 全部检查通过")
        lines.append("")
    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", default="", help="按样本 id 逗号分隔筛选")
    ap.add_argument("--tag", default="run")
    return asyncio.run(_main(ap.parse_args()))


if __name__ == "__main__":
    raise SystemExit(main())
