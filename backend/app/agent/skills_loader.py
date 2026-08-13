"""深度研究 agent 的技能库加载器（Phase 26 内置技能 + Phase 27 用户上传技能）。

技能正文以 .md 文件形式存在仓库里（`backend/app/agent/skills/`，方便版本管理/人工维护），
但 deep_research 的 agent 默认用的是 `StateBackend`（ephemeral，per-invoke，不碰真实磁盘——
选型原因见 docs/pitfalls/ 里 FilesystemBackend virtual_mode 默认值的踩坑记录）。所以这里只
负责「读盘一次/查一次库 → 转成 StateBackend 认的 FileData → 每轮 agent.ainvoke 时当 files
种子传入」。

虚拟路径约定（不带外层 `/skills/` 包裹，直接是顶层前缀——为了沙箱场景下
`CompositeBackend(default=沙箱, routes={"/main/": state, ...})` 能用同一套前缀，见
docs/task_plans/task_plan-phase27-用户技能上传与cube沙箱执行.md）：
- 磁盘 `skills/main/xxx/SKILL.md` → `/main/xxx/SKILL.md`（内置，主 agent）
- 磁盘 `skills/researcher/xxx/SKILL.md` → `/researcher/xxx/SKILL.md`（内置，api-researcher）
- 数据库里某用户名为 `xxx` 的技能 → `/user/xxx/{相对路径}`（用户私有，只给主 agent；
  单文件粘贴上传时只有 `/user/xxx/SKILL.md` 一项，zip 多文件上传时还会有
  `/user/xxx/references/...` 之类的附带文件，Phase 27b）
"""

from __future__ import annotations

import functools
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

SKILLS_ROOT = Path(__file__).resolve().parent / "skills"


@functools.lru_cache(maxsize=1)
def _scan_builtin_skill_files() -> tuple[tuple[str, str], ...]:
    """扫描磁盘内置技能目录一次，返回 (虚拟路径, 文件内容) 元组（供 lru_cache 命中）。"""
    if not SKILLS_ROOT.is_dir():
        logger.warning("技能目录不存在，跳过加载: %s", SKILLS_ROOT)
        return ()

    entries: list[tuple[str, str]] = []
    for path in sorted(SKILLS_ROOT.rglob("*")):
        if not path.is_file():
            continue
        try:
            content = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as e:
            logger.warning("跳过无法读取的技能文件 %s: %s", path, e)
            continue
        virtual_path = "/" + path.relative_to(SKILLS_ROOT).as_posix()
        entries.append((virtual_path, content))
    return tuple(entries)


def _load_user_skill_files(user_id: str) -> dict[str, str]:
    """查该用户自己上传的技能（Phase 26/27b：单文件 + zip 多文件），转成 {虚拟路径: 正文} dict。

    查询失败（DB 不可用等）只记 warning、返回空——用户技能是锦上添花，不应该让整轮
    深度研究失败。
    """
    import json

    try:
        from app.db.models import TravelUserSkill
        from app.db.session import get_session

        with get_session() as db:
            rows = db.query(TravelUserSkill).filter(TravelUserSkill.user_id == user_id).all()
            out: dict[str, str] = {}
            for row in rows:
                files = json.loads(row.files_json) if row.files_json else {"SKILL.md": row.content}
                for relpath, content in files.items():
                    out[f"/user/{row.name}/{relpath}"] = content
            return out
    except Exception:  # noqa: BLE001
        logger.warning("加载用户上传技能失败，本轮跳过", exc_info=True)
        return {}


def load_skill_files(user_id: str | None = None) -> dict:
    """返回 {虚拟路径: FileData}，用于 `agent.ainvoke({..., "files": load_skill_files()})`。

    内置技能读盘失败/目录不存在时返回空（技能库缺失不应该让整轮深度研究失败——agent
    退化为只靠 system prompt 里的资源纪律工作，只是少了 progressive-disclosure 的方法论
    细节）；传了 `user_id` 时额外并入该用户私有技能（仅本人可见，见 Phase 27）。
    """
    from deepagents.backends.utils import create_file_data

    files = {vpath: content for vpath, content in _scan_builtin_skill_files()}
    if user_id:
        files.update(_load_user_skill_files(user_id))
    return {vpath: create_file_data(content) for vpath, content in files.items()}
