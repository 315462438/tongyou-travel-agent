"""页面结构化抽取（PRD 6.4/6.5，评审 🔴5：结构化输出）

Phase 69：这里的输入全是抓来的页面文本（不可信），此前是裸拼进 prompt 的。
虽然 parse() 的结构化输出限制了危害形态，但 summarize_page 是自由文本且结果会流回
主上下文，注入可借它跨层传播——统一包 <external_content> 并追加外部内容规则。
"""

from app.agent.context_security import EXTERNAL_POLICY, wrap_external
from app.llm.client import get_llm
from app.schemas.hotel_schema import HotelInfo
from app.schemas.note_schema import TravelNote

HOTEL_SYSTEM = (
    "你是酒店信息抽取助手。从网页可访问性树文本中抽取酒店信息。"
    "页面文本可能含导航、广告等噪声，只抽取与酒店主体相关的信息。"
    "价格只取数字；找不到的字段留空，不要编造。"
)

NOTE_SYSTEM = (
    "你是旅行攻略总结助手。从网页文本中抽取旅行攻略信息。"
    "页面文本可能含噪声，只抽取攻略正文相关内容。找不到的字段留空列表，不要编造。"
)


def extract_hotel(page_text: str) -> HotelInfo:
    return get_llm().parse(
        f"网页文本:\n\n{wrap_external(page_text)}", HotelInfo,
        system=HOTEL_SYSTEM + EXTERNAL_POLICY,
    )


def extract_note(page_text: str) -> TravelNote:
    return get_llm().parse(
        f"网页文本:\n\n{wrap_external(page_text)}", TravelNote,
        system=NOTE_SYSTEM + EXTERNAL_POLICY,
    )


SUMMARY_SYSTEM = (
    "你是网页内容总结助手。用 2-4 句中文概括这个网页的主要内容"
    "（它是什么网站/页面、提供什么信息或服务、和旅行有什么关系）。"
    "只根据页面实际内容总结，不要编造。直接输出总结文字，不要客套。"
)


def summarize_page(page_text: str) -> str:
    """对任意页面生成一段自然语言总结（用便宜的 flash 模型）。"""
    from app.config import settings

    return get_llm().generate(
        f"网页文本:\n\n{wrap_external(page_text)}",
        model=settings.model_classifier,
        system=SUMMARY_SYSTEM + EXTERNAL_POLICY,
        max_tokens=500,
    )
