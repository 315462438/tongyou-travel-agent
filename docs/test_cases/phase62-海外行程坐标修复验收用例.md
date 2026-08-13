# Phase 62：海外行程坐标修复验收用例

## 自动化用例

### 后端

1. 国内缓存
   - 成都地点首次查询走高德并写 `v2|amap|cn|...`；
   - 再次查询直接命中；
   - `force_refresh` 绕过缓存。
2. 海外 provider 隔离
   - 吉隆坡地点只调用全球编码，不调用高德 POI；
   - 旧 `吉隆坡|地点` 中国坐标缓存不会命中；
   - 新结果写 `v2|photon|my|...`。
3. 候选可信度
   - 国家码不一致的候选被拒绝；
   - 距城市锚点超过 120km 的同国候选被拒绝；
   - 相关性排序中首个合法候选被采纳。
   - 海外 `search_name` 使用英文/当地官方名查询，界面仍展示中文 `name`。
4. 已有坐标修复
   - 能重新解析的地点覆盖为马来西亚坐标；
   - 无新结果且远离吉隆坡锚点的旧中国坐标被清空；
   - 返回 updated/cleared/unresolved 统计。
   - Day2 过夜仙本那时，“吉隆坡国际机场”能回退到吉隆坡查询，“仙本那镇”仍落仙本那。
5. 检查中心
   - 一天内多次超长跳点生成 `kind=geocode`、`action=repair_geocode`；
   - 可疑坐标不再重复生成长途驾驶结论。
6. 路径降级
   - 吉隆坡坐标不调用高德 direction；
   - 返回正数时间/距离，并带 `estimated=true` 与海外估算说明。

运行：

```bash
cd backend
.venv/bin/python -m pytest tests/test_geocode_cache.py tests/test_trip_collab.py tests/test_amap.py -q
```

### 前端

1. 地图下方存在“重新定位”入口与处理中禁用态。
2. `repair_geocode` 告警点击后调用修复接口。
3. 海外估算路段展示“估算”徽章。
4. 页面展示 OpenStreetMap contributors 署名。

运行：

```bash
cd frontend
npm test
npm run lint
npm run build
```

## 人工验收

1. 打开“吉隆坡 + 仙本那 + 亚庇”已有行程。
2. 检查中心应显示坐标异常告警；点击告警或地图下方“重新定位”。
3. 修复后吉隆坡点位集中在马来西亚半岛，仙本那/亚庇点位位于沙巴，不再散落中国。
4. 未在 OSM 找到的地点显示问号且不参与串路线，不能保留旧中国坐标。
5. 切换各 Day，地图缩放范围与当天城市一致。
6. 相邻海外路段显示“估算”；国内成都行程仍显示高德真实路线且无“估算”徽章。
