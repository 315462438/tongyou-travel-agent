"""攻略 → 本体对象图的抽取结构（Phase 86）

这是**全系统唯一**一处「从攻略正文抽结构」的 schema，取代此前 poster / budget /
行程导入三套各抽各的。字段 description 就是抽取规范（`llm.parse` 会把 JSON Schema
注入 system prompt）。

拆成 Summary / Days 两个模型是沿用 Phase 51 攻略导入踩出来的经验：长行程一次性出完整
JSON 容易触顶被截断，分块抽取每块都短，且某一块失败不会作废其他块。
"""

from pydantic import BaseModel, Field


class StopExtraction(BaseModel):
    """行程里的一个地点。"""

    day: int = Field(description="第几天（从 1 开始）")
    order: int = Field(default=0, description="当天内的游玩顺序（从 1 开始）")
    name: str = Field(description="地点名称，用能在地图上搜到的规范名（如「灵隐寺」而非「灵隐寺附近」）")
    search_name: str = Field(
        default="", description="海外地点的英文或当地官方名（如双子塔→Petronas Towers）；国内留空"
    )
    type: str = Field(
        default="spot",
        description="类型，只能填：spot=景点 / food=餐馆美食 / checkin=打卡点 / lodging=住宿 / transit=交通中转",
    )
    note: str = Field(default="", description="一句话亮点或建议时段（15 字内）")
    transport: str = Field(default="", description="从上一个地点到这里的交通方式，如「步行」「地铁」；正文没写就留空")
    # 刻意不抽 start_time / stay_min / ticket_price：攻略里极少写全，而每个字段都要为
    # **每个地点**多输出一个键值对——结构化输出的瓶颈是 token 数，字段越多越容易顶到上限。
    # 花费统一由 TripCostExtraction 抽（那里本来就要逐项列），不在地点上重复一遍。


class DayMetaExtraction(BaseModel):
    """一天的路线命名与过夜信息。"""

    day: int = Field(description="第几天（从 1 开始）")
    title: str = Field(default="", description="路线名，如「西湖经典线」，6 字内")
    subtitle: str = Field(default="", description="路线主题短语，如「湖光山色·人文宋韵」")
    overnight_city: str = Field(default="", description="当晚住哪座城市；单城行程填该城市名")
    type: str = Field(default="stay", description="当天性质：stay=正常游玩 / transit=赶路 / return=返程")


class ExpenseExtraction(BaseModel):
    """一项开销。"""

    category: str = Field(
        description="类别，只能是：住宿/交通/餐饮/门票/大交通/其他。"
        "往返目的地的机票高铁算「大交通」，当地地铁打车算「交通」"
    )
    name: str = Field(description="项目名，如「灵隐寺门票」「西湖边民宿1晚」")
    day: int = Field(default=0, description="第几天的开销；整趟通用或分不清就填 0")
    amount: float = Field(description="金额（元），按【一个人】算。区间价如「200-300元」取中间值 250")
    note: str = Field(default="", description="备注，12 字内，可留空")


class ReservationExtraction(BaseModel):
    name: str = Field(description="需要提前预约或抢票的景点/项目名")
    channel: str = Field(default="", description="预约渠道，如「官方公众号」「官网」；正文没写就留空")
    advance: str = Field(default="", description="需提前多久，如「提前7天」；正文没写就留空")
    note: str = Field(default="", description="其他注意事项，20 字内，可留空")


class LodgingExtraction(BaseModel):
    name: str = Field(description="酒店/民宿名，尽量用能在地图搜到的规范名")
    city: str = Field(default="", description="所在城市；单城行程填目的地")
    area: str = Field(default="", description="地段/商圈，如「西湖景区旁」")
    price_text: str = Field(default="", description="价位展示文本，如「¥400/晚」；正文没写就留空")
    price: float = Field(default=0, description="每晚价格数值（元）；正文没写就填 0")
    day: int = Field(default=0, description="第几晚住这里；正文没明确对应到某天就填 0")
    source: str = Field(default="", description="来源，如「携程」「攻略作者推荐」")
    note: str = Field(default="", description="一句话亮点（12 字内）")


class NamedItemExtraction(BaseModel):
    name: str = Field(description="名称")
    note: str = Field(default="", description="一句话描述（14 字内）")


class HeadcountExtraction(BaseModel):
    """只抽一个数：出行人数（Phase 108）。

    单独成一路的理由是**代价不对称**：人数是唯一一个「错了会让下游所有金额一起错」的字段
    （Phase 67 不变式：金额一律人均口径），而它同时又是整份抽取里最便宜的一个数。
    所以让它走保守档、单独一次小调用，其余大批量抽取才敢降档提速。
    """

    headcount: int = Field(
        default=1,
        description=(
            "攻略面向的出行人数。「两大一小」填 3，「情侣/两人」填 2，没写就填 1。"
            "注意区分：「2人3天总花费6800」说的是 2 人，不是 3 人也不是 6800 人。"
        ),
    )


class TripProfileExtraction(BaseModel):
    """行程画像：标题、主题、住宿与推荐。**不含逐日地点、不含金额。**"""

    title: str = Field(description="8-14 字的标题，含目的地和天数，如「成都3日City Walk」")
    subtitle: str = Field(default="", description="一句心情语/副标题")
    theme: str = Field(
        default="", description="主题短语，用·分隔 3 段，如「西湖烟雨·茶香宋韵·运河繁华」"
    )
    destination: str = Field(description="目的地城市；多城行程填主目的地")
    days_count: int = Field(default=0, description="总天数")
    headcount: int = Field(default=1, description="攻略面向的出行人数，没写就填 1")
    lodgings: list[LodgingExtraction] = Field(
        default_factory=list,
        description="住宿推荐 0-4 个。正文没提具体酒店就给空数组，不要编造酒店名",
    )
    foods: list[NamedItemExtraction] = Field(default_factory=list, description="当地美食 0-6 个")
    specialties: list[NamedItemExtraction] = Field(
        default_factory=list, description="当地特产/伴手礼 0-4 个"
    )
    tips: list[str] = Field(default_factory=list, description="旅行贴士 0-4 条，每条一句话")


class TripItineraryExtraction(TripProfileExtraction):
    """行程主体 = 画像 + 逐日地点。**一路对应一个消费者**（手账海报）。

    刻意与旧的 `PosterData` 覆盖同样的内容：那一次调用实测 37.9s，而把它拆成
    「画像」+「逐日」两次并发反而要 53.8s（2026-08-13 实测）。抽取调用有很高的
    固定开销，能一次拿到的就别拆。
    """

    stops: list[StopExtraction] = Field(
        default_factory=list, description="全部地点，按天和游玩顺序；每天 3-7 个"
    )
    day_meta: list[DayMetaExtraction] = Field(
        default_factory=list, description="给每天起一个路线名"
    )


class TripCostExtraction(BaseModel):
    """行程花费与预约。**一路对应一个消费者**（预算明细面板）。"""

    headcount: int = Field(default=1, description="攻略面向的出行人数，没写就填 1")
    expenses: list[ExpenseExtraction] = Field(
        default_factory=list,
        description="逐项开销。只填正文里**真实出现**的金额，绝不估算编造；正文没写预算就给空数组。"
        "正文预算表里的汇总条目（如「餐饮：正餐7次×140」）要按乘式拆成明细计入。"
        "**不要**输出「合计」「总预算」这类总计项——总额由系统累加，输出总计会导致重复计算",
    )
    reservations: list[ReservationExtraction] = Field(
        default_factory=list,
        description="需提前预约/抢票的项目。依据正文里「需要预约」「提前预约」「抢票」"
        "「约满」等表述判断；正文没提就给空数组",
    )
    notes: list[str] = Field(
        default_factory=list, description="预算口径说明 0-3 条，如「不含往返大交通」"
    )
    stated_total: float = Field(
        default=0,
        description="正文自己写出的合计金额（整个团组口径，如「合计约3210元」填 3210）；"
        "没写就填 0。只照抄，不要自己算",
    )


class TripDaysExtraction(BaseModel):
    """逐日地点（按天分块，每次只覆盖几天）。"""

    stops: list[StopExtraction] = Field(default_factory=list, description="这几天的地点，按游玩顺序")
    day_meta: list[DayMetaExtraction] = Field(default_factory=list, description="这几天的路线命名")
