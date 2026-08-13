"""深度研究模式（Phase 21，deepagents 试点）

开放式旅行问题（多城市对比/预算测算/签证政策/帮我选）走自主 agent：
write_todos 规划 → 主 agent（持浏览器）搜索 → 派 api-researcher subagent（纯 API：
高德/fetch_url）并行收集 → 汇总为带来源的 Markdown 报告。

与主攻略流水线完全隔离：独立入口、独立超时/取消，不碰 checkpoint 图。
"""

import asyncio
import json
import logging

from app.agent.cancel import TurnCancelled, is_cancelled
from app.agent.context_security import EXTERNAL_POLICY, HEALTH_POLICY
from app.config import settings
from app.llm.client import get_llm

logger = logging.getLogger(__name__)

RESEARCH_SYSTEM = """你是 17同游 的资深旅行研究员，擅长回答开放式旅行问题：多目的地对比、
预算测算、签证/政策查询、帮用户做选择。你有一套技能库（见下方 Skills System），对比/预算/
签证政策这几类场景都有对应技能给出方法论细节，命中场景先读技能再动手，不要凭经验自由发挥。

**资源纪律（严格遵守，浏览器极贵；搜索/读页有代码层硬配额，超限会被直接拒绝）**：
- 天气、景点、地点核实：**一律派 api-researcher 子任务用高德查**（amap_city_brief 一次给出
  某城天气预报+热门景点评分坐标），绝不要为这些用 web_search！
- 攻略/美食/玩法/住宿体验类信息：**优先派 api-researcher 用 xhs_search+xhs_detail 查小红书**
  （真实用户笔记，质量远高于网页搜索；每轮有配额，一个关键词挑 1-2 篇最相关的读）。
- web_search 全程**最多 3 次**，只用于高德和小红书都覆盖不了的信息（政策/签证/时刻票价）。
  一次搜索要覆盖一个完整信息缺口（比如把两个城市并进一个 query）。
- **禁止用 open_page 打开搜索引擎页面**（google/bing/baidu 的 /search URL 一律会被
  安全层拒绝或浪费一轮）；搜索只有 web_search 这一条路。
- 搜到 URL 后**立刻打包派给 api-researcher 用 fetch_url 读**（一个子任务给它 3-5 个 URL），
  不要自己一个个开页面；只有子任务报告"读不到"的页面才用 open_page 兜底。

**时间纪律**：整轮有约 10 分钟硬超时，超时所有工作作废。资料收集控制在前几分钟、
有 5-8 个可用来源就**立刻转入产出**——宁可信息略少、缺的标注「待核实」，也绝不能超时。
工具结果尾部出现「⏳ 已用…」的预算报告时要当真：出现「❗预算即将耗尽」必须立即收尾。

**子任务纪律**：派子任务的 prompt 必须自带具体信息（明确的 URL 列表、城市名、要核实的
具体事实），**禁止**「根据你的发现去…」这类甩锅式委派；子任务结果回来后由你自己综合，
不要再派一个子任务去总结。
- **并发派发（提速关键）**：相互独立的采集子问题（如多城对比要分别查成都、重庆、西安）
  **在同一步里一次性并发派多个 api-researcher**（同一轮发出多个子任务调用，会并行执行），
  不要一个查完再派下一个。但仍**禁止**为每个 URL/页面/章节单独派——按「城市/主题」成批，
  一个子任务给它 3-5 个 URL 或一个城市的完整采集。

**记笔记纪律**：上下文超限时旧的工具结果会被自动清理成占位符。每读完一个来源，如果里面
有之后要用的关键事实（价格、时刻、电话、评分、结论），**先在回复里用 1-2 句话记下要点**
再读下一个——只有你自己写下的内容保证一直保留；被清理的来源可用 read_source 重读。

工作方式：write_todos 拆解 → 先派高德子任务拿天气/景点 → 至多 3 次搜索补缺口 →
派子任务读页 → 汇总。

产出要求：结构化 Markdown 报告，关键数据标注来源网站名，全文中文，直接输出报告正文。
**报告写完即整轮结束**——不要在报告之后再单独发一条「报告已生成」「总结一下」之类的
收尾消息（系统取最后的正文当终稿，收尾消息会顶掉报告本体）。""" + EXTERNAL_POLICY

API_RESEARCHER_PROMPT = """你是数据收集员。你有一套技能库（见下方 Skills System），高德查询
组合用法、网页抓取结果取舍的细节方法论都在里面，命中场景先读技能再动手。

用手头工具完成主 agent 派来的收集任务：
- amap_city_brief(city)：城市天气预报 + 热门景点
- amap_poi(keyword, city)：核实具体地点/坐标
- xhs_search(keyword) / xhs_detail(feed_id, xsec_token)：搜/读小红书笔记
  （攻略/美食/玩法体验优先用它，一个关键词挑 1-2 篇最相关的读，别把配额烧光）
- fetch_url(url)：抓网页正文

把查到的事实**原样、带数字、注明出处**汇总成一份紧凑报告返回，不要发挥。""" + EXTERNAL_POLICY

# deepagents 会自动挂一个内置 general-purpose subagent（除非显式覆盖，见 create_deep_agent
# 文档），拿到的工具/技能默认跟主 agent 一样（含浏览器！），但用的是框架自带的通用 prompt，
# 不包含我们写在 RESEARCH_SYSTEM 里的资源纪律。这里显式定义同名 subagent 覆盖掉默认版本，
# 把资源纪律也写进去，避免它绕开"浏览器只在主 agent 谨慎用"这条约束。
GENERAL_PURPOSE_PROMPT = """你是通用助手 subagent：适合承接主 agent 甩来的、需要隔离上下文的
复杂多步子任务（比如在大量已抓取资料里翻找一个不确定能不能一次找到的信息、整理一段独立的
长文本）。跑完只需要把结论压缩成一份简报返回，不需要保留过程细节。

你和主 agent 共用同一套技能库（见下方 Skills System）和同一个浏览器工具
（web_search/open_page）——**浏览器是全局共享的稀缺资源，不是你独占的**：
- 能不用浏览器就不用，你的任务多数应该是"整理/查找已有信息"而不是"重新去网上搜"；
- 真要用 web_search，一次任务里最多 1-2 次，query 要一次覆盖完整信息缺口；
- 不要把自己当成搜集新资料的主力，那是主 agent 和 api-researcher 的职责。""" + EXTERNAL_POLICY

# 沙箱开启时追加到主 agent / general-purpose 的 system prompt。关键是第一条路径映射——
# 文件工具的虚拟根 `/` 与容器挂载点 `/workspace` 是同一目录（backend 侧已做别名，见
# DockerSandboxBackend._resolve_path），这里再明说一次，避免模型在两套坐标系间来回猜。
SANDBOX_NOTE = """

**代码执行沙箱已开启**（execute 工具，在隔离容器里跑 shell 命令）：
- 文件工具（ls/read_file/write_file/glob/grep）的根目录 `/` 和 execute 里的 `/workspace`
  是**同一个目录**：`write_file("/workspace/x")` 和 `write_file("/x")` 等价，写完的文件在
  execute 里就是 `/workspace/x`。
- execute 的工作目录固定为 /workspace；容器内其余路径只读，产物一律放 /workspace 下。
- 容器**没有网络**：装依赖/下载都做不了，只能用镜像里已有的 python3/node 等。
- **一次成稿**：代码/文档/PPT 由你自己直接 write_file 完整写出、execute 验证，
  **禁止**为每个文件/页面/章节单独派 subagent——那会把整轮时间预算烧光导致超时作废。"""


QUICK_TAKE_SYSTEM = (
    "你要在几秒内给出一个**初步判断**，随后系统会去查实时资料出完整版。\n"
    "要求：\n"
    "- 150 字以内，先直接给结论/倾向，再用一两条理由支撑；\n"
    "- 只说你有把握的常识性内容，**不要编造**价格、班次、营业时间这些需要实时核实的数字；\n"
    "- 时间/节假日表述必须与用户问题一致（用户问国庆就只谈国庆，不要串成春节/暑假）；\n"
    "- 不要说「我将要去搜索」之类的过程话，也不要列长清单；\n"
    "- 结尾不用加免责声明，系统会自动标注这是初步回答。"
) + HEALTH_POLICY


async def _emit_quick_take(cid: str, user_text: str, user_id: str) -> None:
    """先落一条「初步回答」消息（Phase 71 感知延迟优化）。best-effort，失败静默跳过。"""
    from app.agent.memory import gather_context
    from app.agent.orchestrator import _add_message, _progress

    if not settings.deep_research_quick_take:
        return
    try:
        mem = gather_context(cid, "", user_id, user_text=user_text)
        prefix = f"{mem['block']}\n\n" if mem.get("block") else ""
        text = await asyncio.to_thread(
            get_llm().generate,
            f"{prefix}用户的问题：{user_text}",
            model=settings.model_classifier,
            system=QUICK_TAKE_SYSTEM,
            max_tokens=400,
        )
        if is_cancelled(cid):  # 生成期间用户点了停止 → 不要再往会话里塞消息
            return
        if (text or "").strip():
            _add_message(cid, "assistant", text.strip(), meta={"preliminary": True})
            _progress(cid, "💡 已给出初步判断，正在查证并展开完整分析…")
    except Exception:  # noqa: BLE001 — 纯增强，绝不能影响深度研究主流程
        logger.warning("quick take failed cid=%s", cid, exc_info=True)


async def run_deep_research(cid: str, user_text: str, user_id: str, sandbox_enabled: bool = False) -> None:
    """入口：跑深度研究 agent，终稿写 travel_message。由 orchestrator 路由调用。

    `sandbox_enabled` 是这一轮用户在消息旁打开的「沙箱执行」开关（Phase 27c），最终是否
    真给 agent 代码执行能力还要看服务器 `docker_sandbox_enabled` 有没有开——两个都是
    True 才生效，见 `_build_backend`。
    """
    from app.agent.orchestrator import (
        _add_message, _add_streaming_message, _finalize_streaming_message,
        _progress, clear_plain_progress,
    )
    from app.agent.research_tools import BrowserSession, build_tools
    from app.agent.skills_loader import load_skill_files

    _progress(cid, "🧭 这是个开放式问题，进入深度研究模式（规划 → 搜集 → 汇总）…")

    # Phase 56：流式时先占一条 streaming 消息，终稿/报错都落到它上（非流式为 None → 走 _add_message）
    # ⚠️ 顺序要求（Phase 71）：占位必须在快答**之前**建立。快答是一条非流式 assistant 消息，
    # 若此时没有流式占位，_is_running 会判本轮已完成 → 前端停止轮询，完整版永远收不到。
    stream_msg_id: str | None = _add_streaming_message(cid) if settings.deep_research_stream else None

    # Phase 71 快答先行：深度研究要 4-6 分钟，很多用户以为卡死就走了。先用快模型给一份
    # 15 秒内可读的初步判断（无浏览器、无来源），让用户立刻有东西看；完整版随后照常产出。
    # 纯增强：失败/被停止都不影响主流程。
    await _emit_quick_take(cid, user_text, user_id)

    session = BrowserSession(cid, user_id)
    sources: list[dict] = []
    skill_files = load_skill_files(user_id=user_id)
    turn_messages, mem_ctx = _build_turn_messages(cid, user_text, user_id)
    backend, sandbox_tmp_dir, seed_paths = _build_backend(user_id, sandbox_enabled)
    stream_state: dict = {}

    def _emit(text: str, meta: dict | None) -> None:
        if stream_msg_id:
            _finalize_streaming_message(stream_msg_id, text, stream_state.get("reasoning", ""), meta or {})
        else:
            _add_message(cid, "assistant", text, meta=meta or None)

    try:
        agent = _build_agent(
            cid, user_id, session, sources, backend,
            # 没上传过技能就别声明 /user/ 技能源——deepagents 对不存在的目录每轮报
            # "Cannot load skills from '/user/': path_not_found"（无害但刷日志）
            user_skills=any(p.startswith("/user/") for p in skill_files),
        )
        _invoke = _invoke_streaming if stream_msg_id else _invoke_with_cancel
        result = await asyncio.wait_for(
            _invoke(
                cid, agent, user_text, user_id,
                skill_files=skill_files, turn_messages=turn_messages,
                stream_msg_id=stream_msg_id, stream_state=stream_state,
            ),
            timeout=settings.deep_research_timeout_s,
        )
        answer = _extract_answer(result)
        if not answer:
            raise RuntimeError("agent 没有产出回答")
        meta = {}
        if sources:
            meta["sources"] = _dedupe(sources)
        skills_used = _extract_skills_used(result)
        if skills_used:
            meta["skills_used"] = skills_used
        if sandbox_tmp_dir:
            artifacts = _collect_sandbox_artifacts(sandbox_tmp_dir, seed_paths)
            if artifacts:
                meta["artifacts"] = artifacts
        # Phase 33 轮末钩子（与 guide/direct 对齐）：记忆提炼 + 历史摘要折叠。
        # extract_and_save/update_history_summary 内部自带失败兜底，不会拖垮终稿。
        if mem_ctx.get("used"):
            meta["memories_used"] = mem_ctx["used"]
        from app.agent.memory import extract_and_save
        from app.agent.orchestrator import update_history_summary

        saved = extract_and_save(cid, user_text, answer, user_id)
        if saved:
            meta["memories_saved"] = saved
        _emit(answer, meta)
        update_history_summary(cid)
        clear_plain_progress(cid)
    except TurnCancelled:
        raise  # 流式占位由外层 _ensure_stopped_message 统一收尾（与 guide 一致）
    except asyncio.TimeoutError:
        logger.warning("deep research timeout for %s", cid)
        _emit("研究超时了，问题可能太大。可以拆小一点再问我，比如先问其中一个城市。", None)
    except Exception as e:  # noqa: BLE001 — 步数超限等：优雅降级而不是裸「出错了」
        from langgraph.errors import GraphRecursionError

        if isinstance(e, GraphRecursionError):
            logger.warning("deep research recursion limit for %s", cid)
            _emit(
                "这个问题研究步骤太多，没能在限定步数内收敛。建议拆小一点再问"
                "（比如一次只对比两个维度），或者关掉深度推理先要一个快速回答。", None,
            )
        elif stream_msg_id:  # 流式下未知错误：定稿占位消息，别留孤儿 streaming
            logger.error("deep research failed for %s", cid, exc_info=True)
            _emit("抱歉，研究过程中出错了，请重试。", None)
        else:
            raise
    finally:
        await session.close()
        if sandbox_tmp_dir:
            import shutil

            shutil.rmtree(sandbox_tmp_dir, ignore_errors=True)


def _build_backend(user_id: str, sandbox_enabled: bool = False):
    """默认 (None, None, set()) → deepagents 用 `StateBackend()`（技能/草稿文件走图状态，
    零新故障面）。

    只有**服务器开关**（`settings.docker_sandbox_enabled`，运维决定这台机器具不具备
    这个能力）和**本轮开关**（`sandbox_enabled`，用户在消息旁自己选的，Phase 27c）
    同时为真，才换成**纯** `DockerSandboxBackend`（不再包一层 `CompositeBackend`）：
    技能文件在轮初就物理写进这个 per-turn host 临时目录（`_write_skill_files_to_dir`），
    ls/read/write/grep/glob/execute 全部由这一个 backend 处理。

    **不用 `CompositeBackend(default=沙箱, routes={"/main/": state, ...})` 这个曾经的方案**：
    那样会让三个路由共享同一个 `StateBackend()` 实例——但 `CompositeBackend` 的 glob/ls
    聚合逻辑假设"每个路由背后的 backend 返回的是相对自己根目录的路径"，而共享的
    `StateBackend` 内部其实是全局绝对路径（`/main/xxx`、`/researcher/xxx` 都在同一份
    flat dict 里），两边对不上，会产生 `/main/main/xxx/SKILL.md` 这种二次拼前缀的错乱
    路径（实测踩到，见 docs/pitfalls/）。改成单一 backend 后没有多路由聚合这一层，
    这个问题不存在。

    返回 (backend, 临时目录, 种子文件相对路径集合)——种子文件集合是"轮初写进去的技能
    文件"基线，轮末用来 diff 出 agent 真正产出的产物（`_collect_sandbox_artifacts`）。
    """
    if not (settings.docker_sandbox_enabled and sandbox_enabled):
        return None, None, set()

    import os
    import tempfile

    from app.tools.docker_sandbox import DockerSandboxBackend

    tmp_dir = tempfile.mkdtemp(prefix="travel-sandbox-")
    os.chmod(tmp_dir, 0o777)  # 容器内非 root 用户（--user nobody）要能写这个挂载目录
    seed_paths = _write_skill_files_to_dir(tmp_dir, user_id)
    return DockerSandboxBackend(tmp_dir), tmp_dir, seed_paths


def _write_skill_files_to_dir(root_dir: str, user_id: str) -> set[str]:
    """把内置 + 用户技能物理写进沙箱的 per-turn 临时目录，返回写入的相对路径集合。

    沙箱场景下没有 `StateBackend` 可用（技能不再经图状态种子传入），技能只能是
    这个临时目录里的真实文件——`DockerSandboxBackend` 的 `virtual_mode=True` 已经把
    ls/read/write/grep/glob 限定在这个目录内，技能文件写在这儿天然就在同一套隔离范围里。
    """
    import os

    from app.agent.skills_loader import load_skill_files

    seed_paths: set[str] = set()
    for vpath, file_data in load_skill_files(user_id=user_id).items():
        rel = vpath.lstrip("/")
        full_path = os.path.join(root_dir, rel)
        os.makedirs(os.path.dirname(full_path), exist_ok=True)
        with open(full_path, "w", encoding="utf-8") as f:
            f.write(file_data["content"])
        seed_paths.add(rel)
    return seed_paths


_ARTIFACT_MAX_FILES = 20
_ARTIFACT_MAX_TOTAL_BYTES = 20 * 1024 * 1024


def _collect_sandbox_artifacts(tmp_dir: str, seed_paths: set[str]) -> list[dict]:
    """轮末 diff 沙箱临时目录跟种子文件基线，把 agent 新产出的文件拷进持久化产物目录
    （`sandbox_artifacts_dir/{batch_key}/`），返回 `meta.artifacts` 用的元信息列表。

    产物用扁平化文件名存（相对路径把 "/" 换成 "__"），避免下载端点要处理子目录/路径穿越；
    数量和总大小都有上限，防止 agent 在沙箱里堆一堆无关文件。

    ⚠️ 安全（Phase 69）：**绝不能跟随符号链接**。沙箱容器以 nobody 跑、根只读、无网络，
    但 /workspace 是 rw 绑定挂载，容器内可以 `ln -s /home/ubuntu/.../.env leak.txt`；
    而本函数跑在**宿主后端进程**里（uid=ubuntu，读得到 .env），一旦跟随软链就会把宿主密钥
    拷进不鉴权的产物下载目录 —— 实测可拖走 DeepSeek key / PG 密码 / 高德 secret。
    因此：软链一律跳过 + 真实路径必须仍在沙箱目录内 + 拷贝也不跟随。
    """
    import os
    import shutil
    import uuid

    _cleanup_expired_artifacts()

    tmp_root = os.path.realpath(tmp_dir)
    candidates: list[tuple[str, str, int]] = []  # (完整路径, 展示名, 大小)
    # followlinks=False：不下潜进软链目录（os.walk 默认值，显式写出以表明是安全要求）
    for dirpath, dirnames, filenames in os.walk(tmp_dir, followlinks=False):
        # 软链目录即使不下潜也不该出现在遍历里，直接从 dirnames 剔除
        dirnames[:] = [d for d in dirnames if not os.path.islink(os.path.join(dirpath, d))]
        for name in filenames:
            full = os.path.join(dirpath, name)
            rel = os.path.relpath(full, tmp_dir)
            if rel in seed_paths:
                continue
            if os.path.islink(full):
                logger.warning("跳过沙箱产物中的符号链接：%s -> %s", rel,
                               os.readlink(full) if os.path.lexists(full) else "?")
                continue
            # 双保险：解析后仍必须落在沙箱目录内（防软链目录残留等边角情况）
            if not os.path.realpath(full).startswith(tmp_root + os.sep):
                logger.warning("跳过逃出沙箱目录的产物：%s", rel)
                continue
            try:
                st = os.lstat(full)  # lstat 不跟随软链
            except OSError:
                continue
            if not os.path.isfile(full) or st.st_size == 0:
                continue
            candidates.append((full, rel.replace(os.sep, "__"), st.st_size))

    if not candidates:
        return []

    batch_key = uuid.uuid4().hex
    dest_dir = os.path.join(settings.sandbox_artifacts_dir, batch_key)
    os.makedirs(dest_dir, exist_ok=True)

    artifacts: list[dict] = []
    total_bytes = 0
    for full, display_name, size in candidates:
        if len(artifacts) >= _ARTIFACT_MAX_FILES or total_bytes + size > _ARTIFACT_MAX_TOTAL_BYTES:
            logger.warning("sandbox artifacts truncated: %d candidates, kept %d", len(candidates), len(artifacts))
            break
        try:
            # follow_symlinks=False：即便上面的检查被绕过，也不会解引用到宿主文件
            shutil.copy2(full, os.path.join(dest_dir, display_name), follow_symlinks=False)
        except OSError:
            logger.warning("failed to copy sandbox artifact %s", full, exc_info=True)
            continue
        total_bytes += size
        artifacts.append({
            "name": display_name,
            "size": size,
            # 相对于前端 API 常量的路径（前端已含 "/api" 前缀，见 frontend/src/api.ts）
            "url": f"/sandbox-artifacts/{batch_key}/{display_name}",
        })
    return artifacts


def _cleanup_expired_artifacts() -> None:
    """懒清理：每次要写新产物前先扫一遍，删掉超过 TTL 的旧产物目录（不额外起后台线程）。"""
    import os
    import shutil
    import time

    root = settings.sandbox_artifacts_dir
    if not os.path.isdir(root):
        return
    cutoff = time.time() - settings.sandbox_artifacts_ttl_min * 60
    for name in os.listdir(root):
        path = os.path.join(root, name)
        try:
            if os.path.isdir(path) and os.path.getmtime(path) < cutoff:
                shutil.rmtree(path, ignore_errors=True)
        except OSError:
            continue


def _build_agent(cid: str, user_id: str, session, sources, backend=None, user_skills: bool = True):
    import os

    os.environ.setdefault("DEEPSEEK_API_KEY", settings.deepseek_api_key)
    from deepagents import create_deep_agent
    from langchain_deepseek import ChatDeepSeek

    main_tools, sub_tools = _tools(cid, user_id, session, sources)
    model = ChatDeepSeek(model=settings.model_planner, api_base=settings.deepseek_base_url)
    # Phase 56 模型分层：数据采集子任务用快模型（高德/抓正文不需深推理 → 更快更省），
    # 主 agent 保持 v4-pro（规划/汇总要质量）。空配置回退 v4-flash。
    sub_model = ChatDeepSeek(
        model=settings.model_research_sub or settings.model_classifier,
        api_base=settings.deepseek_base_url,
    )
    main_skills = ["/main/", "/user/"] if user_skills else ["/main/"]
    sandbox_note = SANDBOX_NOTE if backend is not None else ""
    return create_deep_agent(
        model=model,
        tools=main_tools,
        system_prompt=RESEARCH_SYSTEM + sandbox_note,
        skills=main_skills,
        # 分层压缩（Phase 29/33，对齐 Claude Code microcompact+autocompact）：
        # 第一层 = 工具结果定向清理（可用 read_source 找回）；第二层全量摘要**不要自己挂**——
        # deepagents 内置 SummarizationMiddleware（被驱逐历史落盘 /conversation_history/、
        # 可 read_file 找回 + 溢出兜底重试），再挂同名实例会触发
        # "Please remove duplicate middleware instances"（线上踩坑，见 pitfalls）
        middleware=[_context_trim_middleware()],
        backend=backend,
        subagents=[
            {
                "name": "api-researcher",
                "description": "数据收集员：查高德城市天气/景点、核实地点坐标、纯 HTTP 抓取网页正文。"
                               "适合并行收集，不占浏览器。",
                "system_prompt": API_RESEARCHER_PROMPT,
                "tools": sub_tools,
                "skills": ["/researcher/"],
                "model": sub_model,  # Phase 56：采集用快模型提速
            },
            {
                # 显式定义同名 subagent，覆盖 deepagents 自动挂载的默认 general-purpose
                # （否则拿到主 agent 同款浏览器工具却没有资源纪律，见 GENERAL_PURPOSE_PROMPT 注释）
                "name": "general-purpose",
                "description": "通用助手：适合隔离上下文的复杂多步子任务（翻找资料、整理长文本），"
                               "跟主 agent 共享同一套工具/技能。",
                "system_prompt": GENERAL_PURPOSE_PROMPT + sandbox_note,
                "tools": main_tools,
                "skills": main_skills,
                "middleware": [_context_trim_middleware()],
            },
            # api-researcher 不挂清理中间件：单个子任务上下文短，清了反而丢它正要汇总的原文
        ],
    )


def _context_trim_middleware():
    """旧工具结果清理（Phase 29，microcompaction）：上下文超过 trigger 时把最旧的工具
    结果换成占位符、保留最近 keep 个完整结果——治「抓的网页越多、后程 LLM 越肥越慢」。
    ClearToolUsesEdit 对齐 Anthropic clear_tool_uses_20250919 行为；approximate 计数
    对中文偏差大，trigger 取保守值（settings 可调）。
    """
    from langchain.agents.middleware import ContextEditingMiddleware
    from langchain.agents.middleware.context_editing import ClearToolUsesEdit

    return ContextEditingMiddleware(edits=[ClearToolUsesEdit(
        trigger=settings.deep_research_context_trim_tokens,
        keep=settings.deep_research_context_keep_tools,
        placeholder="[旧工具结果已清理以节省上下文；如需重看该来源请用 read_source]",
    )])


def _tools(cid, user_id, session, sources):
    from app.agent.research_tools import build_tools

    return build_tools(cid, user_id, session, sources)


HEARTBEAT_EVERY_S = 60  # 心跳进度间隔（Phase 28）


def _build_turn_messages(cid: str, user_text: str, user_id: str) -> tuple[list[dict], dict]:
    """研究轮消息装配（Phase 33，仿 Claude Code 全量轨迹）：

        [全量历史（逐字交替消息，append-only → 跨轮前缀缓存命中）]
        + user: <background_memory>记忆</> + 本轮问题（易变内容末置，不打破历史前缀）

    保险：全量历史超 `deep_research_history_max_chars` → 回退窄窗形态
    （<conversation_summary> + 近 5 轮截断）；`deep_research_carry_history` 关 →
    只带本轮问题（旧行为）。任何装配失败都退化为旧行为——历史/记忆是增强，
    不能让整轮研究起不来。
    """
    fallback = ([{"role": "user", "content": user_text}], {"block": "", "used": []})
    try:
        from app.agent.memory import gather_context
        from app.agent.orchestrator import _full_history_messages, _history_context

        mem_ctx = gather_context(cid, "", user_id, user_text=user_text)
        user_parts: list[str] = []
        history: list[dict] = []
        if settings.deep_research_carry_history:
            history = _full_history_messages(cid)
            if sum(len(m["content"]) for m in history) > settings.deep_research_history_max_chars:
                history, summary = _history_context(cid)
                if summary:
                    user_parts.append(f"<conversation_summary>\n{summary}\n</conversation_summary>")
        # 本轮用户消息在路由前已落库，历史尾部会重复出现——去掉，问题只在末条 user 里出现一次
        if history and history[-1]["role"] == "user" and history[-1]["content"].strip() == user_text.strip():
            history = history[:-1]
        if mem_ctx.get("block"):
            user_parts.append(f"<background_memory>\n{mem_ctx['block']}\n</background_memory>")
        user_parts.append(user_text)
        return history + [{"role": "user", "content": "\n\n".join(user_parts)}], mem_ctx
    except Exception:  # noqa: BLE001
        logger.warning("build turn messages failed, fallback to bare question", exc_info=True)
        return fallback


async def _invoke_with_cancel(
    cid: str, agent, user_text: str, user_id: str,
    skill_files: dict | None = None, turn_messages: list[dict] | None = None,
    stream_msg_id: str | None = None, stream_state: dict | None = None,  # 非流式不用，签名对齐
):
    """agent.ainvoke 包一层取消看护：工具层异常可能被 ToolNode 吞掉，这里保证停止按钮硬生效。"""
    from app.agent.skills_loader import load_skill_files
    from app.observability import langchain_handler

    if skill_files is None:  # run_deep_research 已加载则复用，避免重复查一次用户技能
        skill_files = load_skill_files(user_id=user_id)
    config: dict = {"recursion_limit": settings.deep_research_recursion}
    handler = langchain_handler()  # Langfuse：agent 全图追踪（每轮 messages+工具调用+子agent）
    if handler is not None:
        config["callbacks"] = [handler]
    task = asyncio.ensure_future(agent.ainvoke(
        {"messages": turn_messages or [{"role": "user", "content": user_text}], "files": skill_files},
        config=config,
    ))
    try:
        elapsed = 0
        while not task.done():
            if is_cancelled(cid):
                task.cancel()
                raise TurnCancelled()
            await asyncio.sleep(1)
            elapsed += 1
            # 心跳进度（Phase 28）：模型长推理/子任务/沙箱写代码期间不会产生工具 progress，
            # 前端最后一个气泡会一直转圈像卡死——定期报一次还活着 + 已用时
            if elapsed % HEARTBEAT_EVERY_S == 0:
                minutes = max(elapsed // 60, 1)
                budget_min = settings.deep_research_timeout_s // 60
                _heartbeat(cid, f"🧠 研究进行中（第 {minutes} 分钟 / 预算约 {budget_min} 分钟）——"
                                "模型正在思考、整理或写产物，这个阶段没有新的工具进度是正常的")
        return task.result()
    finally:
        if not task.done():
            task.cancel()


def _heartbeat(cid: str, text: str) -> None:
    """写一条心跳 progress；失败（DB 抖动等）绝不能影响研究主流程。"""
    try:
        from app.agent.orchestrator import _progress

        _progress(cid, text)
    except Exception:  # noqa: BLE001
        logger.warning("heartbeat progress failed for %s", cid, exc_info=True)


async def _heartbeat_loop(cid: str) -> None:
    """流式期间的后台心跳（模型思考/工具执行静默期仍报「还在研究」+ 已用时）。"""
    elapsed = 0
    budget_min = settings.deep_research_timeout_s // 60
    try:
        while True:
            await asyncio.sleep(HEARTBEAT_EVERY_S)
            elapsed += HEARTBEAT_EVERY_S
            minutes = max(elapsed // 60, 1)
            _heartbeat(cid, f"🧠 研究进行中（第 {minutes} 分钟 / 预算约 {budget_min} 分钟）——"
                            "模型正在思考、整理或写产物，正常现象")
    except asyncio.CancelledError:
        return


def _is_ai_chunk(msg) -> bool:
    cls = type(msg).__name__
    mtype = getattr(msg, "type", "")
    if mtype == "tool" or "Tool" in cls:  # 工具结果（可能很大）不进流
        return False
    return mtype in ("ai", "AIMessageChunk") or "AIMessage" in cls


def _chunk_text(msg) -> str:
    """从流式消息块里取「AI 文本增量」（报告正文）；工具调用/结果不入流。"""
    if not _is_ai_chunk(msg):
        return ""
    content = getattr(msg, "content", None)
    if not content:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, list):  # 多段 content 块
        parts = []
        for c in content:
            if isinstance(c, str):
                parts.append(c)
            elif isinstance(c, dict) and c.get("type") in (None, "text") and c.get("text"):
                parts.append(c["text"])
        return "".join(parts)
    return ""


def _chunk_reasoning(msg) -> str:
    """取思考链增量（langchain-deepseek 放在 additional_kwargs['reasoning_content']）——
    采集阶段模型输出多是工具调用+思考、正文为空，把思考流出来才让漫长研究期「活着」。"""
    if not _is_ai_chunk(msg):
        return ""
    ak = getattr(msg, "additional_kwargs", None)
    if isinstance(ak, dict):
        r = ak.get("reasoning_content")
        if isinstance(r, str):
            return r
    return ""


async def _invoke_streaming(
    cid: str, agent, user_text: str, user_id: str,
    skill_files: dict | None = None, turn_messages: list[dict] | None = None,
    stream_msg_id: str | None = None, stream_state: dict | None = None,
):
    """流式跑 agent（Phase 56）：astream 逐块把「当前正在写的 AI 消息」增量落到 streaming 占位，
    用户边看边等。按 message id 跟踪当前消息（新消息即重置），同时流式**思考链**——采集阶段
    正文为空、全是工具调用+思考，把思考流出来才让漫长研究期不再是空气泡。最终报告是最后一条
    AI 文本消息，自然停在它上。返回最终 state 供 `_extract_answer` 取干净终稿；末条消息的
    思考写入 stream_state['reasoning'] 供定稿保留。"""
    import time as _t

    from app.agent.orchestrator import _update_streaming_message
    from app.agent.skills_loader import load_skill_files
    from app.observability import langchain_handler

    if skill_files is None:
        skill_files = load_skill_files(user_id=user_id)
    config: dict = {"recursion_limit": settings.deep_research_recursion}
    handler = langchain_handler()
    if handler is not None:
        config["callbacks"] = [handler]
    inputs = {
        "messages": turn_messages or [{"role": "user", "content": user_text}],
        "files": skill_files,
    }
    hb = asyncio.ensure_future(_heartbeat_loop(cid))
    last_state: dict = {}
    cur_id = None
    buf: list[str] = []
    rbuf: list[str] = []
    last_flush = _t.monotonic()
    try:
        async for mode, chunk in agent.astream(inputs, config=config, stream_mode=["messages", "values"]):
            if is_cancelled(cid):
                raise TurnCancelled()
            if mode == "values":
                if isinstance(chunk, dict):
                    last_state = chunk
                continue
            # mode == "messages": chunk = (message_chunk, metadata)
            try:
                msg, _meta = chunk
            except (TypeError, ValueError):
                continue
            text, reasoning = _chunk_text(msg), _chunk_reasoning(msg)
            if not text and not reasoning:
                continue
            mid = getattr(msg, "id", None)
            if mid != cur_id:  # 新消息开始 → 重置缓冲（只展示当前正在写的这条）
                cur_id, buf, rbuf = mid, [], []
            if text:
                buf.append(text)
            if reasoning:
                rbuf.append(reasoning)
            if stream_msg_id and _t.monotonic() - last_flush > 1.2:
                _update_streaming_message(stream_msg_id, "".join(buf), "".join(rbuf))
                last_flush = _t.monotonic()
    finally:
        hb.cancel()
    if stream_state is not None:
        stream_state["reasoning"] = "".join(rbuf)  # 末条（报告）的思考，定稿保留
    return last_state


def _extract_answer(result) -> str:
    """取终稿：在 AI 文本消息里择优，而不是无脑取最后一条。

    走查 P0-1（线上真实翻车）：模型写完长报告后又追加了一条「报告已生成。核心结论…」的
    收尾寒暄——按「最后一条」取，用户等 4 分钟拿到的是 200 字摘要，几千字的对比报告被丢弃。
    规则：默认取最后一条；但若前面存在明显更长（≥1.5 倍且 ≥1200 字）的 AI 文本消息，
    取其中最长的那条（真正的报告总是全轮最长的 AI 消息，收尾/过程性消息都短得多）。

    ⚠️ 只在**最后一条 human 消息之后**的 AI 消息里选：state 的 messages 带着注入的
    近几轮对话历史，全局取最长会把历史里的旧攻略当成本轮终稿（上线当天真实翻车：
    问长沙 vs 南昌，终稿被换成上一轮的武汉美食攻略）。
    """
    msgs = list((result or {}).get("messages") or [])
    last_human = -1
    for i, m in enumerate(msgs):
        if getattr(m, "type", "") == "human":
            last_human = i
    texts: list[str] = []
    for m in msgs[last_human + 1:]:
        content = getattr(m, "content", None)
        if getattr(m, "type", "") != "ai" or not content:
            continue
        if isinstance(content, list):  # 多段 content 块
            content = "".join(c.get("text", "") for c in content if isinstance(c, dict))
        if isinstance(content, str) and content.strip():
            texts.append(content.strip())
    if not texts:
        return ""
    last = texts[-1]
    longest = max(texts, key=len)
    if len(longest) >= max(1200, int(len(last) * 1.5)):
        return longest
    return last


_SKILL_PATH_PREFIXES = ("/main/", "/researcher/", "/user/")


def _extract_skills_used(result) -> list[str]:
    """扫一遍本轮消息里的 `read_file` 工具调用，挑出命中技能虚拟路径的，取技能名去重。

    详细调用链本来就在 Langfuse 里（Phase 24 全图追踪）；这里只是把"这轮到底读了哪些
    技能"这个产品可见的轻量汇总提炼出来，写进 assistant 消息的 meta（Phase 27）。
    """
    msgs = (result or {}).get("messages") or []
    seen: list[str] = []
    for m in msgs:
        for tc in getattr(m, "tool_calls", None) or []:
            name = tc.get("name") if isinstance(tc, dict) else getattr(tc, "name", None)
            if name != "read_file":
                continue
            args = tc.get("args") if isinstance(tc, dict) else getattr(tc, "args", None)
            path = (args or {}).get("file_path") or ""
            for prefix in _SKILL_PATH_PREFIXES:
                if not path.startswith(prefix):
                    continue
                skill_name = path[len(prefix):].split("/", 1)[0]
                if skill_name and skill_name not in seen:
                    seen.append(skill_name)
                break
    return seen


def _dedupe(sources: list[dict]) -> list[dict]:
    seen, out = set(), []
    for s in sources:
        if s["url"] not in seen:
            seen.add(s["url"])
            out.append(s)
    return out[:10]


# ---------- 三路路由（Phase 22：v4-flash 单次分类，~1s） ----------
# 原「研究关键词门」已被统一分类取代：既然 direct/guide 也要判，一次 flash 全判掉。

ROUTE_SYSTEM = (
    "给旅行助手的用户消息选择处理通道，输出 kind：\n"
    "- direct：不需要查任何实时网页就能答好的：旅行常识/建议/注意事项/穿搭交通经验、"
    "对上文内容的追问或解释、闲聊。例：「鼓浪屿要提前订票吗」「带娃去三亚要注意什么」"
    "「你刚说的八市是什么」\n"
    "- guide：需要检索实时信息并产出结构化内容：规划或修改行程、生成攻略、查酒店、"
    "查价格/房态/班次。\n"
    "- research：开放式研究：多目的地对比、预算成本测算、签证政策查询、在多个选项间"
    "帮用户做决策。\n"
    "拿不准时一律选 guide。"
)


def resolve_route(user_text: str, llm, deep_reasoning: bool = False) -> tuple[str, bool]:
    """快/慢思考语义（Phase 44 重排）。返回 (route, suggest_deep)。

    - 开关**关**：direct 仍快速直答；guide（明确规划/攻略/酒店）直接走联网攻略流水线；
      只有 research（开放式研究/多方案决策）降级为快速回答并提示开启深度推理。
    - 开关**开** = 慢思考：三路分类——direct（闲聊/追问仍秒回，开着开关问「谢谢」
      不该跑重流水线）/ guide（联网攻略流水线：浏览器、图片、反思、思考链）/
      research（开放式深研，服务器未启用退 guide）。
    """
    kind = decide_route(user_text, llm)
    if deep_reasoning:
        if kind == "research":
            return ("research" if settings.deep_research_enabled else "guide"), False
        if kind == "direct":
            return "direct", False
        return "guide", False
    # 普通规划是产品核心能力，不能因为开关关闭就降成容易截断、无来源的 direct。
    if kind == "guide":
        return "guide", False
    # research 在快思考下仍给快速概览 + 一键深度研究；direct 被禁时退 guide。
    if not settings.direct_answer_enabled:
        return "guide", kind == "research"
    return "direct", kind == "research"


def decide_route(user_text: str, llm) -> str:
    """纯三分类（Phase 44：不做开关门控，门控上移 resolve_route）。
    失败/未知/空一律 guide（重流水线兜底，宁慢勿错）。"""
    text = (user_text or "").strip()
    if not text:
        return "guide"
    # 明确的行程规划由确定性规则兜底，避免快分类模型偶发把长规划需求判成 direct。
    from app.agent.context_security import is_explicit_itinerary_request

    if is_explicit_itinerary_request(text):
        return "guide"
    try:
        from pydantic import BaseModel

        class _Route(BaseModel):
            kind: str  # direct / guide / research

        r = llm.classify(text[:500], _Route, system=ROUTE_SYSTEM)
        kind = (r.kind or "").strip().lower()
    except Exception:  # noqa: BLE001
        logger.warning("route classify failed, fallback guide", exc_info=True)
        return "guide"
    return kind if kind in ("direct", "guide", "research") else "guide"
