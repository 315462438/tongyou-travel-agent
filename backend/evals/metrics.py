"""过程指标（2026-08-04）。

从消息 meta 直接算，不依赖 Langfuse key——评估集必须在任何环境都能跑。
指标本身不判好坏，是给人看的对照量：耗时涨了、来源少了、复用没命中，都能一眼看出。
"""

from __future__ import annotations

from dataclasses import asdict, dataclass


@dataclass
class Metrics:
    elapsed_s: float = 0.0
    chars: int = 0
    sources_n: int = 0
    xhs_n: int = 0
    has_amap: bool = False
    has_ctrip: bool = False
    images_n: int = 0
    reused: bool = False          # 本轮是否命中跨会话来源复用
    memories_used: int = 0

    def as_dict(self) -> dict:
        return asdict(self)


def collect(guide: str, meta: dict, elapsed_s: float, progress_texts: list[str]) -> Metrics:
    sources = meta.get("sources") or []
    return Metrics(
        elapsed_s=round(elapsed_s, 1),
        chars=len(guide or ""),
        sources_n=len(sources),
        xhs_n=sum(1 for s in sources if s.get("site") == "xhs"),
        has_amap=any(s.get("site") == "amap" or "高德" in (s.get("title") or "") for s in sources),
        has_ctrip=any(s.get("site") == "ctrip" or "携程" in (s.get("title") or "") for s in sources),
        images_n=sum(len(s.get("images") or []) for s in sources),
        reused=any("复用了" in t for t in progress_texts),
        memories_used=len(meta.get("memories_used") or []),
    )
