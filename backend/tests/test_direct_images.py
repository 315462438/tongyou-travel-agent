"""直答配实景图（2026-11-10）。

线上：联网搜索推荐了几家汤泉后用户问「有没有图片」，回答「我是纯文字助手，没法发图」。
直答链路从没接过图——攻略链路的高德实景图 + /api/img + [[img:]] 占位符它一样没用上。
"""
import pytest

import app.agent.orchestrator as O
from app.tools import amap


class _FakeLLM:
    def __init__(self, answer, places=("水相汤泉", "滨湖温泉"), city="合肥"):
        self.answer, self.places, self.city = answer, list(places), city
        self.messages = None
        self.classify_prompts: list[str] = []

    def classify(self, prompt, schema, **kw):
        self.classify_prompts.append(prompt)
        if schema is O._PhotoPlaces:
            return schema(city=self.city, places=self.places)
        return schema(queries=["合肥 汤泉"])

    def stream_generate_with_reasoning(self, messages, **kw):
        self.messages = messages
        yield "content", self.answer
        yield "finish", "stop"


@pytest.fixture
def direct(monkeypatch):
    finals: list[tuple[str, dict]] = []
    progress: list[str] = []
    calls: list[tuple[str, str, int]] = []
    photos = {"水相汤泉": ["https://store.is.autonavi.com/a.jpg", "https://store.is.autonavi.com/b.jpg"]}
    history = [{"role": "assistant", "content": "推荐 **水相汤泉** 和 **滨湖温泉**。"}]
    monkeypatch.setattr(O, "gather_context", lambda *a, **k: {"block": "", "used": []})
    monkeypatch.setattr(O, "_assemble_history", lambda *a, **k: (history, ""))
    monkeypatch.setattr(O, "_recent_plan_prefix", lambda *a, **k: "")
    monkeypatch.setattr(O, "_add_streaming_message", lambda cid: "m1")
    monkeypatch.setattr(O, "_update_streaming_message", lambda *a, **k: None)
    monkeypatch.setattr(O, "_finalize_streaming_message",
                        lambda mid, content, reasoning, meta: finals.append((content, meta)))
    monkeypatch.setattr(O, "extract_and_save", lambda *a, **k: [])
    monkeypatch.setattr(O, "update_history_summary", lambda *a, **k: None)
    monkeypatch.setattr(O, "_progress", lambda cid, text, meta=None: progress.append(text))
    monkeypatch.setattr(amap, "enabled", lambda: True)

    async def _photos(client, keyword, city="", limit=1):
        calls.append((keyword, city, limit))
        urls = photos.get(keyword)
        if keyword == "汤连得温泉馆":   # 高德有这家店但没图：仍能出地点卡
            return {"name": keyword, "address": "蜀山区", "location": "117.2,31.8", "photos": []}
        return ({"name": keyword + "(滨湖店)", "address": "包河区某路1号", "location": "117.29,31.72",
                 "photos": urls[:limit]} if urls else None)

    monkeypatch.setattr(amap, "search_poi_photos", _photos)

    def run(llm, text):
        monkeypatch.setattr(O, "get_llm", lambda: llm)
        O.run_direct_answer("c1", text, "u1")
        run.meta = finals[-1][1]
        return finals[-1][0], llm.messages[-1]["content"], calls, progress

    run.photos = photos
    return run


def test_asking_for_pictures_embeds_amap_photos(direct):
    llm = _FakeLLM("水相汤泉的环境：\n[[img:水相汤泉]]\n[[img:水相汤泉 图2]]\n滨湖温泉暂时没找到图。")
    content, prompt, calls, progress = direct(llm, "有没有图片")
    assert "![水相汤泉](/travel/api/img?u=https%3A%2F%2Fstore.is.autonavi.com%2Fa.jpg)" in content
    assert "b.jpg" in content and "[[img" not in content
    assert ("水相汤泉", "合肥", 3) in calls          # 要图：每处最多 3 张、限定城市
    assert "[[img:名称]]" in prompt and "水相汤泉 图2" in prompt
    assert "纯文字助手" in prompt                    # 明确禁止再说这句
    assert "滨湖温泉" in llm.classify_prompts[-1]    # 上一轮回答进了挑地点的上下文
    assert any("正在找实景图" in p for p in progress)


def test_model_forgets_placeholder_still_gets_photo(direct):
    content, *_ = direct(_FakeLLM("### 水相汤泉\n环境不错。"), "有没有照片")
    assert "a.jpg" in content


def test_plain_question_does_not_look_up_images(direct):
    llm = _FakeLLM("带身份证就行。")
    content, prompt, calls, _ = direct(llm, "泡汤要带什么")
    assert calls == [] and llm.classify_prompts == [] and "img" not in prompt


def test_no_photo_found_tells_model_to_say_so(direct):
    direct.photos.clear()
    content, prompt, calls, _ = direct(_FakeLLM("暂时没找到图。"), "有没有图片")
    assert calls and "没有找到可用的实景图" in prompt and "[[img:名称]]" not in prompt
    assert "![" not in content


def test_lookup_failure_never_breaks_answer(direct, monkeypatch):
    async def _boom(*a, **k):
        raise RuntimeError("amap down")

    monkeypatch.setattr(amap, "search_poi_photos", _boom)
    content, *_ = direct(_FakeLLM("照常回答。"), "有没有图片")
    assert content == "照常回答。"


def test_disabled_flag_restores_old_behaviour(direct, monkeypatch):
    monkeypatch.setattr(O.settings, "direct_images_enabled", False)
    llm = _FakeLLM("回答。")
    _, prompt, calls, _ = direct(llm, "有没有图片")
    assert calls == [] and llm.classify_prompts == []


def test_web_search_turn_gets_one_photo_per_place(direct, monkeypatch):
    from app.tools import web_search_api

    async def _search(q, top_k=None):
        return [{"title": "水相汤泉体验", "url": "https://example.com/a", "content": "水相汤泉在经开区。" * 10}]

    monkeypatch.setattr(web_search_api, "enabled", lambda: True)
    monkeypatch.setattr(web_search_api, "search", _search)
    O._WEB_SEARCH_CIDS.add("c1")
    try:
        llm = _FakeLLM("推荐 **水相汤泉** [1]")
        content, prompt, calls, _ = direct(llm, "推荐个泡汤的地方")
    finally:
        O._WEB_SEARCH_CIDS.discard("c1")
    assert ("水相汤泉", "合肥", 1) in calls and "a.jpg" in content and "b.jpg" not in content
    assert "水相汤泉在经开区" in llm.classify_prompts[-1]  # 搜索结果进了挑地点的上下文


def test_place_names_cannot_break_markdown(direct):
    llm = _FakeLLM("x", places=["水相汤泉](http://evil/?d=1)![", "a"])
    _, prompt, calls, _ = direct(llm, "有没有图片")
    assert all("]" not in k and "(" not in k for k, _, _ in calls)


@pytest.mark.parametrize("keyword,poi,ok", [
    ("水相汤泉", "水相汤泉生活馆(滨湖店)", True),
    ("合肥水相汤泉", "水相汤泉生活馆", True),
    ("汤连得温泉馆（合肥店）", "汤连得温泉馆", True),
    ("金孔雀洗浴中心", "大浪淘沙洗浴中心", False),   # 只有品类词相同：不是同一家
    ("云水谣汤泉", "碧水云天汤泉", False),
    ("天沐温泉", "天沐养生SPA·肩颈调理(高新区大铺头店)", False),  # 线上实测配错过
    ("水相汤泉馆", "水相汤泉生活馆", True),
    ("", "水相汤泉", False),
])
def test_poi_name_must_match(keyword, poi, ok):
    assert amap._poi_name_matches(keyword, poi, "合肥") is ok


def test_search_poi_photos_skips_mismatched_and_photoless(monkeypatch):
    import asyncio

    seen = {}

    async def _call(client, path, **params):
        seen.update(params)
        return {"pois": [
            {"name": "大浪淘沙洗浴中心", "photos": [{"url": "https://x.autonavi.com/wrong.jpg"}]},
            {"name": "水相汤泉(老店)", "photos": []},
            {"name": "水相汤泉生活馆", "photos": [{"url": "https://x.autonavi.com/1.jpg"},
                                            {"url": "https://x.autonavi.com/1.jpg"},
                                            {"url": "https://x.autonavi.com/2.jpg"}]},
        ]}

    monkeypatch.setattr(amap, "enabled", lambda: True)
    monkeypatch.setattr(amap, "_call", _call)
    r = asyncio.run(amap.search_poi_photos(None, "水相汤泉", city="合肥", limit=3))
    assert r["name"] == "水相汤泉生活馆"
    assert r["photos"] == ["https://x.autonavi.com/1.jpg", "https://x.autonavi.com/2.jpg"]
    assert seen["citylimit"] == "true" and seen["city"] == "合肥"


# ---------- 追问按钮 + 地点卡 ----------

def test_suggestions_leave_content_and_enter_meta(direct):
    llm = _FakeLLM("你在哪个区？\n\n[[追问:我在滨湖区|想带吃饭的|看看图片]]")
    content, prompt, *_ = direct(llm, "泡汤要带什么")
    assert content == "你在哪个区？"
    assert direct.meta["suggestions"] == ["我在滨湖区", "想带吃饭的", "看看图片"]
    assert "[[追问:" in prompt


def test_no_suggestion_line_means_no_buttons(direct):
    content, *_ = direct(_FakeLLM("不客气。"), "谢谢")
    assert content == "不客气。" and "suggestions" not in direct.meta


@pytest.mark.parametrize("raw,body,items", [
    ("正文\n[[追问：A店怎么去｜营业到几点]]", "正文", ["A店怎么去", "营业到几点"]),
    ("正文\n[[追问:只有一个", "正文", []),                      # 被截断：半截不留在正文里
    ("正文\n[[追问:**加粗**|" + "长" * 30 + "|好]]", "正文", ["加粗"]),  # 去标记、去超长、去单字
    ("正文 [[img:水相汤泉]]", "正文 [[img:水相汤泉]]", []),         # 不误伤配图占位符
])
def test_split_suggestions(raw, body, items):
    assert O._split_suggestions(raw) == (body, items)


@pytest.mark.parametrize("partial,shown", [
    ("正文\n[[追", "正文"), ("正文\n[[追问:我在", "正文"), ("正文\n[", "正文"),
    ("正文 [[img:水相", "正文 [[img:水相"), ("正文\n[[追问:a b|c d]]", "正文"),
])
def test_streaming_never_flashes_suggestion_line(partial, shown):
    assert O._hide_suggestion_tail(partial) == shown


def test_place_cards_only_for_places_the_answer_mentions(direct, monkeypatch):
    from app.tools import web_search_api

    async def _search(q, top_k=None):
        return [{"title": "t", "url": "https://example.com/a", "content": "水相汤泉、汤连得温泉馆、滨湖温泉。" * 8}]

    monkeypatch.setattr(web_search_api, "enabled", lambda: True)
    monkeypatch.setattr(web_search_api, "search", _search)
    O._WEB_SEARCH_CIDS.add("c1")
    try:
        llm = _FakeLLM("推荐 **水相汤泉** 和 **汤连得温泉馆**。", places=["水相汤泉", "汤连得温泉馆", "滨湖温泉"])
        direct(llm, "推荐个泡汤的地方")
    finally:
        O._WEB_SEARCH_CIDS.discard("c1")
    cards = direct.meta["places"]
    assert [c["name"] for c in cards] == ["水相汤泉(滨湖店)", "汤连得温泉馆"]   # 滨湖温泉查不到 → 没卡
    assert cards[0]["photo"].startswith("/travel/api/img?u=") and cards[1]["photo"] == ""
    assert cards[0]["nav"]["amap"].startswith("https://uri.amap.com/navigation") and cards[0]["address"]


def test_no_place_cards_without_lookup(direct):
    direct(_FakeLLM("带身份证就行。"), "泡汤要带什么")
    assert "places" not in direct.meta


# ---------- 定位回答「附近」 ----------

def test_location_feeds_position_and_nearby_places(direct, monkeypatch):
    async def _locate(loc):
        assert loc == "117.28,31.86"
        return {"location": "117.2857,31.8585", "city": "合肥市", "district": "包河区", "address": "安徽省合肥市包河区某路"}

    async def _around(location, keyword, radius=5000, limit=8):
        assert location == "117.2857,31.8585" and keyword == "洗浴"
        return [{"name": "近处汤泉", "address": "某路 8 号", "location": "117.29,31.86", "distance": 650,
                 "rating": "4.6", "photo": "https://store.is.autonavi.com/n.jpg"},
                {"name": "远处汤泉", "address": "", "location": "117.33,31.9", "distance": 4200, "rating": "", "photo": ""}]

    monkeypatch.setattr(amap, "locate_device", _locate)
    monkeypatch.setattr(amap, "search_around", _around)

    class _LLM(_FakeLLM):
        def classify(self, prompt, schema, **kw):
            if schema is O._NearbyKeyword:
                return schema(keyword="洗浴")
            return super().classify(prompt, schema, **kw)

    O._TURN_LOCATION["c1"] = "117.28,31.86"
    try:
        content, prompt, *_ = direct(_LLM("最近的是 **近处汤泉**，650 米。"), "附近有什么洗浴")
    finally:
        O._TURN_LOCATION.pop("c1", None)
    assert "包河区某路" in prompt and "不要再反问" in prompt and "不代表常驻地" in prompt
    assert "近处汤泉｜650 米" in prompt and "远处汤泉｜4.2 公里" in prompt
    assert [c["name"] for c in direct.meta["places"]] == ["近处汤泉"]      # 只给回答提到的出卡


def test_no_location_means_no_lookup(direct, monkeypatch):
    async def _boom(*a, **k):
        raise AssertionError("不该查定位")

    monkeypatch.setattr(amap, "locate_device", _boom)
    _, prompt, *_ = direct(_FakeLLM("好的"), "附近有什么洗浴")
    assert "此刻所在位置" not in prompt


def test_location_failure_falls_back_to_plain_answer(direct, monkeypatch):
    async def _boom(*a, **k):
        raise RuntimeError("amap down")

    monkeypatch.setattr(amap, "locate_device", _boom)
    O._TURN_LOCATION["c1"] = "117.28,31.86"
    try:
        content, prompt, *_ = direct(_FakeLLM("照常回答。"), "附近有什么洗浴")
    finally:
        O._TURN_LOCATION.pop("c1", None)
    assert content == "照常回答。" and "此刻所在位置" not in prompt
