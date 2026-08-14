"""LangGraph 攻略图组装（Phase 14 + 16 checkpoint）

固定采集/生成主干 + critique/research/rewrite 反思循环：
  parse → (quick_take 占位+快答先行) → collect → (有料) generate → critique
    critique → finalize / research→generate / rewrite→generate
反思关闭或达上限时退化为「生成一次即终稿」。

Phase 16：编译时挂 Postgres checkpointer（AsyncPostgresSaver），每步 state 落 PG，
thread_id = 本轮用户消息 id；进程被杀后可从 checkpoint 续跑。
"""

import logging
from functools import lru_cache

from langgraph.graph import END, START, StateGraph

from app.agent import nodes
from app.agent.graph_state import AgentState
from app.config import settings

logger = logging.getLogger(__name__)


def _build_graph() -> StateGraph:
    g = StateGraph(AgentState)
    g.add_node("parse", nodes.parse_node)
    g.add_node("quick_take", nodes.quick_take_node)  # 2026-08-13：占位+快答先行
    g.add_node("collect", nodes.collect_node)
    g.add_node("apologize", nodes.apologize_node)
    g.add_node("generate", nodes.generate_node)
    g.add_node("critique", nodes.critique_node)
    g.add_node("research", nodes.research_node)
    g.add_node("rewrite", nodes.rewrite_node)
    g.add_node("finalize", nodes.finalize_node)

    g.add_edge(START, "parse")
    g.add_conditional_edges(
        "parse", nodes.route_after_parse, {"plan": "quick_take", "end": END}
    )
    g.add_edge("quick_take", "collect")
    g.add_conditional_edges(
        "collect", nodes.route_after_collect, {"generate": "generate", "apologize": "apologize"}
    )
    g.add_edge("apologize", END)
    g.add_edge("generate", "critique")
    g.add_conditional_edges(
        "critique", nodes.route_after_critique,
        {"finalize": "finalize", "research": "research", "rewrite": "rewrite"},
    )
    g.add_edge("research", "generate")
    g.add_edge("rewrite", "generate")
    g.add_edge("finalize", END)
    return g


@lru_cache(maxsize=1)
def _compiled():
    """无 checkpointer 的编译版（离线测试用）。"""
    return _build_graph().compile()


def _saver_ctx():
    from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

    return AsyncPostgresSaver.from_conn_string(settings.checkpoint_conn)


async def run_guide_graph(cid: str, user_text: str, user_id: str, turn_id: str = "") -> None:
    """跑攻略图。开启 checkpointer 时按 thread_id=turn_id 持久化每步 state。"""
    state = {"cid": cid, "user_text": user_text, "user_id": user_id}
    if not settings.checkpointer_enabled or not turn_id:
        await _compiled().ainvoke(state)
        return
    async with _saver_ctx() as saver:
        app = _build_graph().compile(checkpointer=saver)
        await app.ainvoke(state, config={"configurable": {"thread_id": turn_id}})


async def resume_turn(turn_id: str) -> bool:
    """从 checkpoint 续跑某轮（重启恢复用）。thread_id=turn_id，input=None 表示续跑。
    有可续跑的 checkpoint 返回 True，无则 False。"""
    if not settings.checkpointer_enabled or not turn_id:
        return False
    async with _saver_ctx() as saver:
        app = _build_graph().compile(checkpointer=saver)
        cfg = {"configurable": {"thread_id": turn_id}}
        snap = await app.aget_state(cfg)
        if snap is None or not snap.next:  # 没有未完成的节点 → 无需续跑
            return False
        await app.ainvoke(None, config=cfg)
        return True


async def checkpoint_setup() -> None:
    """建 checkpoint 表（startup 一次，幂等）。"""
    if not settings.checkpointer_enabled:
        return
    try:
        async with _saver_ctx() as saver:
            await saver.setup()
    except Exception:  # noqa: BLE001 — 建表失败不致命，退化为无 checkpoint
        logger.warning("checkpoint setup failed", exc_info=True)
