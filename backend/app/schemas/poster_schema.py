from pydantic import BaseModel, Field


class PosterStop(BaseModel):
    """海报上的一个点位（LLM 从攻略正文抽取）"""

    day: int = Field(description="第几天（从 1 开始）")
    order: int = Field(default=0, description="当天内的顺序（从 1 开始）")
    name: str = Field(description="地点名称，尽量用能在地图上搜到的规范名")
    type: str = Field(default="spot", description="类型：spot=景点 / food=餐馆美食 / checkin=打卡点")
    note: str = Field(default="", description="一句话亮点或推荐理由（15 字内）")


class PosterDayMeta(BaseModel):
    """一天=一条路线的命名（对应参考图「路线一：西湖经典线」）"""

    day: int = Field(description="第几天（从 1 开始）")
    title: str = Field(default="", description="路线名，如「西湖经典线」，6 字内")
    subtitle: str = Field(default="", description="路线主题短语，如「湖光山色·人文宋韵」")


class PosterHotel(BaseModel):
    """酒店推荐（右栏卡片）"""

    name: str = Field(description="酒店名，尽量规范可在地图搜到")
    area: str = Field(default="", description="地段/位置，如「西湖景区旁」")
    price: str = Field(default="", description="价位，如「¥400/晚」")
    note: str = Field(default="", description="一句话亮点（12 字内）")


class PosterFood(BaseModel):
    """美食推荐（右栏卡片）"""

    name: str = Field(description="菜名或餐馆名")
    note: str = Field(default="", description="一句话描述，如「酸甜鲜嫩·西湖名菜」（14 字内）")


class PosterSpecialty(BaseModel):
    """当地特产（右栏卡片）"""

    name: str = Field(description="特产名，如「西湖龙井」")
    note: str = Field(default="", description="一句话描述（12 字内）")


class PosterData(BaseModel):
    """手账海报结构化数据（LLM 抽取部分）"""

    title: str = Field(description="海报标题，如「成都3日City Walk手账」")
    subtitle: str = Field(default="", description="一句话副标题/心情语")
    theme: str = Field(
        default="", description="顶部主题短语，用·分隔，如「西湖烟雨·茶香宋韵·运河繁华」"
    )
    destination: str = Field(default="", description="目的地城市")
    stops: list[PosterStop] = Field(default_factory=list)
    day_meta: list[PosterDayMeta] = Field(default_factory=list)
    hotels: list[PosterHotel] = Field(default_factory=list, description="酒店推荐，2-4 个")
    foods: list[PosterFood] = Field(default_factory=list, description="美食推荐，3-6 个")
    specialties: list[PosterSpecialty] = Field(default_factory=list, description="当地特产，2-4 个")
    tips: list[str] = Field(default_factory=list, description="旅行贴士，2-4 条，每条一句")
