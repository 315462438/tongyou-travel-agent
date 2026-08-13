"""预算明细 + 预约提醒的抽取结构（Phase 67）。

字段 description 就是抽取规范——llm.parse 会把 JSON Schema 注入 system prompt。
注意：金额一律「人均」口径，汇总由服务端重算，模型不需要（也不应该）给总额。
"""

from pydantic import BaseModel, Field


class BudgetLine(BaseModel):
    """预算里的一项开销。"""

    category: str = Field(
        description="类别，只能是：住宿/交通/餐饮/门票/大交通/其他。"
        "大交通指往返目的地的机票高铁，交通指当地市内通勤"
    )
    name: str = Field(description="项目名，如「灵隐寺门票」「西湖边民宿1晚」")
    day: int = Field(default=0, description="第几天的开销，整趟通用或分不清就填 0")
    amount: float = Field(description="金额（元），按【一个人】计。区间价取中间值")
    note: str = Field(default="", description="备注，12 字内，可留空")


class ReservationItem(BaseModel):
    """需要提前预约/抢票的项目。"""

    name: str = Field(description="景点或项目名，如「故宫博物院」")
    channel: str = Field(default="", description="预约渠道，如「官方公众号」「官网」，正文没写就留空")
    advance: str = Field(default="", description="需提前多久，如「提前7天」，正文没写就留空")
    note: str = Field(default="", description="其他要注意的，20 字内，可留空")


class BudgetData(BaseModel):
    """从攻略正文抽出的预算与行前提醒。"""

    currency: str = Field(default="CNY", description="币种代码，人民币填 CNY")
    headcount: int = Field(default=1, description="攻略面向的出行人数，没写就填 1")
    items: list[BudgetLine] = Field(
        default_factory=list,
        description="预算明细。只填正文里真实出现的金额，正文没写预算就给空数组，绝对不要估算编造",
    )
    reservations: list[ReservationItem] = Field(
        default_factory=list,
        description="需要提前预约/抢票的景点。依据正文里「需要预约」「提前预约」「抢票」"
        "「约满」「官方预约」等表述判断；正文没提就给空数组",
    )
    notes: list[str] = Field(
        default_factory=list,
        description="预算相关说明 0-3 条，如「不含往返大交通」「旺季房价上浮」，每条一句话",
    )
    guide_stated_total: float = Field(
        default=0,
        description="攻略正文自己给出的合计金额（整个团组口径，如「合计约3210元」填 3210）；"
        "正文没写合计就填 0。只照抄，不要自己算",
    )
