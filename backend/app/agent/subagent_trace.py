"""子代理运行可视化（Phase 88）

深度研究会**并发派多个 `api-researcher`**（RESEARCH_SYSTEM 明确要求一步里一次性发多个），
但用户此前完全看不见：谁在跑、在查什么、跑了多久、烧了多少 token。等待期只有一串
扁平的足迹进度，看不出并行度，也判断不了「是不是卡住了」。

这里挂一个 LangChain callback，跟踪 `task` 工具（deepagents 的子代理派发入口）的
开始/结束，并把子代理内部的 LLM token 归属到对应子任务上，落成一条
`meta.subagents` 的 progress 消息供前端渲染成面板。

**token 归属靠 run 树**：callback 每个事件都带 `run_id` / `parent_run_id`，
deepagents 把父 callbacks 透传给子图（见 subagents.py 注释），所以子代理内部的
LLM run 顺着 parent 链一定能走回派发它的那次 `task` 工具 run。

失败一律降级为「不显示面板」，绝不能影响研究主流程——它只是观测。
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any
from uuid import UUID

logger = logging.getLogger(__name__)

# 落库节流：子代理事件密集（每次 LLM 结束都更新 token），不节流会把消息表写爆
_FLUSH_INTERVAL_S = 1.5

# 面板上每条的提示词摘要长度——够看出「这个子任务在干嘛」，又不至于撑破一行
_PROMPT_PREVIEW = 60


@dataclass
class SubagentRun:
    """一次子代理运行。`run_id` 是 LangChain 的 tool run id，用来归属 token。"""

    run_id: str
    name: str                      # subagent_type，如 api-researcher
    title: str                     # 从 description 提炼的短标题
    prompt: str                    # description 摘要
    started_at: float
    status: str = "running"        # running / done / failed
    ended_at: float | None = None
    tokens: int = 0

    def elapsed_s(self) -> float:
        return (self.ended_at or time.monotonic()) - self.started_at

    def to_dict(self) -> dict:
        return {
            "id": self.run_id,
            "name": self.name,
            "title": self.title,
            "prompt": self.prompt,
            "status": self.status,
            "tokens": self.tokens,
            "elapsed_s": round(self.elapsed_s(), 1),
        }


def _title_of(description: str, subagent_type: str) -> str:
    """从子任务描述里取一个短标题。

    描述通常是一整段任务说明，第一句/第一行往往就是任务是什么。取不到就退回类型名，
    绝不留空——面板上一条没有标题的记录等于没有信息。
    """
    text = (description or "").strip()
    if not text:
        return subagent_type or "子任务"
    # 取**最早出现**的分隔符切一刀。逐个 split 再挑「长度合适的」是错的：
    # 没找到分隔符时 split 返回整串，而整串长度恰好落在区间内就会被当成标题。
    cut = len(text)
    for sep in ("\n", "。", "；", ";", "，", ".", ","):
        i = text.find(sep)
        if i > 0:
            cut = min(cut, i)
    head = text[:cut].strip()
    return head[:20] if len(head) >= 4 else text[:20]


def _preview(text: str, limit: int = _PROMPT_PREVIEW) -> str:
    flat = " ".join((text or "").split())
    return flat[:limit] + ("…" if len(flat) > limit else "")


class SubagentTracker:
    """LangChain callback：跟踪 `task` 工具的子代理运行并落库。

    刻意不继承 `AsyncCallbackHandler`——只实现用到的几个钩子，
    LangChain 按属性名鸭子调用。少继承一层，也避免版本间基类签名漂移。
    """

    # LangChain 用它判断是否需要在后台线程里跑同步回调；我们全是内存操作，直接标可跑
    run_inline = True

    def __init__(self, cid: str) -> None:
        self.cid = cid
        self.runs: dict[str, SubagentRun] = {}
        self._order: list[str] = []
        self._parent: dict[str, str] = {}   # run_id → parent_run_id（走 run 树用）
        self._last_flush = 0.0
        self._msg_id: str | None = None

    # ---------- run 树 ----------

    def _remember_parent(self, run_id: UUID | None, parent_run_id: UUID | None) -> None:
        if run_id is not None and parent_run_id is not None:
            self._parent[str(run_id)] = str(parent_run_id)

    def _owning_run(self, run_id: UUID | None, parent_run_id: UUID | None) -> SubagentRun | None:
        """顺 parent 链往上找派发它的那次 task 运行；主 agent 自己的 LLM 调用返回 None。"""
        cur = str(parent_run_id) if parent_run_id else (str(run_id) if run_id else None)
        seen = 0
        while cur and seen < 32:  # 深度上限兜底，防环
            run = self.runs.get(cur)
            if run is not None:
                return run
            cur = self._parent.get(cur)
            seen += 1
        return None

    # ---------- callback 钩子 ----------

    def on_tool_start(
        self, serialized: dict[str, Any] | None, input_str: str,
        *, run_id: UUID | None = None, parent_run_id: UUID | None = None,
        inputs: dict[str, Any] | None = None, **kwargs: Any,
    ) -> None:
        try:
            self._remember_parent(run_id, parent_run_id)
            name = (serialized or {}).get("name") or kwargs.get("name") or ""
            if name != "task" or run_id is None:
                return
            args = inputs if isinstance(inputs, dict) else {}
            sub_type = str(args.get("subagent_type") or "subagent")
            desc = str(args.get("description") or input_str or "")
            rid = str(run_id)
            self.runs[rid] = SubagentRun(
                run_id=rid, name=sub_type,
                title=_title_of(desc, sub_type), prompt=_preview(desc),
                started_at=time.monotonic(),
            )
            self._order.append(rid)
            self._flush(force=True)  # 新子代理立刻可见，不等节流
        except Exception:  # noqa: BLE001 — 观测绝不能影响主流程
            logger.warning("subagent tracker on_tool_start failed", exc_info=True)

    def on_tool_end(self, output: Any, *, run_id: UUID | None = None, **kwargs: Any) -> None:
        self._finish(run_id, "done")

    def on_tool_error(self, error: BaseException, *, run_id: UUID | None = None, **kwargs: Any) -> None:
        self._finish(run_id, "failed")

    def on_chain_start(
        self, serialized: dict[str, Any] | None, inputs: Any,
        *, run_id: UUID | None = None, parent_run_id: UUID | None = None, **kwargs: Any,
    ) -> None:
        # 只为维护 run 树：子代理内部的 LLM 调用挂在若干层 chain 之下
        self._remember_parent(run_id, parent_run_id)

    def on_llm_start(
        self, serialized: dict[str, Any] | None, prompts: list[str],
        *, run_id: UUID | None = None, parent_run_id: UUID | None = None, **kwargs: Any,
    ) -> None:
        self._remember_parent(run_id, parent_run_id)

    def on_chat_model_start(
        self, serialized: dict[str, Any] | None, messages: Any,
        *, run_id: UUID | None = None, parent_run_id: UUID | None = None, **kwargs: Any,
    ) -> None:
        self._remember_parent(run_id, parent_run_id)

    def on_llm_end(
        self, response: Any, *, run_id: UUID | None = None,
        parent_run_id: UUID | None = None, **kwargs: Any,
    ) -> None:
        try:
            owner = self._owning_run(run_id, parent_run_id)
            if owner is None:
                return  # 主 agent 自己的调用，不计进任何子代理
            owner.tokens += _token_count(response)
            self._flush()
        except Exception:  # noqa: BLE001
            logger.warning("subagent tracker on_llm_end failed", exc_info=True)

    def _finish(self, run_id: UUID | None, status: str) -> None:
        try:
            run = self.runs.get(str(run_id)) if run_id else None
            if run is None or run.status != "running":
                return
            run.status = status
            run.ended_at = time.monotonic()
            self._flush(force=True)  # 结束状态立刻可见
        except Exception:  # noqa: BLE001
            logger.warning("subagent tracker finish failed", exc_info=True)

    # ---------- 落库 ----------

    def snapshot(self) -> list[dict]:
        return [self.runs[r].to_dict() for r in self._order if r in self.runs]

    def _flush(self, force: bool = False) -> None:
        now = time.monotonic()
        if not force and now - self._last_flush < _FLUSH_INTERVAL_S:
            return
        self._last_flush = now
        rows = self.snapshot()
        if not rows:
            return
        try:
            self._write(rows)
        except Exception:  # noqa: BLE001
            logger.warning("subagent panel write failed cid=%s", self.cid, exc_info=True)

    def _write(self, rows: list[dict]) -> None:
        """写一条独占的 progress 消息（复用已有的轮询通道，前端无需新接口）。

        带 meta 的 progress 不会被 `clear_plain_progress` 清掉，所以面板在终稿后仍在，
        用户回看时能知道这轮派了哪些子任务。
        """
        import json

        from app.db.models import TravelMessage
        from app.db.session import get_session

        payload = json.dumps({"subagents": rows}, ensure_ascii=False)
        with get_session() as db:
            if self._msg_id:
                row = db.get(TravelMessage, self._msg_id)
                if row is not None:
                    row.meta_json = payload
                    db.commit()
                    return
            msg = TravelMessage(
                conversation_id=self.cid, role="progress", content="", meta_json=payload,
            )
            db.add(msg)
            db.commit()
            self._msg_id = msg.id

    def finalize(self) -> None:
        """轮末收尾：把仍标记 running 的子代理落成结束态。

        没有这一步的话，被取消/超时的那一轮会永远留着几个转圈的绿点
        （用户回看历史时看到「还在跑」，但其实早就结束了）。
        """
        for run in self.runs.values():
            if run.status == "running":
                run.status = "done"
                run.ended_at = time.monotonic()
        self._flush(force=True)


def _token_count(response: Any) -> int:
    """从 LLM 响应里取本次用量。取不到返回 0——面板少个数字可以，报错不行。"""
    try:
        usage = getattr(response, "llm_output", None) or {}
        if isinstance(usage, dict):
            tok = usage.get("token_usage") or usage.get("usage") or {}
            if isinstance(tok, dict):
                total = tok.get("total_tokens")
                if isinstance(total, int):
                    return total
        # 新版 LangChain 把用量挂在 generations 的 message.usage_metadata 上
        for gen_list in getattr(response, "generations", []) or []:
            for gen in gen_list or []:
                msg = getattr(gen, "message", None)
                meta = getattr(msg, "usage_metadata", None)
                if isinstance(meta, dict):
                    total = meta.get("total_tokens")
                    if isinstance(total, int):
                        return total
    except Exception:  # noqa: BLE001
        pass
    return 0
