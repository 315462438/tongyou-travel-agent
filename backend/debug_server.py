"""PyCharm 断点调试入口：在 IDE 里右键此文件 → Debug 'debug_server'。

前置（终端跑一次即可，幂等）：
    backend/scripts/db_tunnel.sh        # 必须：数据库隧道
    backend/scripts/start_chrome.sh    # 可选：只有要调试浏览器采集链路才需要

注意：
- 这里故意不开 --reload：reload 模式会 fork 出 worker 子进程，断点只挂在父进程上不生效。
  调试时改了代码就手动重启（Debug 工具栏的 ⟳）。
- 断点可以打在任何位置，包括后台线程里的 run_conversation_turn / 图节点 / 工具层。
"""
import uvicorn

if __name__ == "__main__":
    uvicorn.run("app.main:app", host="127.0.0.1", port=8000, reload=False)
