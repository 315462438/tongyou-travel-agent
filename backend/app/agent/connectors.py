"""连接器清单（Phase 109）：把「这个系统连了哪些外部站点、各自能做什么」摊开给用户看。

**为什么需要它**：用户现在完全不知道系统会去携程和小红书取数据，也不知道自己的
携程登录态被记着。更糟的是能力边界不透明——问「我的携程订单」才发现做不到。

清单是**代码常量不是用户数据**，所以不入库；状态复用 `travel_site_login`
（Phase 9/15 已经是 `(user_id, site)` 按用户隔离的）。多一张表就多一处不同步。

⚠️ **不显示「有效期」**：`settings.site_login_ttl_min` 在浏览器池模式下是死代码
（`_expire_stale_logins` 直接提前返回，Phase 68 已订正）。把它渲染成过期时间等于
向用户承诺一个系统根本不执行的行为。实际寿命 ≈ 站点 cookie（携程约 13 个月）。
"""

from __future__ import annotations

import logging
import os
import shutil
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class Operation:
    """连接器实际会调用的一个操作（豆包连接器详情里的「包含的操作」那一层）。

    `tool` 是**代码里真实的工具名**，不是展示用的别名——这样才能拿它跟真实白名单
    对账。小红书那份有测试钉住：`xhs_mcp._READONLY_TOOLS` 变了而这里没跟上就会红，
    避免「用户看到的能力清单」与「系统真能做的事」悄悄分叉。
    """

    tool: str
    label: str
    write: bool = False


@dataclass(frozen=True)
class Connector:
    """一个外部数据源的声明。

    `excludes` 是刻意设的字段，不是凑数：能力边界不写出来，用户只能靠试错发现。
    写法参考 Trip.com 的连接器描述——它把「不提供预订、账户、支付或订单管理接口」
    放在描述第一屏，而不是藏在文档里。
    """

    key: str
    name: str
    kind: str  # login=需用户扫码授权 / builtin=平台内置，用户无需也无法配置
    summary: str
    provides: tuple[str, ...]
    excludes: tuple[str, ...] = ()
    note: str = ""
    operations: tuple[Operation, ...] = ()

    @property
    def connectable(self) -> bool:
        return self.kind == "login"


CONNECTORS: tuple[Connector, ...] = (
    Connector(
        key="amap", name="高德地图", kind="builtin",
        summary="地点、天气、坐标与静态地图",
        provides=("景点坐标与评分", "实时天气预报", "路线距离与时长", "地图出图"),
        note="平台内置，走服务端密钥，无需你配置。",
        operations=(
            Operation("search_poi", "搜索地点与评分"),
            Operation("geocode_address", "地址转坐标"),
            Operation("weather_forecast", "查询天气预报"),
            Operation("route_time", "估算路线时长"),
            Operation("search_hotels", "按城市找酒店"),
        ),
    ),
    Connector(
        key="xhs", name="小红书", kind="builtin",
        summary="公开笔记与实景图片",
        provides=("目的地攻略笔记", "笔记配图"),
        excludes=("你的账号与收藏", "发布、评论、点赞等写操作"),
        # 这一句是有意写给用户看的：解释「为什么不让你绑自己的号」，
        # 而不是让用户以为这是个还没做的功能（决策见 Phase 68）。
        note="使用平台的公共账号读取公开内容，不会用到、也不需要你的小红书账号。",
        # ⚠️ 必须与 xhs_mcp._READONLY_TOOLS 完全一致，有测试钉住。那份白名单是
        # Phase 68 的安全边界（该 MCP 还暴露发帖/评论/点赞等写操作），这里是它的
        # 用户可见投影——两边分叉就意味着界面在描述一个不真实的能力范围。
        operations=(
            Operation("search_feeds", "按关键词搜索公开笔记"),
            Operation("get_feed_detail", "读取笔记正文与配图"),
        ),
    ),
    Connector(
        key="ctrip", name="携程", kind="login",
        summary="酒店价格与房态",
        provides=("酒店价格区间", "房态与可订情况", "酒店实拍图"),
        excludes=("你的订单与行程", "支付与账户信息", "会员等级与权益"),
        note="需要你扫码登录，因为价格和房态与账号相关。登录态保存在你的独立浏览器里。",
        operations=(
            Operation("extract_ctrip_hotels", "读取酒店列表与价格"),
        ),
    ),
)

_BY_KEY = {c.key: c for c in CONNECTORS}


def get_connector(key: str) -> Connector | None:
    return _BY_KEY.get(key)


def profile_dir_of(user_id: str, profile_base: str | None = None) -> str:
    """该用户浏览器 profile 的磁盘路径（与 browser_pool 的拼法保持一致）。"""
    from app.config import settings

    base = profile_base if profile_base is not None else settings.browser_profile_base
    return os.path.join(base, user_id)


def list_status(logged_sites: dict[str, object]) -> list[dict]:
    """把清单与「该用户已登录的站点」合成前端要的视图。纯函数，便于离线测试。

    `logged_sites`: site -> logged_in_at（来自 travel_site_login）。
    """
    out: list[dict] = []
    for c in CONNECTORS:
        at = logged_sites.get(c.key)
        out.append({
            "key": c.key,
            "name": c.name,
            "kind": c.kind,
            "summary": c.summary,
            "provides": list(c.provides),
            "excludes": list(c.excludes),
            "note": c.note,
            "operations": [{"tool": o.tool, "label": o.label, "write": o.write}
                           for o in c.operations],
            "connectable": c.connectable,
            # builtin 恒为已就绪；login 看有没有登录记录
            "connected": True if c.kind == "builtin" else at is not None,
            "connected_at": at.isoformat() if hasattr(at, "isoformat") else None,
        })
    return out


def disconnect(db, user_id: str, key: str) -> None:
    """断开某个可登录连接器。

    ⚠️ **必须真的清掉浏览器登录态，否则界面在说谎。** 池模式下 cookie 在磁盘 profile
    里（`browser_pool` 启动参数 `--user-data-dir={profile_dir}`），而 `site_router`
    根本不读 `travel_site_login`——它是导航过去看有没有登录墙。只删那行记录的话，
    profile 里的 cookie 还在，下一轮照样自动登录，而页面显示「已断开」。

    **刻意不用 `evaluate_script` 清 `document.cookie`**：携程会话 cookie 必然是
    HttpOnly，JS 碰不到。那种实现会「执行成功但没生效」——正是本项目一直在防的
    静默失效。宁可功能粗（连带清掉该浏览器上的其他站点登录，文案已如实说明），
    也不要一个会说谎的精细实现。

    顺序不能反：先杀进程（profile 被占用时删不掉），再删目录，最后删记录。
    """
    from app.db.models import TravelSiteLogin
    from app.tools.browser_pool import get_pool

    try:
        get_pool().restart(user_id)  # 杀掉该用户的 Chrome，释放 profile 目录占用
    except Exception:  # noqa: BLE001 — 进程本来就没起时不算失败
        logger.warning("restart browser before disconnect failed user=%s", user_id, exc_info=True)

    path = profile_dir_of(user_id)
    try:
        shutil.rmtree(path, ignore_errors=True)
    except Exception:  # noqa: BLE001
        logger.warning("remove profile dir failed: %s", path, exc_info=True)

    db.query(TravelSiteLogin).filter(
        TravelSiteLogin.user_id == user_id, TravelSiteLogin.site == key
    ).delete()
    db.commit()
