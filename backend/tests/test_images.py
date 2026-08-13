"""攻略配图（Phase 12）单测：占位符替换、图片上下文组装、代理白名单。全部离线。"""

from app.agent.orchestrator import _build_image_context, _embed_images
from app.api.img_api import _allowed


# ---------- 占位符替换 ----------

IMG_MAP = {
    "黄山风景区": "/travel/api/img?u=A",
    "全季酒店(黄山店)": "/travel/api/img?u=B",
}


def test_embed_exact_match():
    out = _embed_images("看这里 [[img:黄山风景区]] 很美", IMG_MAP)
    assert "![黄山风景区](/travel/api/img?u=A)" in out
    assert "[[img:" not in out


def test_embed_fuzzy_match():
    # 模型写的名称与清单略有出入 → 包含匹配兜底
    out = _embed_images("[[img:全季酒店]]", IMG_MAP)
    assert "/travel/api/img?u=B" in out


def test_embed_unmatched_removed():
    out = _embed_images("正文 [[img:不存在的地方]] 结束", IMG_MAP)
    assert "[[img:" not in out and "不存在的地方](" not in out


def test_embed_streaming_strips_incomplete():
    # 流式中行尾未闭合的占位符残片不显示
    out = _embed_images("已生成 [[img:黄", IMG_MAP, streaming=True)
    assert "[[img:" not in out and out.rstrip().endswith("已生成")
    # 非流式保留残片（终稿时理应已闭合，残片罕见）
    assert "[[img:黄" in _embed_images("已生成 [[img:黄", IMG_MAP, streaming=False)


def test_embed_empty_map_clears_placeholders():
    assert "[[img:" not in _embed_images("a [[img:x]] b", {})


# ---------- 图片上下文组装 ----------

def test_build_image_context():
    sources = [
        {"site": "amap", "images": [{"name": "黄山风景区", "url": "http://store.is.autonavi.com/a"}]},
        {"site": "ctrip", "images": [{"name": "全季酒店", "url": "https://dimg04.c-ctrip.com/b.webp"}]},
        {"site": "xhs", "images": [{"name": "小红书灵感·黄山周末·1",
                                   "url": "https://sns-webpic-qc.xhscdn.com/c.webp"}]},
        {"site": "amap", "images": [{"name": "黄山风景区", "url": "http://x/dup"}]},  # 重名去重
    ]
    image_map, block = _build_image_context(sources)
    assert set(image_map) == {"黄山风景区", "全季酒店", "小红书灵感·黄山周末·1"}
    assert "store.is.autonavi.com" in image_map["黄山风景区"]  # URL 编码进代理
    assert "景点：黄山风景区" in block and "酒店：全季酒店" in block
    assert "小红书灵感图" in block and "至少分散使用 3 张" in block


def test_build_image_context_empty():
    assert _build_image_context([{"site": "amap"}]) == ({}, "")


# ---------- 代理白名单 ----------

def test_proxy_whitelist():
    assert _allowed("http://store.is.autonavi.com/showpic/x")
    assert _allowed("https://dimg04.c-ctrip.com/images/x.webp")
    assert _allowed("https://aos-comment.amap.com/x.jpg")
    assert _allowed("https://sns-webpic-qc.xhscdn.com/x.webp")
    assert not _allowed("http://evil.com/x")
    assert not _allowed("http://autonavi.com.evil.com/x")  # 后缀伪造
    assert not _allowed("http://169.254.169.254/latest/meta-data")  # SSRF 目标


# ---------- 终稿兜底插入（模型没插占位符时） ----------

def test_fallback_inserts_after_heading():
    """酒店场景：模型没插占位符，但 ### 标题匹配图名 → 兜底插入。"""
    guide = "### 浙江饭店\n很好的酒店。\n\n### 杭州君悦酒店\n豪华。"
    img_map = {"浙江饭店": "/travel/api/img?u=A", "杭州君悦酒店": "/travel/api/img?u=B"}
    out = _embed_images(guide, img_map)
    assert "![浙江饭店](/travel/api/img?u=A)" in out
    assert "![杭州君悦酒店](/travel/api/img?u=B)" in out
    # 图插在对应标题之后
    assert out.index("浙江饭店](") < out.index("### 杭州君悦酒店")


def test_fallback_not_duplicate_when_placeholder_used():
    """模型已用占位符插过的图，兜底不重复插。"""
    guide = "### 浙江饭店\n[[img:浙江饭店]]\n正文"
    img_map = {"浙江饭店": "/travel/api/img?u=A"}
    out = _embed_images(guide, img_map)
    assert out.count("/travel/api/img?u=A") == 1


def test_fallback_skips_plain_mention():
    """名称只在普通句子里出现（非标题/列表）→ 不插图，避免乱插。"""
    guide = "我们路过了浙江饭店门口继续走。"
    out = _embed_images(guide, {"浙江饭店": "/travel/api/img?u=A"})
    assert "img?u=A" not in out


def test_fallback_not_in_streaming():
    """流式中不做兜底（正文未完整，标题可能没生成完）。"""
    guide = "### 浙江饭店\n正文"
    out = _embed_images(guide, {"浙江饭店": "/travel/api/img?u=A"}, streaming=True)
    assert "img?u=A" not in out


def test_xhs_fallback_distributes_across_guide_sections():
    """模型漏放小红书占位符时，终稿仍把灵感图分散到不同章节，避免纯文字墙。"""
    guide = "## Day 1 城市漫步\n正文\n\n## Day 2 美食路线\n正文\n\n## 住宿\n正文"
    img_map = {
        "小红书灵感·城市机位·1": "/travel/api/img?u=X1",
        "小红书灵感·本地美食·1": "/travel/api/img?u=X2",
    }
    out = _embed_images(guide, img_map)
    assert out.count("/travel/api/img?u=X") == 2
    assert out.index("img?u=X1") < out.index("## Day 2")
    assert out.index("img?u=X2") > out.index("## Day 2")


def test_xhs_fallback_can_cover_five_day_sections():
    guide = "\n\n".join(f"## Day {day}\n当天安排" for day in range(1, 6))
    img_map = {
        f"小红书灵感·第{day}天·1": f"/travel/api/img?u=D{day}"
        for day in range(1, 7)
    }
    out = _embed_images(guide, img_map)
    assert sum(f"img?u=D{day}" in out for day in range(1, 7)) == 5
    for day in range(1, 6):
        assert f"img?u=D{day}" in out


# ---------- 2026-08-04：插图把表格劈成两截（evals broken_table 抓到的线上复发） ----------

def test_rejoin_table_split_by_images():
    """线上真实形态：表头+前 3 行 → 空行 → 两张图 → 剩余行（已成孤儿）。

    孤儿行没有表头/分隔行，GFM 会当纯文本渲染成一串裸竖线。
    """
    from app.agent.orchestrator import _rejoin_split_tables

    text = "\n".join([
        "| 时段 | 地点与体验 |",
        "|------|------------|",
        "| 上午 | 抵达汉口站 |",
        "| 下午 | 黎黄陂路老街 |",
        "",
        "![巴公房子](/travel/api/img?u=a)",
        "",
        "![咸安坊](/travel/api/img?u=b)",
        "",
        "| 傍晚 | 江汉关博物馆 |",
        "| 晚上 | 江汉路步行街 |",
        "",
        "**💡 今天的重要提示**：",
    ])
    out = _rejoin_split_tables(text).split("\n")
    rows = [i for i, ln in enumerate(out) if ln.startswith("|")]
    assert rows == list(range(rows[0], rows[0] + 6)), f"表格行必须连续，实际 {rows}"
    imgs = [i for i, ln in enumerate(out) if ln.startswith("![")]
    assert min(imgs) > max(rows), "图片必须被搬到整张表之后"
    assert "**💡 今天的重要提示**：" in out


def test_rejoin_handles_model_written_blank_line_inside_table():
    """模型自己在表格中间写了空行——插入点是无辜的，同样要接回去。"""
    from app.agent.orchestrator import _rejoin_split_tables

    text = "| 时段 | 内容 |\n|---|---|\n| 上午 | A |\n\n| 下午 | B |"
    out = _rejoin_split_tables(text)
    assert out == "| 时段 | 内容 |\n|---|---|\n| 上午 | A |\n| 下午 | B |"


def test_rejoin_keeps_genuinely_separate_tables_apart():
    """第二张表自带分隔行 = 真的新表，不许合并。"""
    from app.agent.orchestrator import _rejoin_split_tables

    text = "\n".join([
        "| A | B |", "|---|---|", "| 1 | 2 |",
        "",
        "![图](/travel/api/img?u=x)",
        "",
        "| C | D |", "|---|---|", "| 3 | 4 |",
    ])
    assert _rejoin_split_tables(text) == text


def test_rejoin_is_noop_without_tables():
    from app.agent.orchestrator import _rejoin_split_tables

    text = "## 标题\n\n正文一段\n\n![图](/travel/api/img?u=x)\n\n- 列表项"
    assert _rejoin_split_tables(text) == text


def test_embed_images_never_leaves_a_split_table():
    """端到端：走完整个 _embed_images，兜底插图不得把表格劈开。"""
    from app.agent.orchestrator import _embed_images

    text = "\n".join([
        "## Day 1",
        "| 时段 | 地点与体验 |",
        "|------|------------|",
        "| 下午 | **黎黄陂路**老街漫步，路口是**巴公房子** |",
        "| 傍晚 | **江汉关博物馆** |",
        "| 晚上 | 江汉路步行街 |",
        "",
        "**提示**：早点出门",
    ])
    out = _embed_images(text, {"巴公房子": "/travel/api/img?u=a"})
    lines = out.split("\n")
    rows = [i for i, ln in enumerate(lines) if ln.startswith("|")]
    assert rows == list(range(rows[0], rows[0] + 5)), f"表格被劈开了：{out}"
