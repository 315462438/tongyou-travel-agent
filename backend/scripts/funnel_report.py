#!/usr/bin/env python
"""新用户漏斗与留存报告（2026-08-05）。

固化 08-05 那次人工排查用的全部查询，方便隔几天重跑一次、和上一批 cohort 做对照。

用法（在 backend/ 下；本地需先跑 scripts/db_tunnel.sh，服务器上可直连）：

    .venv/bin/python -m scripts.funnel_report                 # 全部真实用户
    .venv/bin/python -m scripts.funnel_report --since 2026-08-04
    .venv/bin/python -m scripts.funnel_report --since 2026-08-04 --detail

`--since` 是**注册时间**下界，用来切 cohort：改造前后各跑一次才有对照意义。

内部账号（admin/evalbot/test*…）一律排除——evalbot 一个人跑评估集就能把
「成都」刷成第一名、把会话数刷上天，不排除的话所有指标都是假的。
"""

from __future__ import annotations

import argparse
import json
from collections import Counter
from datetime import datetime, timezone

from sqlalchemy import func, select

# 内部账号名单只有一份定义（onboarding 的热门榜也用它），避免两处各维护一套
from app.api.onboarding_api import INTERNAL_USERNAMES
from app.db.models import TravelConversation, TravelMessage, TravelTrip, TravelUser
from app.db.session import get_session


def _pct(part: int, whole: int) -> str:
    return f"{part / whole * 100:.0f}%" if whole else "—"


def _quantile(values: list[float], q: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    idx = min(len(ordered) - 1, int(round(q * (len(ordered) - 1))))
    return ordered[idx]


def classify_first_reply(content: str, meta: dict) -> str:
    """首答形态。这是判断「用户为什么走」最直接的信号。"""
    if meta.get("candidates"):
        return "候选卡"          # Phase 76 之后区域型提问应落在这里
    text = (content or "").strip()
    if not text:
        return "空回复"
    if text.startswith("已停止"):
        return "被停止"
    if len(text) <= 60 and text.endswith(("？", "?")):
        return "反问"
    if len(text) < 400:
        return "很短"
    return "攻略"


def report(since: str = "", detail: bool = False) -> dict:
    cutoff = datetime.fromisoformat(since).replace(tzinfo=timezone.utc) if since else None

    with get_session() as db:
        users_q = select(TravelUser).where(TravelUser.username.not_in(INTERNAL_USERNAMES))
        if cutoff is not None:
            users_q = users_q.where(TravelUser.created_at >= cutoff)
        users = list(db.execute(users_q).scalars().all())
        uids = [u.id for u in users]
        if not uids:
            return {"users": 0}

        convs = list(db.execute(
            select(TravelConversation).where(TravelConversation.user_id.in_(uids))
        ).scalars().all())
        cids = [c.id for c in convs]
        msgs = list(db.execute(
            select(TravelMessage).where(TravelMessage.conversation_id.in_(cids))
            .order_by(TravelMessage.created_at)
        ).scalars().all()) if cids else []
        trips = db.execute(
            select(func.count()).select_from(TravelTrip).where(TravelTrip.owner_id.in_(uids))
        ).scalar_one()

    by_conv: dict[str, list[TravelMessage]] = {}
    for m in msgs:
        by_conv.setdefault(m.conversation_id, []).append(m)

    def meta_of(m: TravelMessage) -> dict:
        try:
            return json.loads(m.meta_json) if m.meta_json else {}
        except Exception:  # noqa: BLE001
            return {}

    asked_uids = {c.user_id for c in convs
                  if any(m.role == "user" for m in by_conv.get(c.id, []))}
    silent = [u.username for u in users if u.id not in asked_uids]

    # 单轮等待：用户提问 → 下一条**终稿** assistant
    waits: list[float] = []
    shapes: Counter[str] = Counter()
    posters = 0
    for c in convs:
        rows = by_conv.get(c.id, [])
        finals = [m for m in rows
                  if m.role == "assistant" and not meta_of(m).get("streaming")]
        posters += sum(1 for m in rows if meta_of(m).get("poster"))
        for m in rows:
            if m.role != "user":
                continue
            nxt = next((a for a in finals if a.created_at > m.created_at), None)
            if nxt is not None:
                waits.append((nxt.created_at - m.created_at).total_seconds())
        first_user = next((m for m in rows if m.role == "user"), None)
        if first_user is not None:
            fa = next((a for a in finals if a.created_at > first_user.created_at), None)
            shapes[classify_first_reply(fa.content, meta_of(fa)) if fa else "无回复"] += 1

    # 留存：有几个用户在**两个不同的日子**来过
    days_per_user: dict[str, set] = {}
    conv_owner = {c.id: c.user_id for c in convs}
    for m in msgs:
        uid = conv_owner.get(m.conversation_id)
        if uid:
            days_per_user.setdefault(uid, set()).add(m.created_at.date())
    returned = [u for u, d in days_per_user.items() if len(d) >= 2]

    turns_per_conv = [sum(1 for m in by_conv.get(c.id, []) if m.role == "user") for c in convs]

    out = {
        "cohort": since or "全部",
        "users": len(users),
        "silent_users": len(silent),
        "silent_pct": _pct(len(silent), len(users)),
        "silent_names": silent,
        "conversations": len(convs),
        "single_turn_convs": sum(1 for t in turns_per_conv if t <= 1),
        "returned_users": len(returned),
        "returned_pct": _pct(len(returned), len(asked_uids)),
        "wait_median_s": round(_quantile(waits, 0.5)),
        "wait_p90_s": round(_quantile(waits, 0.9)),
        "wait_max_s": round(max(waits)) if waits else 0,
        "first_reply_shapes": dict(shapes),
        "posters": posters,
        "trips": int(trips),
    }
    if detail:
        out["per_user"] = sorted(
            ({"username": u.username,
              "days": len(days_per_user.get(u.id, ())),
              "asks": sum(1 for m in msgs
                          if conv_owner.get(m.conversation_id) == u.id and m.role == "user")}
             for u in users),
            key=lambda r: (-r["days"], -r["asks"]),
        )
    return out


def render(r: dict) -> str:
    if not r.get("users"):
        return "该 cohort 没有真实用户。"
    lines = [
        f"# 新用户漏斗 · cohort={r['cohort']}",
        "",
        f"注册 {r['users']} 人，其中 **{r['silent_users']} 人零提问（{r['silent_pct']}）**"
        f"{'：' + '、'.join(r['silent_names']) if r['silent_names'] else ''}",
        f"会话 {r['conversations']} 个，单轮 {r['single_turn_convs']} 个",
        f"二次回访 {r['returned_users']} 人（占提问用户 {r['returned_pct']}）",
        "",
        f"等待：中位 {r['wait_median_s']}s · p90 {r['wait_p90_s']}s · 最长 {r['wait_max_s']}s",
        f"首答形态：{r['first_reply_shapes']}",
        f"下游：手账海报 {r['posters']} 次 · 协同行程 {r['trips']} 个",
    ]
    for row in r.get("per_user", []):
        lines.append(f"  - {row['username']}：{row['days']} 天 / {row['asks']} 问")
    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--since", default="", help="注册时间下界（YYYY-MM-DD），用于切 cohort")
    ap.add_argument("--detail", action="store_true", help="逐用户明细")
    ap.add_argument("--json", action="store_true", help="输出 JSON 便于二次处理")
    args = ap.parse_args()

    r = report(args.since, args.detail)
    print(json.dumps(r, ensure_ascii=False, indent=2) if args.json else render(r))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
