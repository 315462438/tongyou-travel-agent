"""连接管理（Phase 109）。sqlite 内存库 + TestClient，全离线。

重点不在「接口能返回列表」，而在两件容易做错的事：
  1. **断开必须真的断开** —— 只删 DB 行是装饰性的，profile 里的 cookie 还在，
     下轮照样自动登录，而界面显示「已断开」。测试三条一起断言，缺一不可。
  2. **能力边界必须出现在返回里** —— `excludes` 写了但没渲染等于没写。
"""

from contextlib import contextmanager

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.models import Base, TravelSiteLogin, TravelUser


@pytest.fixture()
def env(monkeypatch, tmp_path):
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False},
                           poolclass=StaticPool)
    Base.metadata.create_all(engine)
    maker = sessionmaker(bind=engine)

    # 每用户 profile 根目录指到 tmp，断开时真的会被删
    monkeypatch.setattr("app.config.settings.browser_profile_base", str(tmp_path / "profiles"))

    killed: list[str] = []

    class _FakePool:
        def restart(self, user_id):
            killed.append(user_id)

    monkeypatch.setattr("app.tools.browser_pool.get_pool", lambda: _FakePool())

    import app.api.connectors_api as api

    app = FastAPI()
    app.include_router(api.router)

    with maker() as db:
        db.add_all([
            TravelUser(id="ua", username="alice", password_hash="x"),
            TravelUser(id="ub", username="bob", password_hash="x"),
        ])
        db.commit()

    current = {"id": "ua"}
    from app.api.deps import get_current_user
    from app.db.session import get_db

    def fake_user():
        with maker() as db:
            return db.get(TravelUser, current["id"])

    def fake_db():
        db = maker()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_current_user] = fake_user
    app.dependency_overrides[get_db] = fake_db

    return {"client": TestClient(app), "maker": maker, "current": current,
            "killed": killed, "tmp": tmp_path}


def _login(maker, user_id, site="ctrip"):
    from datetime import datetime
    with maker() as db:
        db.add(TravelSiteLogin(user_id=user_id, site=site, logged_in_at=datetime(2026, 8, 20)))
        db.commit()


# ---------- 清单与状态 ----------

def test_list_shows_builtin_and_login_kinds(env):
    data = env["client"].get("/api/connectors").json()["connectors"]
    by = {c["key"]: c for c in data}
    assert by["amap"]["kind"] == "builtin" and by["amap"]["connected"] is True
    assert by["xhs"]["kind"] == "builtin" and by["xhs"]["connected"] is True
    # 携程没登录过 → 未连接
    assert by["ctrip"]["kind"] == "login" and by["ctrip"]["connected"] is False


def test_capability_boundary_is_exposed(env):
    """`excludes` 必须出现在返回里。

    这是本功能存在的主要理由之一：用户现在只能靠试错发现「查不到我的订单」。
    写了不渲染等于没写，所以钉住。
    """
    by = {c["key"]: c for c in env["client"].get("/api/connectors").json()["connectors"]}
    joined = "".join(by["ctrip"]["excludes"])
    assert "订单" in joined and "支付" in joined
    # 小红书要说清是平台公共账号，避免用户以为「绑自己的号」是没做完的功能
    assert "公共账号" in by["xhs"]["note"]


def test_connected_state_follows_site_login(env):
    _login(env["maker"], "ua")
    by = {c["key"]: c for c in env["client"].get("/api/connectors").json()["connectors"]}
    assert by["ctrip"]["connected"] is True
    assert by["ctrip"]["connected_at"].startswith("2026-08-20")


def test_other_users_state_is_not_visible(env):
    """按 user_id 隔离（同 Phase 15）：bob 登录过不影响 alice 看到的状态。"""
    _login(env["maker"], "ub")
    by = {c["key"]: c for c in env["client"].get("/api/connectors").json()["connectors"]}
    assert by["ctrip"]["connected"] is False


# ---------- 断开 ----------

def test_disconnect_clears_record_profile_and_browser(env):
    """三条缺一不可：DB 行没了 **且** profile 目录没了 **且** 浏览器被重启。

    只断言第一条的话，那个「只删 DB 行」的说谎实现照样能过——而它的实际后果是
    界面显示已断开、系统仍以该用户身份登录着。
    """
    import os

    from app.agent.connectors import profile_dir_of

    _login(env["maker"], "ua")
    path = profile_dir_of("ua")
    os.makedirs(path, exist_ok=True)
    with open(os.path.join(path, "Cookies"), "w") as f:
        f.write("fake-cookie")

    assert env["client"].delete("/api/connectors/ctrip").status_code == 200

    with env["maker"]() as db:
        assert db.get(TravelSiteLogin, ("ua", "ctrip")) is None      # ① 记录
    assert not os.path.exists(path)                                   # ② profile
    assert env["killed"] == ["ua"]                                    # ③ 浏览器


def test_disconnect_kills_browser_before_removing_profile(env):
    """顺序不能反：profile 被进程占用时删不掉，必须先杀进程。"""
    import inspect

    from app.agent import connectors

    src = inspect.getsource(connectors.disconnect)
    assert src.index("restart(") < src.index("rmtree("), "必须先 restart 再删 profile 目录"


def test_builtin_connectors_cannot_be_disconnected(env):
    for key in ("amap", "xhs"):
        r = env["client"].delete(f"/api/connectors/{key}")
        assert r.status_code == 400, key


def test_unknown_connector_is_404(env):
    assert env["client"].delete("/api/connectors/nope").status_code == 404


def test_disconnect_only_touches_the_caller(env):
    """断开自己的连接不能动到别人的记录。"""
    _login(env["maker"], "ua")
    _login(env["maker"], "ub")
    env["client"].delete("/api/connectors/ctrip")
    with env["maker"]() as db:
        assert db.get(TravelSiteLogin, ("ub", "ctrip")) is not None


# ---------- 不承诺系统不执行的行为 ----------

def test_no_expiry_is_promised(env):
    """不返回有效期字段。

    `site_login_ttl_min` 在浏览器池模式下是死代码（`_expire_stale_logins` 提前返回，
    Phase 68 已订正）。渲染它等于向用户承诺一个系统根本不执行的过期行为。
    """
    data = env["client"].get("/api/connectors").json()["connectors"]
    for c in data:
        assert not any(k in c for k in ("expires_at", "ttl_min", "expired")), c["key"]


# ---------- 独立扫码连接（第二期） ----------

@pytest.fixture()
def sess_env(monkeypatch):
    """把后台驱动换成可控假实现——真跑会去拉 Chrome。"""
    from app.agent import connect_session as cs

    cs._sessions.clear()
    started: list[tuple[str, str]] = []

    def fake_thread_start(sess):
        started.append((sess.user_id, sess.key))

    monkeypatch.setattr(cs, "_run", fake_thread_start)
    # 用同步调用替掉线程，测试才好断言（线程本身不是被测对象）
    monkeypatch.setattr(cs.threading, "Thread",
                        lambda target, args, name, daemon: type(
                            "T", (), {"start": lambda _self: target(*args)})())
    return {"cs": cs, "started": started}


def test_same_user_cannot_open_two_sessions(sess_env):
    """连点「连接」不能开出第二个会话——每个都要 acquire 一次浏览器，而池上限是 2。"""
    cs = sess_env["cs"]
    a = cs.start("ua", "ctrip")
    b = cs.start("ua", "ctrip")
    assert a.token == b.token
    assert len(sess_env["started"]) == 1, "第二次不该再起后台任务"


def test_finished_session_can_be_restarted(sess_env):
    """已结束的会话不算占用，用户可以重试。"""
    cs = sess_env["cs"]
    a = cs.start("ua", "ctrip")
    a.state = "timeout"
    b = cs.start("ua", "ctrip")
    assert b.token != a.token


def test_different_users_are_independent(sess_env):
    cs = sess_env["cs"]
    assert cs.start("ua", "ctrip").token != cs.start("ub", "ctrip").token


def test_cancel_is_not_overwritten_by_timeout(sess_env):
    """用户取消后，后台循环收摊时不能把状态改回 timeout——那会让界面显示得莫名其妙。"""
    cs = sess_env["cs"]
    s = cs.start("ua", "ctrip")
    assert cs.cancel("ua") is True
    cs._finish(s, "timeout", "等待超时")
    assert s.state == "cancelled"


def test_cancel_does_not_block_a_successful_login(sess_env):
    """但「取消」不该盖掉已经成功的登录：扫码已完成时以事实为准。"""
    cs = sess_env["cs"]
    s = cs.start("ua", "ctrip")
    cs.cancel("ua")
    cs._finish(s, "connected", "已连接")
    assert s.state == "connected"


def test_screenshot_url_only_exposed_while_waiting(sess_env):
    """非 waiting 态不给截图地址，前端就不会继续拉一个已删的文件。"""
    cs = sess_env["cs"]
    s = cs.start("ua", "ctrip")
    assert s.view()["screenshot_token"] == ""      # starting
    s.state = "waiting"
    assert s.view()["screenshot_token"] == s.token
    s.state = "connected"
    assert s.view()["screenshot_token"] == ""


def test_screenshot_token_is_not_the_user_id(sess_env):
    """token 必须是每次会话新生成的，不能拿 user_id 当 key。

    user_id 是长期标识，泄露一次就长期可探测；而这条路由是**不鉴权**的
    （<img> 带不了 header）。token 用完即弃才配得上那条公开路由。
    """
    cs = sess_env["cs"]
    s = cs.start("ua", "ctrip")
    assert s.token != "ua" and len(s.token) == 32


def test_connect_wait_is_shorter_than_in_turn_handoff():
    """独立连接的超时必须比轮次内的短——它失败可以重试，不该占着池槽等满 180s。"""
    from app.config import settings
    assert settings.connect_wait_s < settings.handoff_wait_s


def test_builtin_connector_cannot_start_connect(env):
    for key in ("amap", "xhs"):
        assert env["client"].post(f"/api/connectors/{key}/connect").status_code == 400


def test_status_returns_idle_not_404(env):
    """没有会话时返回 idle。前端在轮询，不该把「没事发生」表达成错误码。"""
    from app.agent import connect_session as cs
    cs._sessions.clear()
    r = env["client"].get("/api/connectors/connect/status")
    assert r.status_code == 200 and r.json()["state"] == "idle"


def test_screenshot_404_when_absent(env):
    assert env["client"].get("/api/connectors/connect/deadbeef/screenshot").status_code == 404


# ---------- 「包含的操作」必须与真实能力对账 ----------

def test_xhs_operations_match_the_readonly_whitelist():
    """小红书声明的操作 == `xhs_mcp._READONLY_TOOLS`，一个不多一个不少。

    这是本功能里最有价值的一条护栏。那份白名单是 Phase 68 的安全边界——该第三方
    MCP 还暴露 publish_content / post_comment_to_feed / like_feed 等写操作，而登录态
    是全平台共享的运维账号。连接器页面是这份边界的**用户可见投影**。

    两边分叉的两个方向都很糟：
      - 白名单放宽了而页面没跟上 → 用户看到的能力范围是假的
      - 页面写了白名单里没有的操作 → 承诺了做不到的事
    所以断言相等，不是包含。
    """
    from app.agent.connectors import get_connector
    from app.tools.xhs_mcp import _READONLY_TOOLS

    declared = {o.tool for o in get_connector("xhs").operations}
    assert declared == set(_READONLY_TOOLS), (
        f"声明={sorted(declared)} 实际白名单={sorted(_READONLY_TOOLS)}；"
        "改了白名单就要同步改连接器描述"
    )


def test_no_connector_declares_a_write_operation():
    """当前所有连接器都只读。哪天真要加写操作，这条会红——那时必须先想清楚
    授权模型（谁的账号、能撤销吗、误操作怎么办），而不是顺手加个 Operation。"""
    from app.agent.connectors import CONNECTORS

    writes = [(c.key, o.tool) for c in CONNECTORS for o in c.operations if o.write]
    assert writes == [], f"新增了写操作，请先补授权与撤销设计：{writes}"


def test_amap_operations_exist_in_code():
    """高德声明的操作必须在 app/tools/amap.py 里真有对应函数——防止清单写成愿望。"""
    import app.tools.amap as amap
    from app.agent.connectors import get_connector

    for op in get_connector("amap").operations:
        assert hasattr(amap, op.tool), f"amap.py 里没有 {op.tool}"


def test_lazy_imports_inside_connect_session_actually_resolve():
    """`connect_session` 里所有函数体内的 `from app.x import y` 必须真的存在。

    **这条是线上事故补的护栏。** 2026-08-26 首次真机点「扫码连接」直接报
    「连接过程出错」，日志里是 `No module named 'app.tools.chrome_mcp'`
    ——真实路径是 `app.tools.mcp_client`，我照着印象写错了。

    为什么其余 24 条测试全绿却没拦住：fixture 把 `_run` 整个换成了假实现，
    `_drive` 从来没被执行，函数体内的惰性 import 自然也没被解析。
    **模块顶层的 import 写错了会在 import 期就炸，函数体内的要等真跑到才炸**
    ——而"真跑到"意味着要拉起 Chrome，单测里做不到。

    所以改成静态解析 + importlib 逐个核实：不执行函数，也能验证名字存在。
    本仓库大量使用函数体内惰性导入（避免循环依赖 / 加快启动），这个失效模式
    在别处同样成立。
    """
    import ast
    import importlib
    import inspect

    from app.agent import connect_session as cs

    problems = []
    for node in ast.walk(ast.parse(inspect.getsource(cs))):
        if not isinstance(node, ast.ImportFrom):
            continue
        if not node.module or not node.module.startswith("app."):
            continue
        try:
            mod = importlib.import_module(node.module)
        except Exception as e:  # noqa: BLE001
            problems.append(f"{node.module}: 模块不存在（{e}）")
            continue
        problems += [f"{node.module}.{a.name}: 名字不存在"
                     for a in node.names if not hasattr(mod, a.name)]

    assert not problems, "惰性导入指向了不存在的东西：\n" + "\n".join(problems)


def test_backend_does_not_build_url_paths_for_the_frontend():
    """`view()` 只给 token，不给路径。

    **线上事故补的护栏**（2026-08-26）：原来返回 `/api/connectors/.../screenshot`，
    而前端挂在 `/travel/api` 下 → 图片 404，界面显示成 alt 文字「携程登录页」。

    仓库里确有在后端硬编码 `/travel/` 的写法（`auth_api` 的 avatar_url），
    但那是把部署路径散进后端各处——换个挂载点就要全仓找。
    正确的分工是：后端给标识，前端用自己的 API 常量拼路径。
    """
    from app.agent.connect_session import ConnectSession

    s = ConnectSession(user_id="u", key="ctrip", token="a" * 32)
    s.state = "waiting"
    v = s.view()
    assert v["screenshot_token"] == s.token
    assert "/" not in v["screenshot_token"], "只给 token，不要拼路径"
    assert not any(isinstance(x, str) and x.startswith("/") for x in v.values()), \
        f"view() 不该返回任何 URL 路径：{v}"


def test_connect_switches_to_qr_login_before_waiting():
    """必须先点「扫码登录」再进等待。

    携程登录页默认是账号密码表单，二维码在右侧竖排标签后面。不点这一下，
    用户对着一个表单页干等 90 秒——CLAUDE.md Phase 5 的「纯短信表单登录页会等到
    超时回退」记的就是这个现象，当时没往下追到「有个标签可以切」。

    顺序也要钉：切换必须在 `sess.state = "waiting"`（开始给用户看截图）之前，
    否则第一帧截到的是表单页。
    """
    import inspect

    from app.agent import connect_session as cs

    src = inspect.getsource(cs._drive)
    # ⚠️ 断言**调用表达式**而不是裸字符串「扫码登录」——后者会匹配到上面那段注释，
    #    把切换挪到 waiting 之后也照样绿（写这条时实测过，变异没抓住）。
    call = 'find_and_click("扫码登录"'
    assert call in src, "没有切到扫码登录"
    assert src.index(call) < src.index('sess.state = "waiting"'), \
        "切换必须在展示截图之前，否则第一帧是表单页"


def test_qr_switch_failure_does_not_abort_the_session():
    """站点改版导致找不到那个标签时，只记 warning 继续，不能让整个连接流程炸。"""
    import inspect

    from app.agent import connect_session as cs

    src = inspect.getsource(cs._drive)
    i = src.index("find_and_click")
    tail = src[i:i + 400]
    assert "logger.warning" in tail, "切换失败应降级为 warning"
    assert "return" not in tail.split("sess.state")[0], "切换失败不该提前 return"
