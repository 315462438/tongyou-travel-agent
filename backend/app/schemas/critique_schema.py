from pydantic import BaseModel, Field


class GuideCritique(BaseModel):
    """攻略自检结果（反思循环节点输出）"""

    ok: bool = Field(description="攻略是否已经足够好，无需再改")
    action: str = Field(
        default="none",
        description="不 ok 时的处理：research=缺具体细节需补搜网络资料；"
        "rewrite=资料够但路线/结构/覆盖度需重写；none=已 ok",
    )
    issues: list[str] = Field(
        default_factory=list, description="发现的问题点（简短，1-3 条），rewrite 时作为改进要求"
    )
    search_queries: list[str] = Field(
        default_factory=list, description="action=research 时，需要补搜的 1-3 个搜索词（含目的地）"
    )


class PosterCritique(BaseModel):
    """手账海报自检结果"""

    ok: bool = Field(description="海报点位是否已足够详细")
    add_hints: list[str] = Field(
        default_factory=list,
        description="不 ok 时，需要补充的点位方向（如「Day2 缺餐馆」「打卡点太少」），供再抽取",
    )
