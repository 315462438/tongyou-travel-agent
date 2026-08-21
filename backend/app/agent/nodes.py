"""LangGraph 攻略图节点（Phase 14）

节点复用 orchestrator 里踩坑踩出来的采集/生成逻辑，只新增 critique/research
反思环节。进度/流式照旧写消息表（前端轮询无需改）。
"""

import logging
import re

from app.agent import orchestrator as orch
from app.agent.graph_state import AgentState
from app.config import settings
from app.llm.client import get_llm
from app.schemas.critique_schema import GuideCritique

logger = logging.getLogger(__name__)


CRITIQUE_SYSTEM = (
    "你是旅行攻略质检员，只挑「明显硬伤」，不吹毛求疵。默认攻略是合格的（ok=true）。\n"
    "只有出现下列明显问题之一时才判 ok=false：\n"
    "- 明显空泛：通篇没有具体地名/餐馆/交通，全是套话；→ action=research，"
    "给 1-3 个补搜查询词（含目的地）；\n"
    "- 明显绕路或漏了用户明确要求（如指定天数/预算/必去项没体现）；→ action=rewrite，"
    "issues 写清要改什么。\n"
    "只要攻略有真实地点、行程完整、大体合理，就 ok=true, action=none。别为改而改。"
)


_DAY_HEADING_RE = re.compile(
    r"(?im)^(?:#{1,6}\s*)?(?:\*{0,2})?Day\s*(\d{1,2})"
    r"(?:\s*[-–—~至]\s*(?:Day\s*)?(\d{1,2}))?[^\n]*"
)


def _build_critique_prompt(user_text: str, guide: str) -> str:
    """给质检模型完整的结构事实；长攻略保留开头、Day 索引和结尾。

    旧实现只截前 6000 字，预算/后半程通常恰好在截断点之后，导致质检把
    「没看到」误判成「没生成」。结构索引由代码计算，不让模型猜覆盖范围。
    """
    matches = list(_DAY_HEADING_RE.finditer(guide))
    days: set[int] = set()
    headings: list[str] = []
    for m in matches:
        start = int(m.group(1))
        end = int(m.group(2) or start)
        days.update(range(min(start, end), max(start, end) + 1))
        headings.append(m.group(0).strip())
    budget_present = bool(re.search(r"预算|费用|花费|合计", guide))
    facts = (
        "系统提取的结构事实（判断缺失时必须以此为准）：\n"
        f"- Day 编号：{', '.join(str(d) for d in sorted(days)) or '未识别'}\n"
        f"- 已识别预算/费用内容：{'是' if budget_present else '否'}\n"
    )
    if len(guide) <= 14000:
        excerpt = guide
    else:
        heading_index = "\n".join(headings)
        excerpt = (
            f"{guide[:6500]}\n\n"
            f"[中段 Day 标题索引]\n{heading_index}\n\n"
            f"[攻略结尾]\n{guide[-6500:]}"
        )
    return f"用户要求：{user_text}\n\n{facts}\n攻略：\n{excerpt}"


# ---------- 节点 ----------

def parse_node(state: AgentState) -> dict:
    return orch.parse_request(state["cid"], state["user_text"], state.get("user_id", ""))


# 后台快答线程的引用。不持有会被 GC 掉——线程对象没有其他引用者。
_QUICK_TAKE_THREADS: set = set()


def quick_take_node(state: AgentState) -> dict:
    """parse 后、collect 前：建流式占位 + **异步**快答（2026-08-13 起；2026-08-21 改为不阻塞）。

    ⚠️ 顺序不变式：占位必须先于快答——快答是非流式 assistant（meta.preliminary），
    没有占位时 `_is_running` 会判本轮完成、前端停止轮询、完整版永远收不到。
    所以**占位仍然同步创建**，改的只是快答那次 LLM 调用不再挡路。
    占位消息存进 state，generate 节点复用同一条，终稿落它。

    2026-08-21：线上实测快答要 9.7–11.2s，而它与采集**没有数据依赖**——串起来纯属浪费，
    这 10 秒里浏览器和小红书一动不动。现在丢进后台线程，采集立刻开始。
    用线程而非 asyncio task：`emit_guide_quick_take` 是同步函数（内部 LLM 调用阻塞），
    且本节点本身是同步的；仓库里记忆整理、崩溃续跑也都是这么起的。
    """
    cid = state["cid"]
    msg_id = orch._add_streaming_message(cid)   # 同步：顺序不变式的那一半，不能挪
    if settings.guide_quick_take:
        _spawn_quick_take(cid, state["user_text"], state["pref"], state.get("user_id", ""))
    return {"msg_id": msg_id}


def _spawn_quick_take(cid: str, user_text: str, pref, user_id: str) -> None:
    """后台跑快答。**不 join**——迟到就迟到，它是垫场的，绝不能拖住终稿。"""
    import threading

    def _run() -> None:
        try:
            orch.emit_guide_quick_take(cid, user_text, pref, user_id)
        except Exception:  # noqa: BLE001 — 纯增强：占位已在，快答的任何 bug 都不能毁掉整轮
            logger.warning("quick_take failed cid=%s", cid, exc_info=True)
        finally:
            _QUICK_TAKE_THREADS.discard(threading.current_thread())

    t = threading.Thread(target=_run, name=f"quick-take-{cid[:8]}", daemon=True)
    _QUICK_TAKE_THREADS.add(t)
    t.start()


async def collect_node(state: AgentState) -> dict:
    sources, is_revision = await orch.collect_sources(
        state["cid"], state["pref"], state["intent"], state["hotel_needed"], state.get("user_id", ""),
        state["user_text"],
    )
    return {"sources": sources, "is_revision": is_revision, "rounds": 0}


def apologize_node(state: AgentState) -> dict:
    dest = getattr(state["pref"], "destination", "") or "目的地"
    text = (
        f"我没能从网上抓到足够的 {dest} 资料（可能遇到反爬或网络限制）。"
        "要不要换个目的地，或稍后再试？"
    )
    if state.get("msg_id"):
        # 2026-08-13：快答先行建的占位必须就地终稿，否则 streaming 残留让前端永远判运行中
        orch._finalize_streaming_message(state["msg_id"], text, "", {})
    else:
        orch._add_message(state["cid"], "assistant", text)
    return {}


def generate_node(state: AgentState) -> dict:
    cid = state["cid"]
    if state.get("rounds", 0) > 0:
        if state.get("feedback"):
            _short = state["feedback"].replace("\n", "；")[:40]
            orch._progress(cid, f"发现可优化：{_short}，正在重排…")
        else:
            orch._progress(cid, "正在结合新资料重新规划…")
    else:
        orch._progress(cid, "正在综合多个来源，生成攻略…")
    guide, reasoning, msg_id, mem_ctx = orch.generate_guide_streaming(
        cid, state["user_text"], state["pref"], state["intent"], state["sources"],
        state.get("user_id", ""), msg_id=state.get("msg_id"), feedback=state.get("feedback", ""),
    )
    return {"guide": guide, "reasoning": reasoning, "msg_id": msg_id, "mem_ctx": mem_ctx}


def critique_node(state: AgentState) -> dict:
    """自检攻略。reflection 关闭或已达循环上限则直接判 ok（不再优化）。"""
    # 停止检查点（2026-07-31）：此前反思环节无检查点——终稿已可见但用户点停止后
    # 自检/补搜/重写仍会继续跑好几十秒（线上反馈「不能中途停止」）。
    from app.agent.cancel import check

    check(state.get("cid", ""))
    if not settings.reflection_enabled or state.get("rounds", 0) >= settings.graph_max_guide_rounds:
        return {"critique": {"ok": True, "action": "none"}}
    # 自检静默进行（快模型 ~几秒）：通过则不打扰用户，只有要优化时 generate 节点才叙述
    try:
        # 自检是判断题，用快模型（v4-flash），几秒出结果，不占大模型时间
        c = get_llm().parse(
            _build_critique_prompt(state["user_text"], state["guide"]),
            GuideCritique, model=settings.model_classifier, system=CRITIQUE_SYSTEM,
        )
        crit = c.model_dump()
    except Exception:  # noqa: BLE001 — 自检失败就当达标，不阻塞出稿
        logger.warning("critique failed", exc_info=True)
        crit = {"ok": True, "action": "none", "issues": [], "search_queries": []}
    return {"critique": crit}


async def research_node(state: AgentState) -> dict:
    """针对自检缺口补搜，并入来源。计一轮循环。"""
    rounds = state.get("rounds", 0) + 1
    queries = state.get("critique", {}).get("search_queries") or []
    extra = await orch.research_more(state["cid"], state["pref"], queries, state.get("user_id", ""))
    if not extra:
        # 补搜无果 → 退化为按问题重写
        return {"rounds": rounds, "feedback": "\n".join(state.get("critique", {}).get("issues") or [])}
    seen = {s.get("url") for s in state["sources"]}
    merged = state["sources"] + [s for s in extra if s.get("url") not in seen]
    return {"rounds": rounds, "sources": merged, "feedback": ""}


def finalize_node(state: AgentState) -> dict:
    orch.finalize_guide(
        state["cid"], state["user_text"], state["pref"], state["sources"],
        state["guide"], state["reasoning"], state["msg_id"], state.get("mem_ctx", {}),
        state.get("user_id", ""),
    )
    return {}


# ---------- 条件边 ----------

def route_after_parse(state: AgentState) -> str:
    return "plan" if state.get("route") == "plan" else "end"


def route_after_collect(state: AgentState) -> str:
    return "generate" if state.get("sources") else "apologize"


def route_after_critique(state: AgentState) -> str:
    crit = state.get("critique") or {}
    if crit.get("ok"):
        return "finalize"
    if crit.get("action") == "research" and crit.get("search_queries"):
        return "research"
    return "rewrite"


def rewrite_node(state: AgentState) -> dict:
    """rewrite 分支：把 critique.issues 作为下一轮生成的改进反馈，计一轮循环。"""
    return {
        "rounds": state.get("rounds", 0) + 1,
        "feedback": "\n".join(state.get("critique", {}).get("issues") or []),
    }
