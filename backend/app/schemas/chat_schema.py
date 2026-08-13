from pydantic import BaseModel, Field


class Preference(BaseModel):
    """从对话中解析出的旅行偏好（PreferenceNode 输出）"""

    destination: str = Field(default="", description="目的地城市，如「成都」；无法确定时留空")
    origin: str = Field(default="", description="出发地城市（如「合肥出发」的合肥）；没提就留空")
    waypoint_trip: bool = Field(
        default=False,
        description="用户是否在征集「从 origin 到 destination 沿途/途中/中途」的停留点推荐"
        "（如「A到B途中有什么古镇可以逛」）。是→true，且 destination 填**终点**城市，"
        "绝不要因为中途点未定而把 destination 留空",
    )
    days: int | None = Field(default=None, description="天数")
    budget: float | None = Field(default=None, description="预算（人民币，数字）")
    pace: str | None = Field(default=None, description="节奏：轻松 / 适中 / 紧凑")
    interests: list[str] = Field(default_factory=list, description="兴趣，如 美食/购物/自然/历史")
    special_requirements: list[str] = Field(default_factory=list, description="特殊要求")
    is_travel_request: bool = Field(
        default=True, description="用户这句话是否是一个旅行规划请求（闲聊/无关时为 false）"
    )
    intent: str = Field(
        default="general",
        description="本轮请求的主要意图：hotel=查酒店/住宿；route=规划路线/行程/攻略；general=其他",
    )
    wants_hotel: bool = Field(
        default=False,
        description="本轮是否包含酒店/住宿需求（即使主意图是路线规划，只要提到酒店、"
        "住宿、每晚预算等也为 true）",
    )
    let_agent_decide: bool = Field(
        default=False,
        description="用户是否把选择权交给你（如「你决定」「随便」「都行」「你安排一个热门的」"
        "「看着办」「你帮我选」）。为 true 时不要再反问，直接从上下文里挑一个最合适的具体地名",
    )
    clarification: str | None = Field(
        default=None, description="若信息不足需要反问用户，这里放一句反问；信息足够则留空"
    )


class SearchTask(BaseModel):
    type: str = Field(description="任务类型：guide/spot/food/hotel/transport")
    query: str = Field(description="搜索引擎查询词")


class SearchPlan(BaseModel):
    """TaskPlanNode 输出：搜索任务列表"""

    tasks: list[SearchTask] = Field(default_factory=list)
