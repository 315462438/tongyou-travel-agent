# 评估报告 · baseline

| query | 三层验证 | 耗时 | 字数 | 来源 | 小红书 | 高德 | 携程 | 复用 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| single_city_basic | ✅ | 245.4s | 5595 | 6 | 5 | ✓ | · | · |
| single_city_budget | ❌ 1 | 233.0s | 7758 | 8 | 5 | ✓ | · | ♻️ |
| multi_city_domestic | ✅ | 371.5s | 8089 | 9 | 6 | ✓ | · | · |

## 三层验证明细

### single_city_basic　<sub>最常见的单城攻略。守表格完整、无占位符泄漏、无裸星号。</sub>

**最终回复**：# 成都3日老街小吃漫游攻略…（5595 字，耗时 245s）

**工具调用顺序**：
- parse_request
- amap_city_brief
- xhs_search
- xhs_detail
- web_search_skipped
- generate_guide

**结果验证**：
```
VerificationResult(
    passed=True,
    reason='产出覆盖了用户要求的全部天数与城市，且有真实来源支撑',
    evidence={
        'days_covered': [
            1,
            2,
            3,
        ],
        'days_required': 3,
        'cities_required': ['成都'],
        'cities_missing': [],
        'sources_count': 6,
        'source_sites': [
            'amap',
            'xhs',
        ],
        'chars': 5595,
        'truncated': False,
    }
)
```

**过程验证**：
```
VerificationResult(
    passed=True,
    reason='调用顺序与降级策略均符合既定纪律',
    evidence={
        'tool_sequence': [
            'parse_request',
            'amap_city_brief',
            'xhs_search',
            'xhs_detail',
            'web_search_skipped',
            'generate_guide',
        ],
        'reused_sources': False,
        'web_search_skipped': True,
        'continued_generation': False,
        'progress_steps': 12,
    }
)
```

**质量验证**：
```
VerificationResult(
    passed=True,
    reason='全部质量维度通过',
    evidence={
        '排版完整性': 'PASS',
        '数据可读性': 'PASS',
        '内容完整性': 'PASS',
        '上下文纪律': 'PASS',
        '安全合规': 'PASS',
        '来源可溯': 'PASS',
        'findings': '无',
    }
)
```

### single_city_budget　<sub>带预算与偏好。守价格区间不被删除线吃掉（¥400~600 类）。</sub>

**最终回复**：# 成都4日小众逛吃攻略｜国庆避开人潮，专走本地人私藏路线…（7758 字，耗时 233s）

**工具调用顺序**：
- parse_request
- amap_city_brief
- reuse_recent_sources
- web_search
- generate_guide

**结果验证**：
```
VerificationResult(
    passed=True,
    reason='产出覆盖了用户要求的全部天数与城市，且有真实来源支撑',
    evidence={
        'days_covered': [
            1,
            2,
            3,
            4,
        ],
        'days_required': 4,
        'cities_required': ['成都'],
        'cities_missing': [],
        'sources_count': 8,
        'source_sites': [
            'amap',
            'web',
            'xhs',
        ],
        'chars': 7758,
        'truncated': False,
    }
)
```

**过程验证**：
```
VerificationResult(
    passed=True,
    reason='调用顺序与降级策略均符合既定纪律',
    evidence={
        'tool_sequence': [
            'parse_request',
            'amap_city_brief',
            'reuse_recent_sources',
            'web_search',
            'generate_guide',
        ],
        'reused_sources': True,
        'web_search_skipped': False,
        'continued_generation': False,
        'progress_steps': 7,
    }
)
```

**质量验证**：
```
VerificationResult(
    passed=False,
    reason="1 个维度不达标：['排版完整性']",
    evidence={
        '排版完整性': 'FAIL（raw_bold_marker）',
        '数据可读性': 'PASS',
        '内容完整性': 'PASS',
        '上下文纪律': 'PASS',
        '安全合规': 'PASS',
        '来源可溯': 'PASS',
        'findings': ['raw_bold_marker: 11 处 CJK 标点紧邻 `**`'],
    }
)
```

### multi_city_domestic　<sub>多城。守高德数据不整条丢失、搜索词不整串塞、正文覆盖每一城。</sub>

**最终回复**：> **行程速览**：6天动车串联武汉→开封→洛阳三大古都，以“三国鼎立”的历史轴线为主线，节奏张弛有度——武汉两日看江…（8089 字，耗时 372s）

**工具调用顺序**：
- parse_request
- amap_city_brief
- xhs_search
- xhs_detail
- xhs_search
- web_search_skipped
- generate_guide

**结果验证**：
```
VerificationResult(
    passed=True,
    reason='产出覆盖了用户要求的全部天数与城市，且有真实来源支撑',
    evidence={
        'days_covered': [
            1,
            2,
            3,
            4,
            5,
            6,
        ],
        'days_required': 6,
        'cities_required': [
            '武汉',
            '开封',
            '洛阳',
        ],
        'cities_missing': [],
        'sources_count': 9,
        'source_sites': [
            'amap',
            'xhs',
        ],
        'chars': 8089,
        'truncated': False,
    }
)
```

**过程验证**：
```
VerificationResult(
    passed=True,
    reason='调用顺序与降级策略均符合既定纪律',
    evidence={
        'tool_sequence': [
            'parse_request',
            'amap_city_brief',
            'xhs_search',
            'xhs_detail',
            'xhs_search',
            'web_search_skipped',
            'generate_guide',
        ],
        'reused_sources': False,
        'web_search_skipped': True,
        'continued_generation': False,
        'progress_steps': 12,
    }
)
```

**质量验证**：
```
VerificationResult(
    passed=True,
    reason='全部质量维度通过',
    evidence={
        '排版完整性': 'PASS',
        '数据可读性': 'PASS',
        '内容完整性': 'PASS',
        '上下文纪律': 'PASS',
        '安全合规': 'PASS',
        '来源可溯': 'PASS',
        'findings': '无',
    }
)
```
