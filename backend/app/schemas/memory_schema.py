from pydantic import BaseModel, Field


class MemoryOp(BaseModel):
    """一次记忆变更操作（记忆提炼节点输出的最小单元）"""

    op: str = Field(description="操作类型：add / update / delete")
    id: str = Field(default="", description="delete 时目标记忆的 id；add/update 按 key 归槽，可留空")
    type: str = Field(
        default="preference",
        description="记忆类型：preference=稳定偏好（口味/节奏/预算习惯）；"
        "fact=事实（家庭构成/常驻城市/忌口过敏）",
    )
    key: str = Field(
        default="",
        description="三元组谓词/归类槽，优先从规范集合选：口味偏好/兴趣偏好/节奏偏好/预算偏好/"
        "住宿偏好/出行方式/常驻城市/忌口过敏/同行情况/当前行程。同一 key 会覆盖合并成一条。",
    )
    content: str = Field(default="", description="记忆内容，一句话第三人称陈述，如「用户爱吃辣」")
    explicit: bool = Field(
        default=False, description="是否来自用户本人明确表达（true=用户亲口说；false=从上下文推断）"
    )


class MemoryUpdatePlan(BaseModel):
    """记忆提炼节点输出：对长期记忆库的增删改操作列表。没有值得记的就给空列表。"""

    ops: list[MemoryOp] = Field(default_factory=list)


class MemoryTriplet(BaseModel):
    """整理后的一条规范记忆（三元组归槽，Phase 17 consolidate 用）。"""

    key: str = Field(description="归类槽，优先用规范集合里的 key")
    type: str = Field(default="preference", description="preference / fact / procedural")
    content: str = Field(description="一句话第三人称陈述")
    explicit: bool = Field(default=False, description="是否用户明确表达")


class MemoryConsolidation(BaseModel):
    """把某用户现有全部记忆重写为一组去重合并后的规范三元组。"""

    memories: list[MemoryTriplet] = Field(default_factory=list)
