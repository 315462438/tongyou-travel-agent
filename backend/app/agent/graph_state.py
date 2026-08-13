"""LangGraph 状态定义（Phase 14）"""

from typing import Any, TypedDict


class AgentState(TypedDict, total=False):
    cid: str
    user_text: str
    user_id: str
    history: str  # 近 5 轮对话（Phase 16）
    # parse
    pref: Any  # Preference
    intent: str
    hotel_needed: bool
    route: str  # chat / clarify / apologize / plan
    # collect
    sources: list
    is_revision: bool
    # generate
    guide: str
    reasoning: str
    msg_id: str
    mem_ctx: dict
    # critique / loop
    critique: dict  # {ok, action, issues, search_queries}
    rounds: int
    feedback: str
