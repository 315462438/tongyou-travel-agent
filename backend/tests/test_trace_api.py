"""调用链面板（Phase 25）单测：trace 匹配、观测化简、截断。全离线。"""

from app.api.trace_api import _clip, _dur_ms, _pick_trace, _simplify


def test_pick_trace_by_turn_id():
    traces = [
        {"id": "t2", "metadata": {"turn_id": "m2"}},
        {"id": "t1", "metadata": {"turn_id": "m1"}},
    ]
    assert _pick_trace(traces, "m1")["id"] == "t1"
    assert _pick_trace(traces, "不存在")["id"] == "t2"  # 匹配不到 → 最新一条
    assert _pick_trace(traces, "")["id"] == "t2"
    assert _pick_trace([], "m1") is None


def test_pick_trace_metadata_as_string():
    traces = [{"id": "t1", "metadata": '{"turn_id": "m1"}'}]
    assert _pick_trace(traces, "m1")["id"] == "t1"


def test_simplify_sorts_and_computes_duration():
    obs = [
        {"id": "b", "parentObservationId": "a", "type": "GENERATION", "name": "OpenAI-generation",
         "model": "deepseek-v4-pro", "startTime": "2026-07-13T12:00:05.000Z",
         "endTime": "2026-07-13T12:00:07.500Z", "input": [{"role": "user", "content": "hi"}],
         "output": "回答", "usage": {"input": 10, "output": 5, "total": 15}},
        {"id": "a", "parentObservationId": None, "type": "SPAN", "name": "conversation_turn",
         "startTime": "2026-07-13T12:00:00.000Z", "endTime": "2026-07-13T12:00:10.000Z"},
    ]
    nodes = _simplify(obs)
    assert [n["id"] for n in nodes] == ["a", "b"]  # 按开始时间排
    assert nodes[1]["durMs"] == 2500
    assert nodes[1]["parentId"] == "a"
    assert nodes[1]["usage"] == {"input": 10, "output": 5, "total": 15}
    assert "hi" in nodes[1]["input"]


def test_clip_truncates():
    assert _clip(None) == ""
    assert _clip("短") == "短"
    long = "字" * 9000
    out = _clip(long)
    assert len(out) < 9000 and out.endswith("…(截断)")
    assert "role" in _clip([{"role": "user"}])  # 非字符串 JSON 化


def test_dur_ms_handles_missing():
    assert _dur_ms({"startTime": None, "endTime": "x"}) is None
    assert _dur_ms({"startTime": "bad", "endTime": "bad"}) is None


class _FakeResp:
    def __init__(self, data):
        self._data = data

    def raise_for_status(self):
        pass

    def json(self):
        return {"data": self._data}


class _FakeClient:
    """按页返回预置数据的假 httpx client。"""

    def __init__(self, pages):
        self.pages = pages
        self.requests = []

    def get(self, url, params=None):
        self.requests.append(params)
        page = (params or {}).get("page", 1)
        return _FakeResp(self.pages.get(page, []))


def test_fetch_observations_pages_small():
    """小分页拉取（Phase 28.1）：一次 limit=100 会把小内存 langfuse-web 打挂，
    必须 25/页翻页，且最后一页不满即停。"""
    from app.api.trace_api import _OBS_PAGE_SIZE, _fetch_observations

    pages = {1: [{"id": i} for i in range(_OBS_PAGE_SIZE)], 2: [{"id": "last"}]}
    client = _FakeClient(pages)
    out = _fetch_observations(client, "http://lf", "t1")

    assert len(out) == _OBS_PAGE_SIZE + 1
    assert all(p["limit"] == _OBS_PAGE_SIZE for p in client.requests)
    assert [p["page"] for p in client.requests] == [1, 2]  # 第 2 页不满一页 → 停


def test_fetch_observations_caps_pages():
    from app.api.trace_api import _OBS_MAX_PAGES, _OBS_PAGE_SIZE, _fetch_observations

    pages = {p: [{"id": f"{p}-{i}"} for i in range(_OBS_PAGE_SIZE)] for p in range(1, 50)}
    client = _FakeClient(pages)
    out = _fetch_observations(client, "http://lf", "t1")

    assert len(out) == _OBS_MAX_PAGES * _OBS_PAGE_SIZE  # 超长轮次在上限处截断
    assert len(client.requests) == _OBS_MAX_PAGES


def test_clip_prettifies_before_truncating():
    """Phase 32.1：先美化再截断——顺序反了的话截断处 JSON 不合法，前端只能显示单行原文。"""
    big = [{"role": "system", "content": "x" * 9000}, {"role": "user", "content": "y"}]
    out = _clip(big)
    assert out.startswith("[\n")  # 已是缩进多行
    assert '"role": "system"' in out
    assert out.endswith("…(截断)")

    # 字符串型 payload 若本身是 JSON 文本，同样美化
    assert _clip('{"a":1}') == '{\n  "a": 1\n}'
    # 非 JSON 字符串原样（超长截断）
    assert _clip("纯文本") == "纯文本"

# ---------- 会话轨迹（Phase 90） ----------

from app.api.trace_api import _epoch_ms, _lane_of, _one_line  # noqa: E402


def test_lane_assignment_splits_model_from_tools():
    """三条泳道是密度条的全部信息量：一眼看出在等模型还是在跑工具。"""
    assert _lane_of({"type": "GENERATION", "name": "OpenAI-generation"}) == "model"
    assert _lane_of({"type": "SPAN", "name": "web_search"}) == "tools"
    assert _lane_of({"type": "SPAN", "name": "amap_city_brief"}) == "tools"
    assert _lane_of({"type": "SPAN", "name": "xhs_search"}) == "tools"
    assert _lane_of({"type": "EVENT", "name": "user_message"}) == "input"


def test_lane_falls_back_without_crashing():
    assert _lane_of({}) == "input"
    assert _lane_of({"type": "SPAN", "name": ""}) == "tools"


def test_one_line_flattens_and_caps():
    assert _one_line("a\n\n  b   c") == "a b c"
    long = "字" * 500
    out = _one_line(long)
    assert len(out) <= 161 and out.endswith("…")


def test_one_line_is_idempotent():
    """轨迹行会被反复渲染，截过的再截一次不能继续缩短。"""
    once = _one_line("字" * 500)
    assert _one_line(once) == once


def test_epoch_ms_parses_and_tolerates_garbage():
    assert _epoch_ms("2026-07-13T12:00:00.000Z") == 1783944000000
    assert _epoch_ms("") is None
    assert _epoch_ms("不是时间") is None
