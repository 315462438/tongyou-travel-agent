"""来源全文落库与按需重取（Phase 103）单测。sqlite 内存库，全离线。

改造前：`_search_and_collect_queries` 只留 `_excerpt(page.text)` 的 1500 字，全文丢弃；
而多轮复用分支复用的就是这 1500 字——用户追问「第 3 家酒店的取消政策」时信息已经没了。
深度研究链路早有此能力（`_stash_source` + `read_source`），这里给 guide 链路补上。
"""

from contextlib import contextmanager

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.agent.source_pages import (
    focus_excerpt,
    keywords_of,
    load_texts,
    refresh_reused_summaries,
    save_page,
)
from app.config import settings
from app.db.models import Base, TravelSourcePage

HOTEL_PAGE = (
    "杭州西湖国宾馆\n" + "位置优越环境优美。" * 80
    + "\n取消政策：入住前 3 天可免费取消，之后收取首晚房费。\n"
    + "早餐时间 07:00-10:00。\n" + "周边景点丰富。" * 200
)


@pytest.fixture()
def db(monkeypatch):
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    session = Session(engine)

    @contextmanager
    def fake_session():
        yield session

    monkeypatch.setattr("app.agent.source_pages.get_session", fake_session)
    yield session
    session.close()


# --------------------------------------------------------------------------- 纯函数

def test_keywords_split_chinese():
    """中文没有空格，直接按连续汉字块取会把整句抓成一个 token
    （「第3家酒店的取消政策是什么」→ 一个词，str.find 永远命中不了）。"""
    kws = keywords_of("第3家酒店的取消政策是什么，帮我详细介绍一下")
    assert "取消政策" in kws
    assert not any(len(k) > 12 for k in kws)  # 没有整句 token


def test_keywords_keep_place_name_chars():
    """虚词表刻意不含 中/上/下/里/出 —— 它们在真实地名里很常见。"""
    assert "湖里区" in keywords_of("把行程改到湖里区")
    assert "中山路" in keywords_of("加上中山路")


def test_keywords_drop_stopwords_and_dedupe():
    kws = keywords_of("推荐推荐攻略攻略行程")
    assert kws == [] or all(k not in {"推荐", "攻略", "行程"} for k in kws)


def test_focus_excerpt_hits_the_right_window():
    got = focus_excerpt(HOTEL_PAGE, ["取消政策"], limit=600)
    assert "免费取消" in got
    assert len(got) <= 600


def test_focus_excerpt_returns_empty_on_miss():
    """一个关键词都没命中时返回空串，**由调用方决定退回原 summary**。

    这里若悄悄给个头部截断，调用方就无从区分「找到了」和「没找到」，
    进度提示会谎报「重新定位了 N 处」。
    """
    assert focus_excerpt(HOTEL_PAGE, ["米其林三星"]) == ""
    assert focus_excerpt(HOTEL_PAGE, []) == ""
    assert focus_excerpt("", ["取消政策"]) == ""


def test_focus_excerpt_is_idempotent():
    """纯函数：同样的输入永远同样的输出（Phase 96 的教训——裁剪必须幂等）。"""
    a = focus_excerpt(HOTEL_PAGE, ["取消政策", "早餐"], limit=800)
    b = focus_excerpt(HOTEL_PAGE, ["取消政策", "早餐"], limit=800)
    assert a == b


def test_focus_excerpt_merges_overlapping_windows():
    """两个关键词挨得很近时窗口相交，不能把同一段正文拼两遍。"""
    text = "前置内容。" * 30 + "早餐时间 07:00，取消政策 3 天。" + "后续内容。" * 30
    got = focus_excerpt(text, ["早餐时间", "取消政策"], limit=4000)
    assert got.count("取消政策 3 天") == 1


def test_focus_excerpt_marks_discontinuity():
    """相隔很远的两段之间要有断点标记，否则模型会当成连续正文读。"""
    text = "开头 取消政策在这里。" + "填充。" * 500 + "结尾 早餐时间在这里。"
    got = focus_excerpt(text, ["取消政策", "早餐时间"], limit=4000)
    assert "…" in got


# --------------------------------------------------------------------------- 落库

def test_save_and_load(db):
    pid = save_page("c1", "https://x.com/a", "西湖国宾馆", HOTEL_PAGE)
    assert pid
    assert load_texts([pid])[pid] == HOTEL_PAGE


def test_save_is_upsert_per_conversation_url(db):
    """同一会话重复抓同一页覆盖，不堆历史版本。"""
    p1 = save_page("c1", "https://x.com/a", "t", "第一版")
    p2 = save_page("c1", "https://x.com/a", "t", "第二版")
    assert p1 == p2
    assert load_texts([p1])[p1] == "第二版"
    assert db.execute(select(TravelSourcePage)).scalars().all().__len__() == 1


def test_save_truncates_to_cap(db, monkeypatch):
    monkeypatch.setattr(settings, "source_full_text_max_chars", 100)
    pid = save_page("c1", "https://x.com/a", "t", "字" * 5000)
    assert len(load_texts([pid])[pid]) == 100


def test_save_skips_empty(db):
    assert save_page("c1", "https://x.com/a", "t", "   ") is None
    assert save_page("", "https://x.com/a", "t", "正文") is None


def test_prune_keeps_recent_only(db, monkeypatch):
    monkeypatch.setattr(settings, "source_page_keep", 3)
    for i in range(6):
        save_page("c1", f"https://x.com/{i}", "t", f"正文{i}")
    rows = db.execute(
        select(TravelSourcePage).where(TravelSourcePage.conversation_id == "c1")
    ).scalars().all()
    assert len(rows) <= 3


def test_prune_is_per_conversation(db, monkeypatch):
    monkeypatch.setattr(settings, "source_page_keep", 2)
    for i in range(4):
        save_page("c1", f"https://x.com/{i}", "t", "a")
    save_page("c2", "https://y.com/1", "t", "b")
    assert db.execute(
        select(TravelSourcePage).where(TravelSourcePage.conversation_id == "c2")
    ).scalars().all().__len__() == 1


def test_save_failure_returns_none_not_raises(db, monkeypatch):
    """全文是增强，存不进去也不能拖垮采集。"""
    @contextmanager
    def boom():
        raise RuntimeError("db down")
        yield

    monkeypatch.setattr("app.agent.source_pages.get_session", boom)
    assert save_page("c1", "https://x.com/a", "t", "正文") is None


# --------------------------------------------------------------------------- 复用重取

def test_refresh_focuses_on_current_question(db):
    pid = save_page("c1", "https://x.com/a", "西湖国宾馆", HOTEL_PAGE)
    sources = [{"title": "西湖国宾馆", "url": "https://x.com/a",
                "summary": "位置优越环境优美。" * 10, "page_id": pid}]
    out, hits = refresh_reused_summaries(sources, "第3家酒店的取消政策是什么")
    assert hits == 1
    assert "免费取消" in out[0]["summary"]
    assert out[0]["url"] == sources[0]["url"]  # 其余字段原样


def test_refresh_keeps_old_summary_on_miss(db):
    """关键词没命中 → 退回旧 summary。降级方向永远是「和改造前一样」。"""
    pid = save_page("c1", "https://x.com/a", "t", HOTEL_PAGE)
    old = "旧的摘录内容"
    out, hits = refresh_reused_summaries(
        [{"url": "https://x.com/a", "summary": old, "page_id": pid}], "米其林三星餐厅"
    )
    assert hits == 0
    assert out[0]["summary"] == old


def test_refresh_tolerates_legacy_sources_without_page_id(db):
    """存量消息里的来源没有 page_id，不能炸。"""
    out, hits = refresh_reused_summaries(
        [{"url": "https://x.com/a", "summary": "旧摘录"}], "取消政策"
    )
    assert hits == 0
    assert out[0]["summary"] == "旧摘录"


def test_refresh_handles_empty_and_no_keywords(db):
    assert refresh_reused_summaries([], "取消政策") == ([], 0)
    src = [{"url": "u", "summary": "s", "page_id": "p"}]
    assert refresh_reused_summaries(src, "。。。")[1] == 0


def test_refresh_partial_hit_reports_accurate_count(db):
    """进度气泡会播「重新定位了 N 处」，N 必须是真命中数，不能虚报。"""
    p1 = save_page("c1", "https://x.com/a", "t", HOTEL_PAGE)
    p2 = save_page("c1", "https://x.com/b", "t", "完全无关的内容。" * 50)
    out, hits = refresh_reused_summaries(
        [{"url": "https://x.com/a", "summary": "s1", "page_id": p1},
         {"url": "https://x.com/b", "summary": "s2", "page_id": p2}],
        "取消政策",
    )
    assert hits == 1
    assert out[1]["summary"] == "s2"


# ------------------------------------------------- 泛词筛选（线上实测后补的回归防线）

# 线上真实形态：a11y 快照带 MCP 响应头，标题里就含查询词，之后是一长串导航菜单项。
REAL_HOTEL_PAGE = (
    "# take_snapshot response\n## Page content\n"
    "杭州中山西子湖酒店 杭州 早餐-旅游知识问答【携程攻略】\n"
    + "".join(f"{x} 按回车键打开菜单\n" for x in
             ["酒店", "机票", "火车票", "旅游", "门票·活动", "汽车·船票", "用车", "攻略·景点"])
    + "".join(f"#杭州中山西子湖酒店#早餐是五星标准嘛？{i}\n" for i in range(10))
)


def test_generic_keyword_does_not_hijack_window():
    """线上实测的**质量回归**：「酒店」在一个酒店页里出现 18 次、最早那次在标题里，
    用它定位出来的窗口全是标题和导航菜单——比原来的 `_excerpt` 摘录还差，而
    `refresh_reused_summaries` 还会当成「命中」把它替换进去。

    这是 Phase 96「按位置下刀 = 窗口里全是导航」的另一个实例。
    """
    got = focus_excerpt(REAL_HOTEL_PAGE, ["酒店"], limit=600)
    assert got == ""  # 泛词不参与定位


def test_specific_keyword_still_works_on_same_page():
    """筛掉泛词不能把特异词一起筛掉。"""
    page = REAL_HOTEL_PAGE + "\n取消政策：入住前 3 天可免费取消。\n"
    got = focus_excerpt(page, ["取消政策"], limit=600)
    assert "免费取消" in got


def test_rare_word_in_short_page_is_not_generic():
    """出现两三次的词，无论页面多短都算信号（绝对次数下限保护）。"""
    page = "短页面。取消政策：可退。中间内容。取消政策适用全部房型。"
    assert focus_excerpt(page, ["取消政策"], limit=400) != ""


def test_density_not_absolute_count():
    """用密度而非绝对次数：3 万字百科里出现 50 次的「西湖」仍有定位价值，
    1670 字酒店页里出现 18 次的「酒店」没有。"""
    long_page = ("杭州风光。" * 200 + "西湖景色宜人。") * 50   # 西湖 50 次 / 约 5 万字
    assert focus_excerpt(long_page, ["西湖"], limit=400) != ""
    short_page = "酒店简介。" * 5 + "本酒店" * 15               # 酒店 20 次 / 约 70 字
    assert focus_excerpt(short_page, ["酒店"], limit=400) == ""


def test_snapshot_header_is_stripped_before_storing(db):
    """`# take_snapshot response` / `## Page content` 每页都有、纯噪声，
    还把正文往后推 40 字——泛词命中窗口第一眼看到的就是它。"""
    pid = save_page("c1", "https://x.com/a", "t", REAL_HOTEL_PAGE)
    stored = load_texts([pid])[pid]
    assert not stored.startswith("#")
    assert stored.startswith("杭州中山西子湖酒店")


def test_strip_header_leaves_body_markdown_alone():
    """只剥开头连续的标题行，正文中间的 markdown 标题不能动。"""
    from app.agent.source_pages import _strip_snapshot_header

    assert _strip_snapshot_header("正文\n## 中间的小标题\n更多") == "正文\n## 中间的小标题\n更多"


def test_anchors_never_produce_two_char_tokens():
    """2 字中文锚点几乎必然是泛词，是上面那个回归的源头之一。"""
    from app.agent.source_pages import _anchors

    for frag in ["行程改到湖里区", "早餐几点开始", "取消政策说明书"]:
        assert all(len(a) >= 3 for a in _anchors(frag))
