"""上下文清单（Phase 89，借鉴 dsh 的 "Model-visible ⟺ logged" 不变式）

## 要解决什么

`_assemble_history` 是**请求时现算**的派生结果，事后无法回答「那一轮到底喂了
什么进模型」。

> 2026-08-22 订正：此处原本还列了「改 `history_rounds` 会让边界追溯性移动」——
> 那个装配期滑动窗口已随本次改造删除，边界现在只由日志里的 replace 事件决定，
> 不再随配置漂移。清单要解决的仍是「派生结果没被记下来」这一半。

日志本身是完整的（消息从不删除、摘要也只是另存一列），缺的不是**输入**，
而是**那次派生的结果**。今天调本体抽取时就吃过这个亏：同一路抽取实测
5.6s / 229.9s 的巨大方差，但没法回看那次究竟喂了多少东西进去。

dsh 的做法是把模型可见的一切都变成日志里的事件，并用运行时断言守住。
本项目做不到那种程度的重写，但可以拿到同样的可回溯性：
**每条终稿 assistant 消息记一份清单，说明这次请求由什么装配而成。**

清单是**观测**，不参与任何判定逻辑——任何异常都只记日志。
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

# 清单里保留的历史消息 id 上限。全量历史可能上百条，清单只是回溯线索不是副本。
_MAX_IDS = 40


def build_manifest(
    *,
    history: list[dict] | None = None,
    summary: str = "",
    sources: list[dict] | None = None,
    memory_ids: list[str] | None = None,
    extra: dict[str, Any] | None = None,
) -> dict:
    """把「这次请求由什么装配而成」记成一份可回溯的清单。

    `history_mode` 是关键字段：它记录**当时**走的是全文还是「摘要+近 N 轮」，
    这样即使之后改了 `history_rounds`，也能知道那一轮实际的装配形态。
    """
    hist = history or []
    srcs = sources or []
    hist_chars = sum(len(m.get("content") or "") for m in hist)
    src_chars = sum(len(s.get("summary") or "") for s in srcs)
    manifest: dict[str, Any] = {
        # 有摘要 = 当时超了全文上限、走了压缩装配；没有 = 全文逐字注入
        "history_mode": "summary+recent" if summary else "verbatim",
        "history_count": len(hist),
        "history_chars": hist_chars,
        "summary_chars": len(summary or ""),
        "source_count": len(srcs),
        "source_chars": src_chars,
        "memory_count": len(memory_ids or []),
        # 装配总量：排查「这轮为什么特别慢/特别贵」时第一个要看的数
        "total_chars": hist_chars + len(summary or "") + src_chars,
    }
    if memory_ids:
        manifest["memory_ids"] = list(memory_ids)[:_MAX_IDS]
    if extra:
        manifest.update(extra)
    return manifest


def attach(meta: dict, manifest: dict | None) -> dict:
    """把清单挂进终稿 meta；失败绝不能影响出稿。"""
    if not manifest:
        return meta
    try:
        meta["context_manifest"] = manifest
    except Exception:  # noqa: BLE001
        logger.warning("attach context manifest failed", exc_info=True)
    return meta
