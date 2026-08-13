# Phase 18 手账「城市旅行路线图」海报 — 验收用例

自动化测试：`backend/tests/test_poster.py`（8 例）。
命令：`cd backend && .venv/bin/python -m pytest tests/test_poster.py -q`

| # | 用例 | 期望 | 覆盖 |
| --- | --- | --- | --- |
| 1 | payload 按天分组、天内按 order 重编号 | 玉林(2)排宽窄巷子(5)前，重编 1,2 | `test_build_payload_groups_by_day_and_renumbers` |
| 2 | 每天带路线名/主题/距离/时长 + 逐天 map | title/subtitle/distance(约N公里)/duration/map 齐全；缺 day_meta 回退「Day N 路线」 | 同上 |
| 3 | 右栏 hotels/foods/specialties/tips 组装 + 补图 | 照片按名回填，price/note 保留 | `test_build_payload_right_column_sections` |
| 4 | haversine 路线距离 | 断桥→雷峰塔≈3.4km；单点=0 | `test_route_distance_haversine` |
| 5 | 空点位 → 空 payload | `{}` | `test_build_payload_empty` |
| 6 | staticmap URL / 点位校验 / schema 默认 | — | `test_staticmap_url_format` 等 |

## 线上 E2E（已执行 ✅）

**数据管线**（黄山攻略）：抽取得到 title/theme「奇松怪石·云海仙境·徽味老街」、
每天路线名（西海大环线/迎客徽味线）、14 点位、酒店 4、美食 6、特产 2、贴士 4；
限流后 14/14 点位定位成功，酒店图 4/4、美食图 6/6。

**生产触发**（`POST /api/chat/{cid}/poster`，厦门）：返回带 `meta.poster` 的消息，
含 theme、逐天路线名+距离+时长+地图、美食 5（4 图）、贴士 4；该攻略未提酒店/特产 →
两栏留空并被前端隐藏（优雅降级）。

**真机渲染**（生产 React 应用，admin 登录打开厦门会话）：路线图版式正确渲染——
毛笔标题+朱印、左路线卡（编号色=地图 marker 色）、中逐天地图（marker 加载正常）、
图例、右栏美食（实景图加载）/贴士，无大片留白。截图见会话记录。

## 设计还原说明

参考图为纯手绘水彩地图（画师作品，无法程序化生成）→ 用高德静态地图近似，外套
宣纸/朱印/毛笔国风。信息设计（左路线卡 / 中地图 / 右美食·酒店·特产·贴士 / 底路线一览）
与参考一致。景点在地图按天编号+连线，酒店/美食带实景图卡片——覆盖用户「酒店/美食/
景点都标上去」的诉求。
