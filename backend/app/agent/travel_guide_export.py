"""AI edited travel-guide export.

The frontend owns normalization, layout, and DOCX rendering. This module is a
narrow JSON editor: it rewrites travel prose into a shareable guide schema while
preserving hard facts supplied by the user.
"""

from __future__ import annotations

import json
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from app.llm.client import get_llm

EXPORT_GUIDE_PROMPT_VERSION = "travel-guide-export-v1"


class ExportGuideEditRequest(BaseModel):
    prompt_version: str = EXPORT_GUIDE_PROMPT_VERSION
    normalized: dict[str, Any]


class GuideIssue(BaseModel):
    type: str
    message: str
    day: int | None = None
    severity: Literal["info", "warning", "critical"] | None = None
    sourceIds: list[str] | None = None


class TimelineItem(BaseModel):
    sourceId: str | None = None
    time: str = ""
    title: str
    description: str = ""
    type: Literal[
        "transport", "flight", "hotel", "attraction", "food", "activity",
        "shopping", "outfit", "warning", "tip", "reservation",
    ] = "activity"
    importance: Literal["critical", "important", "normal", "optional"] = "normal"
    duration: str | None = None
    price: str | None = None
    transport: str | None = None
    originalTitle: str | None = None
    originalDescription: str | None = None


class DayHotel(BaseModel):
    name: str
    city: str | None = None
    checkIn: str | None = None
    checkOut: str | None = None
    nights: int | None = None
    note: str | None = None
    sourceId: str | None = None


class GuideDay(BaseModel):
    day: int
    date: str = ""
    city: str = ""
    title: str
    subtitle: str = ""
    highlight: str = ""
    route: list[str] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)
    timeline: list[TimelineItem] = Field(default_factory=list)
    food: list[str] = Field(default_factory=list)
    outfit: str = ""
    tips: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    hotel: DayHotel | None = None


class FoodRecommendation(BaseModel):
    name: str
    city: str = ""
    category: str | None = None
    mealType: str | None = None
    price: str | None = None
    rating: str | None = None
    address: str | None = None
    recommendation: str | None = None


class PackingGroup(BaseModel):
    category: str
    items: list[str] = Field(default_factory=list)


class GuideMeta(BaseModel):
    model_config = ConfigDict(extra="allow")

    travelPlanId: str
    title: str
    subtitle: str = ""
    destination: str = ""
    dateRange: str = ""
    days: int
    nights: int
    tags: list[str] = Field(default_factory=list)
    promptVersion: str = EXPORT_GUIDE_PROMPT_VERSION
    sourceUpdatedAt: str = ""


class GuideSummary(BaseModel):
    overview: str = ""
    rhythm: str = ""
    cities: list[str] = Field(default_factory=list)
    highlights: list[str] = Field(default_factory=list)


class TravelGuideSchema(BaseModel):
    meta: GuideMeta
    summary: GuideSummary
    days: list[GuideDay]
    foodRecommendations: list[FoodRecommendation] = Field(default_factory=list)
    hotels: list[DayHotel] = Field(default_factory=list)
    packingList: list[PackingGroup] = Field(default_factory=list)
    beforeDeparture: list[str] = Field(default_factory=list)
    checklist48h: list[str] = Field(default_factory=list)
    importantNotes: list[str] = Field(default_factory=list)
    issues: list[GuideIssue] = Field(default_factory=list)


TRAVEL_GUIDE_EDITOR_SYSTEM = """你是旅行攻略的内容编辑，不是 Word 排版器。

任务：把输入的 NormalizedTravelGuide 编辑成自然、精炼、适合打印分享的中文 TravelGuideSchema JSON。

你可以做：
- 生成整趟旅行标题、副标题、标签和简介。
- 为每天生成自然的 title、subtitle、highlight。
- 润色用户原始描述，合并重复提醒，去掉啰嗦和重复。
- 将条目分类为 transport、flight、hotel、attraction、food、activity、shopping、outfit、warning、tip、reservation。
- 将重要程度判断为 critical、important、normal、optional。
- 输出适合旅行手册阅读的自然中文。

绝对禁止：
- 修改日期、时间、航班、酒店名称、订单信息、明确价格、预约信息。
- 虚构不存在的餐厅、景点、交通方式。
- 使用外部知识补全用户没有填写的信息。
- 生成 Word 样式、HTML、Markdown 或解释性文字。

冲突处理：
- 如果信息疑似冲突，保留原始信息，在 issues 增加 DATA_CONFLICT，不要猜测正确答案。
- 如果某条信息不够确定，保守表达，不要补事实。

硬信息保护：
- timeline.sourceId、time、price、hotel.name 必须保留输入中的硬事实。
- 可以润色 description，但不能改动其中的航班、预约、时间、价格和酒店名。
"""


def edit_travel_guide(normalized: dict[str, Any]) -> TravelGuideSchema:
    prompt = (
        "请编辑以下 NormalizedTravelGuide，返回符合 schema 的 TravelGuideSchema JSON。\n"
        "保留所有 day 和 timeline 条目，不要删除带 sourceId 的条目；如果要精简，只精简 description 文案。\n\n"
        + json.dumps(normalized, ensure_ascii=False)
    )
    return get_llm().parse(
        prompt,
        TravelGuideSchema,
        system=TRAVEL_GUIDE_EDITOR_SYSTEM,
        max_tokens=16000,
        effort="low",
    )
