from pydantic import BaseModel, Field


class HotelInfo(BaseModel):
    """酒店页面结构化抽取结果（PRD 6.4）"""

    hotel_name: str = Field(description="酒店名称")
    address: str | None = Field(default=None, description="地址")
    price_per_night: float | None = Field(default=None, description="每晚价格（数字）")
    currency: str | None = Field(default=None, description="货币代码，如 CNY/USD/JPY")
    rating: float | None = Field(default=None, description="评分")
    review_count: int | None = Field(default=None, description="评论数量")
    pros: list[str] = Field(default_factory=list, description="优点")
    cons: list[str] = Field(default_factory=list, description="缺点")
    nearby: list[str] = Field(default_factory=list, description="周边地标/车站")
    refund_policy: str | None = Field(default=None, description="退改政策")
    suitable_for: list[str] = Field(default_factory=list, description="适合人群/场景")
