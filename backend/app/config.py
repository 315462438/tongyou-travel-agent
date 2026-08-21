from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    database_url: str
    deepseek_api_key: str = ""
    deepseek_base_url: str = "https://api.deepseek.com"

    model_planner: str = "deepseek-v4-pro"
    model_extractor: str = "deepseek-v4-pro"
    model_classifier: str = "deepseek-v4-flash"

    chrome_debug_url: str = "http://127.0.0.1:9223"
    # （已废弃的部署方式）指定 chrome 路径让 mcp 每会话自启动 headless 浏览器。
    # 持久 profile 下多会话自启动会撞 profile 锁（见 docs/pitfalls/
    # 持久profile多会话启动锁冲突.md），服务器现在改用常驻 Chrome + remote_browser。
    chrome_executable: str = ""
    # 服务器部署标记：连的是远端常驻 headless Chrome（用户看不到窗口）。
    # 影响登录 handoff 形态：true=截图直播扫码；false=本地可见窗口直接登录
    remote_browser: bool = False

    # 每用户浏览器 profile 池（Phase 19）：开启后每 user_id 一个独立 profile+Chrome，
    # 各自扫码登录、互不覆盖；不同用户可并行（受 max 限），同用户串行。关闭则回退单浏览器全局串行。
    browser_pool_enabled: bool = False
    browser_pool_max: int = 2  # 同时存活的 Chrome 上限（内存约束，超出排队）
    browser_profile_base: str = "/home/ubuntu/chrome-agent-profiles"  # 每用户 profile 根目录
    chromium_path: str = "/snap/bin/chromium"  # 池模式下后端拉起的浏览器可执行
    browser_pool_port_start: int = 9300  # 每实例调试端口从此起分配
    browser_idle_timeout_s: int = 600  # 空闲超时回收（释放内存，profile 保留）
    browser_acquire_timeout_s: int = 120  # 排队等待浏览器的上限

    @property
    def is_headless_server(self) -> bool:
        return self.remote_browser or bool(self.chrome_executable)

    # 礼貌性限速（评审 🟡4；Phase 11 调低——抓取目标多为不同域名）
    page_delay_min_s: float = 1.0
    page_delay_max_s: float = 2.5
    max_pages_per_task: int = 30  # 全轮共享一个浏览器会话后预算调大

    # token 控制（评审 🟡2）
    max_snapshot_chars: int = 30000

    # 会话 running 判定的过期兜底：最后一条 user/progress 超过该分钟数视为已中断
    turn_stale_min: int = 30

    # 用户与鉴权（Phase 15）
    # Phase 70：注册邀请码。留空=开放注册（本地开发）；线上在 .env 配 REGISTER_INVITE_CODE。
    # 理由：注册即拿到沙箱执行 + 深度研究，而资源模型（浏览器池 2 槽、小红书共享单账号、
    # LLM 账单按用量）本就不支持公开流量。
    register_invite_code: str = ""
    admin_username: str = "admin"
    admin_password: str = "admin123"  # 首次引导用，建议在 .env 覆盖后重启

    # 图级 checkpoint（Phase 16）：LangGraph 每步 state 存 PG，支持重启续跑
    checkpointer_enabled: bool = True
    history_rounds: int = 5  # 注入的对话历史轮数

    @property
    def checkpoint_conn(self) -> str:
        """checkpointer 用 psycopg 直连，去掉 SQLAlchemy 的 +psycopg 方言后缀。"""
        return self.database_url.replace("postgresql+psycopg://", "postgresql://")

    # LangGraph 反思循环（Phase 14）：生成后自检，不满意就补搜/重写再生成
    reflection_enabled: bool = True
    graph_max_guide_rounds: int = 2  # 攻略最多循环轮数
    graph_max_poster_rounds: int = 2  # 海报最多循环轮数

    # 高德地图 Web 服务 API（Phase 10）：结构化天气/景点/坐标。留空则禁用
    amap_key: str = ""
    amap_secret: str = ""  # key 的数字签名私钥
    # Phase 62：海外地理编码。生产服务器直连 OSMF Nominatim 超时，默认改用实测可达的
    # Photon（OSM POI）+ Open-Meteo（GeoNames 城市）；请求串行限速并持久缓存。
    global_geocoder_url: str = "https://photon.komoot.io"
    global_city_geocoder_url: str = "https://geocoding-api.open-meteo.com"
    global_geocoder_user_agent: str = "TravelBrowserAgent/1.0 (http://42.194.202.233/travel/)"
    global_geocoder_min_interval_s: float = 1.05

    # 记忆系统（Phase 4）
    # Langfuse 可观测埋点（Phase 24）：每轮 trace + LLM prompt/工具调用追踪。
    # 需在 Langfuse（cloud.langfuse.com 或 self-host）建项目拿 key 填入 .env；无 key 即全 no-op
    langfuse_enabled: bool = False
    langfuse_public_key: str = ""
    langfuse_secret_key: str = ""
    langfuse_host: str = "https://cloud.langfuse.com"

    # 轻量直答通道（Phase 22）：常识/建议/追问类问题跳过浏览器采集，单次流式直答
    direct_answer_enabled: bool = True
    # Phase 44 快思考模型：直答用快模型，空 = model_classifier（v4-flash）；
    # 嫌快思考质量不够可在 .env 设 MODEL_DIRECT 调回 v4-pro
    model_direct: str = ""

    # 深度研究模式（Phase 21，deepagents 试点）：对比/决策/政策类开放问题走自主 agent
    deep_research_enabled: bool = False
    deep_research_timeout_s: int = 600  # 整轮兜底超时
    # Phase 71：深度研究先给一份 15 秒可读的初步判断（感知延迟优化），完整版随后产出
    deep_research_quick_take: bool = True
    deep_research_recursion: int = 80  # agent 循环步数上限（40 实测复杂对比题会超）
    # Phase 56 提速：终稿流式（体感提速；出问题设 DEEP_RESEARCH_STREAM=false 即回退 ainvoke 老路）
    deep_research_stream: bool = True
    # 数据采集子任务（api-researcher）用的模型，空=回退快模型 v4-flash（采集不需深推理，提速）
    model_research_sub: str = ""
    # 工具硬配额（Phase 28）：prompt 纪律在长上下文会漂移（实测一轮搜 5 次、读 18 个来源
    # 把 600s 烧光超时作废），工具层强制封顶，超限返回引导文案让 agent 转入产出
    deep_research_max_searches: int = 3  # web_search 每轮上限
    deep_research_max_fetches: int = 10  # fetch_url 每轮上限（主 agent + 全部 subagent 共享）
    deep_research_max_open_pages: int = 3  # open_page（浏览器兜底读页）每轮上限
    # 上下文与预算治理（Phase 29，机制借鉴 Claude Code：留存换引用 / microcompaction）
    deep_research_source_preview_chars: int = 1500  # 抓取正文超过此长度只返回预览，全文留存待 read_source
    deep_research_read_source_chunk: int = 3000  # read_source 每次翻页返回的字符数
    deep_research_context_trim_tokens: int = 30000  # 上下文超过约多少 token 开始清理旧工具结果
    deep_research_context_keep_tools: int = 5  # 清理时保留最近 N 个完整工具结果
    # 记忆升级（Phase 30）：条数多时用小模型挑相关记忆注入（宁缺毋滥），行程记录带过期提醒
    # Phase 68：连续追问达到此轮数后，不再反问，强制代选目的地（防无限追问死循环）
    clarify_max_rounds: int = 2
    # Phase 73 在线状态（admin 用户管理）：无心跳，靠带 token 的请求刷新 last_seen_at
    online_window_s: int = 300  # 距上次活跃 ≤ 该秒数判为「在线」
    online_touch_throttle_s: int = 60  # 距上次写入不足该秒数不再写库（鉴权是最热路径）
    support_message_max_chars: int = 2000  # 客服单条消息长度上限
    # Phase 74：邀请码由管理员在后台生成（register_invite_code 保留为 .env 老钥匙的回退）
    invite_code_default_uses: int = 5
    # Phase 74：图片上传（客服 / 行程群聊共用）
    upload_dir: str = ""  # 留空 = {tmp}/travel_uploads
    upload_max_bytes: int = 5 * 1024 * 1024
    announcement_max_chars: int = 4000
    memory_select_threshold: int = 12  # 记忆超过此条数才走选择器（少量时全量注入更稳）
    memory_select_top: int = 5  # 选择器最多挑几条
    # 深度研究跨轮上下文（Phase 33，仿 Claude Code：全量历史 + 分层压缩）。
    # 临近窗口的全量压缩由 deepagents 内置 SummarizationMiddleware 提供（勿自行再挂，
    # 同名判重会炸——见 pitfalls），此处只留历史注入的两个开关
    deep_research_carry_history: bool = True  # 研究轮带全量对话历史（关=只带本轮问题，旧行为）
    deep_research_history_max_chars: int = 60000  # 全量历史字符上限，超过回退「摘要+近5轮」
    # 全链路全文历史（Phase 34）：direct/guide 也带全文历史，超限回退「摘要+近5轮全文」
    history_full_max_chars: int = 60000

    # 用户上传技能（Phase 27）：私有，仅本人深度研究会话生效
    user_skills_enabled: bool = True
    user_skill_max_bytes: int = 8 * 1024  # 单文件（纯文本粘贴）正文大小上限
    user_skill_max_zip_bytes: int = 256 * 1024  # zip 多文件技能包：解压后总大小上限
    user_skill_max_zip_files: int = 20  # zip 包内文件数上限

    # Docker 沙箱代码执行（Phase 27b）：复用已装 Docker（同机 Langfuse 也用它），
    # 共享宿主内核（namespace/cgroup 隔离，非 VM 级边界）——默认关，见
    # docs/pitfalls/Docker沙箱共享内核隔离与非root挂载权限.md
    docker_sandbox_enabled: bool = False
    # 自定义镜像（backend/docker/sandbox/），预装 python-pptx 等库——运行时 --network=none，
    # 装不上任何运行时依赖，必须在构建期就装好（Phase 27c）
    docker_sandbox_image: str = "travel-sandbox:latest"
    docker_sandbox_timeout_s: int = 60
    docker_sandbox_memory: str = "256m"
    docker_sandbox_cpus: str = "0.5"
    # Phase 69：/workspace 是宿主绑定挂载，docker 限不了磁盘（--storage-opt 依赖存储驱动），
    # execute() 前后查用量，超限清理新增大文件，防止刷爆宿主盘
    docker_sandbox_workspace_max_bytes: int = 64 * 1024 * 1024

    # 沙箱产物（Phase 27c）：agent 在沙箱里生成的文件（PPT/Word/图表等），轮末从临时目录
    # 拷贝到这里供页面下载，懒清理（每次写新产物前先扫一遍删掉过期的）
    sandbox_artifacts_dir: str = "/tmp/travel_sandbox_artifacts"
    sandbox_artifacts_ttl_min: int = 30

    # Phase 86 本体层：攻略 → TripObject 抽一次，poster/budget/行程导入全部从对象图投影。
    # 关掉则各消费者回退到各自用 LLM 从 Markdown 再解析的旧路径（保底开关，不建议常关）。
    ontology_enabled: bool = True
    # 单次抽取喂给模型的正文上限。旧路径是 guide[:5000]/[:6000]——长攻略后半段的预算和
    # 点位直接丢失；超过这个长度改走「全局一次 + 逐日分块」，每块都短且不丢尾部章节。
    ontology_extract_max_chars: int = 24000
    # 每块几天。**1 = 一天一块**：实测 3 天挤一块要 54.5s（输入是整篇、输出 11 个地点），
    # 拆成每天一块后每块只喂当天段落，并发跑，墙钟 ≈ 最慢的那一天（~15s）。
    ontology_day_batch: int = 1
    ontology_chunk_concurrency: int = 4  # 分块并发上限（10 天行程不会一次打 10 个请求）
    # 每路抽取的输出 token 上限。`llm.parse` 默认 8000 **不够**——DeepSeek 的 reasoning
    # tokens 与正文共用这个预算，模型多想几步就在 JSON 中途截断，然后重试再截断，
    # 一次失败要花 ~140s（旧的 budget 抽取同样中招，不是本体层引入的）。
    # 合法输出通常 <2000 token，给到 16000 是纯余量，不会让正常调用变慢。
    # itinerary 路（画像+逐日地点）：v4-flash @ 16000 实测最快 64.2s。
    # 8000 会截断失败（159.5s），v4-pro 反而慢（116-215s）。
    ontology_lane_max_tokens: int = 16000
    # cost 路（逐项金额）：v4-pro @ 8000 实测最快 64.3s；v4-flash 8000/16000 分别
    # 133.5s / 107.6s。快模型在拆金额这类任务上会反复推演，反而更慢。留空 = model_extractor。
    ontology_cost_model: str = ""
    ontology_cost_max_tokens: int = 8000
    # 长行程的 cost 路改用更大的输出预算。2026-08-14 抽取评估集首轮跑出来的真实缺陷：
    # itinerary 路天数多会分块，**cost 路从来不分块**——7 天海外攻略（12k 字、跨 3 地、
    # 逐项几十条）在 8000 上限处 JSON 中途截断 → 整条 cost 路失败 → 线上预算面板全空。
    # 上面那组「8000 最快」的实测是在 3-5 天短攻略上量的，长行程不适用。
    # 判据用**天数**，与 ontology_single_call_max_days 同口径（天数是输出规模的代理）。
    ontology_cost_long_days: int = 6
    ontology_cost_long_max_tokens: int = 16000
    # 天数 <= 这个值时 itinerary 路一次抽完（最快）；超过才拆成画像+逐日分块，
    # 否则输出会顶破 token 上限。判据是**天数**（输出规模的代理），不是输入字符数。
    ontology_single_call_max_days: int = 6

    memory_enabled: bool = True
    memory_max_inject: int = 30  # 每轮注入的记忆条数上限
    memory_max_rows: int = 40  # 单用户记忆条数上限（超出按权重+时间剪枝，Phase 17 兜底）
    # Phase 57 睡眠整合（chapter8 机制⑤）：轮末门控后台整理记忆（复用手动的 consolidate_memories）
    memory_sleep_consolidate_enabled: bool = True
    memory_consolidate_min_hours: int = 6  # 距上次整合至少隔这么久才再整
    memory_consolidate_min_new: int = 5  # 距上次整合后新增/变更记忆达到这么多才整
    memory_consolidate_min_total: int = 8  # 记忆总数太少不值得整理

    # 流式增量落库节拍（2026-08-13 丝滑改造）：guide/direct 流式每多少秒把增量写库一次。
    # 1.2s 曾与前端 1.5s 轮询叠加成最坏 ~2.7s 的「一段一段」跳变；0.5s 后可见粒度 ≤ ~1.3s，
    # 配合前端打字机平滑。单条 UPDATE 很轻，0.5s 粒度对本地 PG 无压力。
    streaming_flush_interval_s: float = 0.5

    # 攻略生成长度（2026-08-04）：8000 对多城长行程明显不够——线上被从「**人均（含」
    # 这种半句处切断。抬高上限 + 触到上限自动续写，用户拿到的应当是完整攻略。
    source_full_text_max_chars: int = 40000  # 单页全文入库上限（Phase 103，防 DB 膨胀）
    source_page_keep: int = 24               # 每会话保留的来源页数
    source_focus_max_chars: int = 2400       # 复用时按关键词重取的摘录上限
    llm_timeout_s: float = 180.0  # 单次 DeepSeek 请求超时（Phase 103；默认 600s 等于没有）
    guide_max_tokens: int = 16000
    guide_max_continuations: int = 2  # 最多续写几轮（16000×3 远超任何真实攻略长度）
    # guide 快答先行（2026-08-13，Phase 71 机制的 guide 版）：parse 后立刻用快模型给
    # 150 字内初步规划思路（meta.preliminary），完整攻略随后照常产出。纯增强可关。
    guide_quick_take: bool = True

    # 站点路由（Phase 3）：酒店→携程 / 路线→小红书，登录墙交给用户手动登录
    site_routing_enabled: bool = True
    # 多城行程酒店：最多为前 N 个城市抓携程实价（每城一次导航+抽取，太多拖慢整轮），其余靠搜索
    ctrip_hotel_max_cities: int = 2
    # 多城行程逐城取高德数据（天气+景点）的城市上限。高德是秒级 HTTP，比携程便宜得多，
    # 但也没必要为 6 城全查——攻略主要用前几城的天气与坐标就近排程。
    amap_max_cities: int = 3
    # Phase 59 小红书 MCP（xpzouying/xiaohongshu-mcp，服务器 docker :18060）：
    # 空 = 不启用（本地开发默认跳过）。攻略/路线/美食来源优先小红书，必应降为兜底。
    xhs_mcp_url: str = ""  # 服务器 .env: http://127.0.0.1:18060/mcp
    xhs_mcp_timeout_s: int = 40  # 单次 MCP 调用整体超时（搜索页冷加载可超 25s，实测掐死过）
    # 2026-08-14：整轮 xhs 采集总预算（搜索+全部详情）。单次 40s 超时 + 连续失败熔断都挡不住
    # 「半死」MCP（失败-成功交替 / 每篇卡在超时边缘）：最坏 2×40s 搜索 + 7×40s 详情 ≈ 5 分钟。
    # 超预算整轮放弃（返回已收集结果），必应兜底——采集不能成为无限等待窗口。
    # 2026-08-21：150 → 75。xhs 串行提速已实测否掉（容器内部串行），只剩「等多久」一个
    # 旋钮；搜索实测 16–27s，75s 够搜索 + 2–3 篇详情。晚到的不等——必应+高德已够生成，
    # xhs 是增味不是主料；且超时现在交回部分收成，不再全丢。
    xhs_collect_timeout_s: float = 75
    xhs_notes_per_turn: int = 5  # guide 每轮最多取几篇笔记详情做来源（单城）
    xhs_notes_per_city: int = 2  # 多城行程逐城各取几篇（最多 3 城）
    xhs_min_for_light_search: int = 1  # 拿到 ≥N 篇 → 必应轻量化（1 查询 4 抓取）
    xhs_skip_search_min: int = 3  # 拿到 ≥N 篇 → 必应**直接跳过**（小红书资料已足够）
    # 跨会话来源复用（2026-07-31）：同目的地近期会话的小红书**正文**可直接拿来用，
    # 省掉最贵的一步（详情逐篇串行 19-20s×5 ≈ 首轮耗时的 85%）。
    xhs_reuse_enabled: bool = True
    xhs_reuse_max_days: int = 7  # 正文复用窗口：玩法/店名/避坑半衰期以周计
    # 图片 URL 有效期实测：20h→200 / 39h→403，即 24 小时；留余量取 20，超窗口清空 images
    xhs_reuse_image_max_hours: int = 20
    # 导入协同行程：单天结构化抽取的输出上限。3000 太低——线上 6 天攻略切到**单天**
    # 仍然 JSON 中途截断（「自动分段仍失败」的真相）。
    trip_import_chunk_max_tokens: int = 16000  # 提到 16k，应对超详细攻略的单日内容
    deep_research_max_xhs: int = 4  # 深度研究每轮小红书调用配额（搜索+详情合计）
    # 小红书暂不接入（风控封锁云服务器 IP，见 docs/pitfalls/小红书风控封锁云服务器IP.md）
    # 路线规划走必应搜索；本地想启用可在 .env 设 XHS_ENABLED=true
    xhs_enabled: bool = False
    handoff_wait_s: int = 180  # 登录墙：等待用户登录的总时长
    handoff_poll_s: float = 6.0  # 登录状态轮询间隔
    price_login_wait_s: int = 90  # 拿实价的主动登录引导：等待时长（不登录也继续，只是无价）
    confirm_wait_s: int = 60  # 需登录来源的确认卡片：等用户点击的时长，超时按跳过
    # 站点登录态有效期（分钟，0=永不过期）。仅服务器模式生效：超时后清浏览器
    # cookie，下次使用重新引导扫码（Phase 9）
    site_login_ttl_min: int = 60


settings = Settings()
