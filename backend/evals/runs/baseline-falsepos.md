# 评估报告 · baseline

| query | 三层验证 | 耗时 | 字数 | 来源 | 小红书 | 高德 | 携程 | 复用 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| single_city_basic | ❌ 质量 | 331.7s | 6394 | 7 | 5 | ✓ | · | ♻️ |
| single_city_budget | ❌ 质量 | 264.5s | 8142 | 8 | 5 | ✓ | · | ♻️ |
| multi_city_domestic | ❌ 质量 | 173.5s | 6587 | 11 | 6 | ✓ | · | ♻️ |

## 三层验证明细

### single_city_basic　<sub>最常见的单城攻略。守表格完整、无占位符泄漏、无裸星号。</sub>

**最终回复**：# 成都3日老街小吃漫游攻略…（6394 字，耗时 332s）

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
        'chars': 6394,
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
    passed=False,
    reason="1 个维度不达标：['排版完整性']",
    codes=['qual_排版完整性'],
    evidence={
        '排版完整性': 'FAIL（raw_bold_marker）',
        '数据可读性': 'PASS',
        '内容完整性': 'PASS',
        '上下文纪律': 'PASS',
        '安全合规': 'PASS',
        '来源可溯': 'PASS',
        'findings': ['raw_bold_marker: 5 处 CJK 标点紧邻 `**`'],
    }
)
```

### single_city_budget　<sub>带预算与偏好。守价格区间不被删除线吃掉（¥400~600 类）。</sub>

**最终回复**：# 成都4日避开人潮 · 城南小众与烟火老街逛吃攻略…（8142 字，耗时 265s）

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
        'chars': 8142,
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
        '排版完整性': 'FAIL（raw_bold_marker）',
        '数据可读性': 'PASS',
        '内容完整性': 'PASS',
        '上下文纪律': 'PASS',
        '安全合规': 'PASS',
        '来源可溯': 'PASS',
        'findings': ['raw_bold_marker: 3 处 CJK 标点紧邻 `**`'],
    }
)
```

### multi_city_domestic　<sub>多城。守高德数据不整条丢失、搜索词不整串塞、正文覆盖每一城。</sub>

**最终回复**：> ⚠️ **日期提示**：你还没有提供具体的出行日期，以下所有价格均为**参考价（非实时）**，动车时刻与票价也暂无法…（6587 字，耗时 174s）

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
        'chars': 6587,
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
        '排版完整性': 'FAIL（raw_bold_marker）',
        '数据可读性': 'PASS',
        '内容完整性': 'PASS',
        '上下文纪律': 'PASS',
        '安全合规': 'PASS',
        '来源可溯': 'PASS',
        'findings': ['raw_bold_marker: 7 处 CJK 标点紧邻 `**`'],
    }
)
```
