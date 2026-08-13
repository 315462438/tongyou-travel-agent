# 评估报告 · baseline

| query | 三层验证 | 耗时 | 字数 | 来源 | 小红书 | 高德 | 携程 | 复用 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| single_city_basic | ✅ | 230.6s | 6136 | 7 | 5 | ✓ | · | ♻️ |
| single_city_budget | ✅ | 251.1s | 10139 | 7 | 5 | ✓ | · | ♻️ |
| multi_city_domestic | ❌ 质量 | 166.1s | 8324 | 11 | 6 | ✓ | · | ♻️ |

## 三层验证明细

### single_city_basic　<sub>最常见的单城攻略。守表格完整、无占位符泄漏、无裸星号。</sub>

**最终回复**：# 成都3日老街小吃漫游攻略…（6136 字，耗时 231s）

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
        ],
        'days_required': 3,
        'cities_required': ['成都'],
        'cities_missing': [],
        'sources_count': 7,
        'source_sites': [
            'amap',
            'web',
            'xhs',
        ],
        'chars': 6136,
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
        'progress_steps': 6,
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

**最终回复**：# 成都4日反向漫游攻略｜国庆躲人潮，钻进城南新贵与老巷烟火…（10139 字，耗时 251s）

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
        'sources_count': 7,
        'source_sites': [
            'amap',
            'web',
            'xhs',
        ],
        'chars': 10139,
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
        'progress_steps': 6,
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

### multi_city_domestic　<sub>多城。守高德数据不整条丢失、搜索词不整串塞、正文覆盖每一城。</sub>

**最终回复**：# 武汉→开封→洛阳 6 日动车古都穿行：从荆楚风华到北宋烟云再到盛唐气象…（8324 字，耗时 166s）

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
        'sources_count': 11,
        'source_sites': [
            'amap',
            'web',
            'xhs',
        ],
        'chars': 8324,
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
    codes=['qual_排版完整性'],
    evidence={
        '排版完整性': 'FAIL（broken_table）',
        '数据可读性': 'PASS',
        '内容完整性': 'PASS',
        '上下文纪律': 'PASS',
        '安全合规': 'PASS',
        '来源可溯': 'PASS',
        'findings': ["broken_table: 发现 2 处断裂的表格行：['| 傍晚 17:00-18:30 | **江汉关博物馆**，在百年钟楼里看汉口开', '| 晚上 18:00 起 | 开封府出来后步行可达**鼓楼夜市**或**西司夜市']"],
    }
)
```
