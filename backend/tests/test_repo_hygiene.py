"""开源仓库卫生护栏（2026-08-25 开源前审计）。

这些问题的共同点是**不会让任何功能坏掉**：程序照跑、测试照过、日志干净，
唯一的后果是仓库里多了一点不该公开的东西——而仓库一旦公开，git 历史不可逆。
没有征兆的问题只能靠护栏。
"""

import pathlib
import re

REPO = pathlib.Path(__file__).resolve().parents[2]


def _tracked_run_files():
    return sorted((REPO / "backend" / "evals" / "runs").glob("*.json"))


def test_eval_baselines_carry_no_real_conversation_ids():
    """评估基线里不许留真实 conversation_id。

    它本身不是密钥，但 `PUBLIC_ROUTES` 里的 `chat_api.handoff_screenshot`
    **不鉴权、只靠「cid 不可猜」保护**（登记表里就是这么写的）。把 cid 公开出去
    等于对那些会话作废了这条假设。

    这些 id 对基线对照毫无用处——`evals/compare.py` 只读 id/metrics/verification/
    findings，从不碰 conversation_id。留着是纯粹的净损失。
    """
    leaked = []
    for path in _tracked_run_files():
        text = path.read_text(encoding="utf-8")
        for m in re.finditer(r'"conversation_id":\s*"([0-9a-f]{32})"', text):
            leaked.append(f"{path.relative_to(REPO)}: {m.group(1)[:8]}…")
    assert not leaked, (
        "评估基线里有真实 conversation_id，跑 `runner.py` 后提交前要抹掉：\n"
        + "\n".join(leaked)
    )


def test_no_default_admin_password_anywhere():
    """全仓不许出现能用的默认管理员口令。

    与 `test_migrate_lock.py::test_config_ships_no_usable_admin_password` 互补：
    那条钉配置项的默认值，这条防它以别的形式（脚本、文档、部署模板）回来。
    `auth_api._DEFAULT_ADMIN_PASSWORD` 是**存量部署的检测用常量**（判断历史上用
    admin123 引导过的站点该提示改密），不是可用默认值，故排除。
    """
    hits = []
    for path in REPO.rglob("*"):
        if not path.is_file() or path.suffix not in {".py", ".sh", ".env", ".example"}:
            continue
        rel = path.relative_to(REPO).as_posix()
        if rel.startswith(("backend/.venv/", "frontend/node_modules/", ".git/")):
            continue
        if rel in {"backend/app/api/auth_api.py", "backend/tests/test_auth.py",
                   "backend/tests/test_repo_hygiene.py"}:
            continue
        text = path.read_text(encoding="utf-8", errors="ignore")
        if re.search(r'admin_password\s*[:=]\s*["\'][^"\']+["\']', text):
            hits.append(rel)
        if re.search(r'^ADMIN_PASSWORD=.+$', text, re.M):
            hits.append(rel)
    assert not hits, f"这些文件给了可用的默认管理员口令：{hits}"


def test_no_production_host_in_tracked_files():
    """跟踪文件里不许出现生产服务器地址。

    IP 不是密钥，但仓库公开 = 给出明确目标，而那台机器上 Redis / ClickHouse /
    两个 uvicorn 全绑 0.0.0.0，防护完全押在云防火墙一层上。真值放
    `backend/.env` 的 DEPLOY_HOST（已 gitignore），脚本自己读。

    判据用 `ipaddress.is_global` 而不是「等于那一个 IP」——只钉具体值的话，
    换台机器就白钉了。私有 / 回环 / link-local / RFC 2544 基准段 / TEST-NET
    文档段都不是真实主机，自动放行；剩下少数当例子用的公共地址显式登记。
    """
    import ipaddress

    EXAMPLES = {"8.8.8.8", "1.1.1.1"}          # 文档/测试里当"公网 IP"的例子
    ip_re = re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b")
    hits = []
    for path in REPO.rglob("*"):
        if not path.is_file() or path.suffix not in {
                ".py", ".sh", ".md", ".ts", ".tsx", ".json", ".example"}:
            continue
        rel = path.relative_to(REPO).as_posix()
        if rel.startswith(("backend/.venv/", "frontend/node_modules/", ".git/",
                           "frontend/dist/", "backend/static/", "backend/evals/runs/")):
            continue
        for m in ip_re.finditer(path.read_text(encoding="utf-8", errors="ignore")):
            raw = m.group(0)
            if raw in EXAMPLES:
                continue
            try:
                ip = ipaddress.ip_address(raw)
            except ValueError:
                continue                        # 版本号之类，不是 IP
            if ip.is_global:
                hits.append(f"{rel}: {raw}")
    assert not hits, (
        "跟踪文件里出现了疑似真实服务器地址，请改成 $DEPLOY_HOST / <服务器IP>：\n"
        + "\n".join(sorted(set(hits))[:20])
    )
