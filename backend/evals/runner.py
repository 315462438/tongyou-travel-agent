"""评估集执行器（2026-08-04）。

用法（在 backend/ 下）：

    .venv/bin/python -m evals.runner --base-url https://17tongyou.com/travel \\
        --user evalbot --password '…' --limit 3 --tag before

    .venv/bin/python -m evals.runner ... --tag after
    .venv/bin/python -m evals.compare evals/runs/before.json evals/runs/after.json

设计取舍：
- 走**真实 HTTP 接口**端到端跑，因为要守的正是"整条流水线的产出"，
  mock 掉任何一层都会漏掉这周真实翻过的车（复用、续写、记忆污染都在链路里）。
- 因此全量一次约 1 小时（浏览器池同用户串行），定位是**大改动前后的对照闸门**，
  不是 CI 每次跑。用 --limit / --only 跑子集做快速验证。
"""

from __future__ import annotations

import argparse
import json
import pathlib
import sys
import time
import urllib.error
import urllib.request

from evals.checks import Query, run_checks
from evals.metrics import collect
from evals.verify import build_report, verify_all

ROOT = pathlib.Path(__file__).parent
RUNS = ROOT / "runs"


def _http(url: str, token: str = "", body: dict | None = None, timeout: int = 60):
    data = json.dumps(body).encode() if body is not None else None
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(url, data=data, headers=headers,
                                 method="POST" if data is not None else "GET")
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read())


def load_queries(path: pathlib.Path, only: str = "", limit: int = 0) -> list[Query]:
    import yaml

    rows = yaml.safe_load(path.read_text(encoding="utf-8")) or []
    qs = [Query(**r) for r in rows]
    if only:
        wanted = {x.strip() for x in only.split(",")}
        qs = [q for q in qs if q.id in wanted or q.category in wanted]
    return qs[:limit] if limit else qs


def passed(r: dict) -> bool:
    """一条结果算不算通过——**唯一判据**。

    修复 2026-08-04：控制台文案、退出码原先各自用 `findings` 另算一套，而 findings 只来自
    checks.py（质量层）。结果是过程验证挂了（比如复用来源后仍跳过必应），退出码照样是 0、
    控制台照样打印「✓ 三层验证通过」，只有翻开 md 表格才看得见 ❌。当闸门用必漏。
    """
    if any(f["level"] == "error" for f in r.get("findings") or []):
        return False
    v = r.get("verification")
    if v is not None:
        return bool(v.get("passed"))
    return bool(r.get("verified", True))  # 兼容三层接入前的老快照


def verdict_line(r: dict) -> str:
    if passed(r):
        return "✓ 三层验证通过"
    v = r.get("verification") or {}
    layers = v.get("failed_layers") or []
    codes = v.get("codes") or [f["code"] for f in r.get("findings") or []
                               if f["level"] == "error"]
    where = "/".join({"result": "结果", "process": "过程", "quality": "质量"}.get(x, x)
                     for x in layers) or "质量"
    return f"✗ {where}层未通过：{'、'.join(codes) or '未知'}"


def run_one(base: str, token: str, q: Query, poll_s: float, timeout_s: int) -> dict:
    """跑一条 query，返回 {guide, meta, metrics, findings}。"""
    cid = _http(f"{base}/api/chat/conversations", token, {})["conversation_id"]
    t0 = time.monotonic()
    _http(f"{base}/api/chat/{cid}/messages", token,
          {"content": q.text, "deep_reasoning": q.deep, "sandbox_enabled": False})

    guide, meta = "", {}
    # 轨迹必须**跨轮询累积**：progress 消息在终稿时会被 clear_plain_progress 清掉，
    # 只看最后一次轮询会拿到空轨迹（过程验证直接失真）。按内容去重保序。
    progress: list[str] = []
    seen: set[str] = set()
    while True:
        time.sleep(poll_s)
        payload = _http(f"{base}/api/chat/{cid}/messages", token)
        msgs = payload.get("messages") or []
        for m in msgs:
            if m.get("role") == "progress" and m.get("content") and m["content"] not in seen:
                seen.add(m["content"])
                progress.append(m["content"])
        finals = [m for m in msgs if m.get("role") == "assistant"
                  and not (m.get("meta") or {}).get("streaming")
                  and not (m.get("meta") or {}).get("preliminary")]
        if not payload.get("running") and finals:
            guide = finals[-1].get("content") or ""
            meta = finals[-1].get("meta") or {}
            break
        if time.monotonic() - t0 > timeout_s:
            guide = finals[-1].get("content", "") if finals else ""
            meta = {"timeout": True}
            break

    elapsed = time.monotonic() - t0
    # 过程验证的主证据源（Phase 90 的轨迹接口）。Langfuse 落库有几秒延迟，
    # 拉不到就是空列表，verify 那边会自动退回进度文案，不影响这一轮的结论。
    try:
        traj = (_http(f"{base}/api/chat/{cid}/trajectory", token).get("events") or [])
    except Exception:  # noqa: BLE001 — 轨迹是增强证据，拿不到不该让整条评估失败
        traj = []
    findings = run_checks(guide, q)
    report, verified = build_report(guide, meta, progress, q, elapsed, traj)
    return {
        "id": q.id, "category": q.category, "text": q.text, "note": q.note,
        "conversation_id": cid,
        "metrics": collect(guide, meta, elapsed, progress).as_dict(),
        "findings": [{"code": f.code, "detail": f.detail, "level": f.level} for f in findings],
        "verified": verified,
        # 结构化三层结果：控制台判定、退出码、compare.py 都读它，
        # 不再各自用 findings 另算一套（那会让过程层的失败无声溜过去）
        "verification": verify_all(guide, meta, progress, q, traj),
        "verification_report": report,
        "progress": progress,
        "trajectory_tools": [e.get("name") for e in traj if (e.get("lane") or "") == "tools"],
        "excerpt": guide[:400],
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base-url", default="https://17tongyou.com/travel")
    ap.add_argument("--user", required=True)
    ap.add_argument("--password", required=True)
    ap.add_argument("--only", default="", help="按 id 或 category 逗号分隔筛选")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--tag", default="run", help="快照名，用于前后对照")
    ap.add_argument("--poll-s", type=float, default=5.0)
    ap.add_argument("--timeout-s", type=int, default=900)
    args = ap.parse_args()

    base = args.base_url.rstrip("/")
    token = _http(f"{base}/api/auth/login", body={"username": args.user, "password": args.password})["token"]
    queries = load_queries(ROOT / "queries.yaml", args.only, args.limit)
    if not queries:
        print("没有匹配的 query", file=sys.stderr)
        return 2

    results = []
    for i, q in enumerate(queries, 1):
        print(f"[{i}/{len(queries)}] {q.id} …", flush=True)
        try:
            r = run_one(base, token, q, args.poll_s, args.timeout_s)
        except Exception as e:  # noqa: BLE001 — 单条失败不该中断整轮评估
            r = {"id": q.id, "category": q.category, "text": q.text, "note": q.note,
                 "metrics": {}, "findings": [{"code": "run_error", "detail": str(e)[:200],
                                              "level": "error"}], "excerpt": ""}
        results.append(r)
        print(f"    {verdict_line(r)}"
              f"  |  {r['metrics'].get('elapsed_s', '?')}s"
              f"  {r['metrics'].get('chars', 0)} 字", flush=True)

    RUNS.mkdir(parents=True, exist_ok=True)
    snap = RUNS / f"{args.tag}.json"
    snap.write_text(json.dumps({"tag": args.tag, "base_url": base, "results": results},
                               ensure_ascii=False, indent=2), encoding="utf-8")
    report = RUNS / f"{args.tag}.md"
    report.write_text(render_report(args.tag, results), encoding="utf-8")
    n_bad = sum(1 for r in results if not passed(r))
    warned = [f"{r['id']}: {w}" for r in results
              for w in ((r.get("verification") or {}).get("warnings") or [])]
    print(f"\n快照：{snap}\n报告：{report}\n{len(results) - n_bad}/{len(results)} 条三层验证通过")
    if warned:
        print("⚠️ " + "\n⚠️ ".join(warned))
    return 1 if n_bad else 0


def render_report(tag: str, results: list[dict]) -> str:
    lines = [f"# 评估报告 · {tag}", "",
             "| query | 三层验证 | 耗时 | 字数 | 来源 | 小红书 | 高德 | 携程 | 复用 |",
             "| --- | --- | --- | --- | --- | --- | --- | --- | --- |"]
    for r in results:
        m = r.get("metrics") or {}
        v = r.get("verification") or {}
        bad = "/".join({"result": "结果", "process": "过程", "quality": "质量"}.get(x, x)
                       for x in (v.get("failed_layers") or [])) or "质量"
        lines.append(
            f"| {r['id']} | {'✅' if passed(r) else '❌ ' + bad} "
            f"| {m.get('elapsed_s', '-')}s | {m.get('chars', '-')} | {m.get('sources_n', '-')} "
            f"| {m.get('xhs_n', '-')} | {'✓' if m.get('has_amap') else '·'} "
            f"| {'✓' if m.get('has_ctrip') else '·'} | {'♻️' if m.get('reused') else '·'} |"
        )
    lines += ["", "## 三层验证明细", ""]
    for r in results:
        if r.get("verification_report"):
            lines.append(r["verification_report"])
        else:  # 跑挂的条目没有报告，退回列 findings
            lines.append(f"### {r['id']}　<sub>{r['note']}</sub>")
            lines += [f"- ❌ `{f['code']}` {f['detail']}" for f in r["findings"]]
            lines.append("")
    return "\n".join(lines)


if __name__ == "__main__":
    raise SystemExit(main())
