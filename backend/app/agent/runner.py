"""Phase 1 任务执行器：打开 URL → 读取 → 分类 → 抽取 → 落库

Phase 1 用简单顺序调用；LangGraph 编排 + checkpoint 恢复在 Phase 2/3。
"""

import asyncio
import json
import logging
import traceback

from app.agent.extract import extract_hotel, extract_note, summarize_page
from app.db.models import TravelPage, TravelTask
from app.db.session import get_session
from app.tools.browser_tool import BrowserTool
from app.tools.mcp_client import ChromeMCP, MCPConnectionError

logger = logging.getLogger(__name__)


def _update_task(task_id: str, **fields) -> None:
    with get_session() as db:
        task = db.get(TravelTask, task_id)
        if task is None:
            return
        for k, v in fields.items():
            setattr(task, k, v)
        db.commit()


async def _run(task_id: str, url: str, user_id: str = "") -> None:
    _update_task(task_id, status="running", current_url=url)
    try:
        async with ChromeMCP(user_id=user_id) as chrome:
            browser = BrowserTool(chrome=chrome)
            page = await browser.open_page(url)

            if page.status == "need_user_handoff":
                _update_task(
                    task_id, status="need_user_handoff",
                    current_url=page.url, handoff_reason=page.reason,
                )
                return
            if page.status == "blocked":
                _update_task(task_id, status="failed", error=page.reason)
                return

            # 长页面滚动补读
            text = page.text
            if len(text) < 2000:
                text = await browser.scroll_and_read(times=2)

            # 按页面类型抽取
            if page.page_type == "hotel":
                data = extract_hotel(text)
                result = {"type": "hotel", "data": data.model_dump()}
            else:
                note = extract_note(text)
                result = {"type": "guide" if page.page_type == "guide" else "note",
                          "data": note.model_dump()}

            # 任何页面都生成一段中文总结，保证「有东西看」（尤其门户/导航页抽不出结构化字段时）
            try:
                result["summary"] = summarize_page(text)
            except Exception:  # noqa: BLE001 — 总结失败不影响主流程
                result["summary"] = ""

            with get_session() as db:
                db.add(TravelPage(
                    task_id=task_id, url=page.url, title=page.title,
                    page_type=page.page_type, raw_text=text[:20000],
                    structured_data=json.dumps(result, ensure_ascii=False),
                ))
                db.commit()

            _update_task(
                task_id, status="done", current_url=page.url,
                result=json.dumps(result, ensure_ascii=False),
            )
    except MCPConnectionError as e:
        _update_task(task_id, status="failed", error=str(e))
    except Exception as e:  # noqa: BLE001
        logger.error("task %s failed: %s", task_id, traceback.format_exc())
        _update_task(task_id, status="failed", error=f"{type(e).__name__}: {e}")


def run_task_sync(task_id: str, url: str, user_id: str = "") -> None:
    """FastAPI BackgroundTasks 入口（同步包装）。

    Phase 68：透传 user_id 走每用户浏览器池——此前裸 ChromeMCP() 会回落到全局调试
    Chrome（travel-chrome.service），是池外旁路，且与其它链路的隔离模型不一致。
    """
    asyncio.run(_run(task_id, url, user_id))
