# Task Plan — Phase 10：高德地图 API 接入（结构化天气/景点/坐标数据）

> 创建：2026-07-06　状态：已完成并上线（验收见 docs/test_cases/phase10-验收用例.md）

## 背景

提速调研（见对话记录）方案 C：路线规划场景从「爬攻略文章猜路线」升级为
「真实路网/POI/天气数据」，同时接口毫秒级返回，远快于浏览器爬取。
复用铺探项目的高德 key（Putan-Lite-web，Web服务类型，开了数字签名）。

## 方案

- `app/tools/amap.py`：httpx 直连 restapi.amap.com，带数字签名
  （参数按字典序拼 `k=v&...` + 私钥取 MD5，算法与铺探 amap-proxy 一致）：
  - `geocode(address)`：目的地 → 坐标/adcode
  - `weather(adcode)`：未来 3-4 天预报（extensions=all）
  - `search_pois(keywords, city)`：景点 POI（v3/place/text，extensions=all 取评分）
  - `build_amap_source(destination)`：编排以上三个调用 → 组装结构化 summary
    （天气预报 + 热门景点清单：名称/评分/地址/坐标）→ 标准来源 dict（site=amap）
- 编排：非复用轮次收集来源时并入高德来源（~3 个 HTTP 调用 <2s，失败返回 None
  不阻塞）；progress「已获取高德实时数据（天气 + 景点）」。
- 生成 prompt（ITINERARY_SYSTEM）补充：行程参考天气（雨天排室内）、
  景点顺序参考坐标就近原则。
- 配置：`AMAP_KEY` / `AMAP_SECRET`（.env，本地 + 服务器），未配置时功能整体关闭。

## 验收标准

1. 「黄山 3 天路线」类查询：来源里出现「高德地图实时数据」，含天气预报与
   ≥5 个景点（真实评分/地址）；攻略行程体现天气与就近原则。
2. 未配置 key 时行为与现状完全一致。
3. 单测：签名函数（已知值校验）、summary 组装、未配置禁用。
