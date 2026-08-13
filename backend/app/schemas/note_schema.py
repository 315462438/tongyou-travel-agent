from pydantic import BaseModel, Field


class TravelNote(BaseModel):
    """攻略页面结构化抽取结果（PRD 6.5）"""

    title: str | None = Field(default=None, description="攻略标题")
    spots: list[str] = Field(default_factory=list, description="景点")
    restaurants: list[str] = Field(default_factory=list, description="餐厅/美食")
    photo_spots: list[str] = Field(default_factory=list, description="拍照点")
    tips: list[str] = Field(default_factory=list, description="实用建议")
    avoid_pitfalls: list[str] = Field(default_factory=list, description="避坑点")
    recommended_route: list[str] = Field(default_factory=list, description="推荐路线（按顺序）")
    estimated_cost: str | None = Field(default=None, description="花费估计描述")
    suitable_for: list[str] = Field(default_factory=list, description="适合人群")


class PageClassification(BaseModel):
    """页面类型判定（Action Guard 第三层）"""

    page_type: str = Field(
        description="页面类型：content(正常内容页) / hotel(酒店详情页) / guide(攻略页) / "
        "login_wall(登录墙) / captcha(验证码页) / payment(支付或订单页) / unknown"
    )
    reason: str = Field(description="判定理由，一句话")
