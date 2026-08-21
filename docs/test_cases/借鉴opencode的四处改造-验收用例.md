# 借鉴 opencode 的四处改造 — 验收用例（Phase 103，2026-08-21）

计划见 `docs/task_plans/借鉴opencode的四处改造-2026-08-21.md`。
全部离线（无网络、无 LLM、sqlite 内存库）。

```bash
cd backend
.venv/bin/python -m pytest tests/test_llm_retry.py tests/test_source_pages.py \
                          tests/test_history_summary_prompt.py -q
```

实测：**69 passed**（35 + 20 + 14）。全量 `pytest tests/ -q` → **1199 passed, 6 failed**，
6 个失败是**改造前就存在**的环境问题（见文末）。

---

## `tests/test_llm_retry.py` — 传输层重试（35 条）

### 可重试判定

| 用例 | 断言 |
| --- | --- |
| `test_is_retryable[429/500/502/504]` | 状态码可重试 |
| `test_is_retryable[503 无特征文本]` | **5xx 一律重试**，哪怕文本毫无特征（SDK 的 isRetryable 常漏标） |
| `test_is_retryable[Service Unavailable / Connection reset / timed out / 服务繁忙]` | 无状态码时靠错误文本兜底 |
| `test_is_retryable[401/404/400]` | 我们自己的问题，一次都不重试 |
| `test_is_retryable[ValueError 校验失败]` | 非传输错误不进重试循环 |
| `test_context_overflow_never_retried` | 四种 overflow 报文形态全部不重试 |
| `test_overflow_wins_over_retryable_signal` | **判定顺序**：`"500 error: context_length_exceeded"` 判为不可重试。先判可重试会把它放进循环，白烧几次超长请求 |

### 退避时长

| 用例 | 断言 |
| --- | --- |
| `test_retry_after_seconds_header` | `Retry-After: 3` → 3.0s |
| `test_retry_after_ms_header_wins` | 同时给两个头时 `retry-after-ms` 优先（更精确） |
| `test_retry_after_http_date` | HTTP-date 形态可解析 |
| `test_retry_after_garbage_falls_back` | 头是垃圾/缺失 → None，退化为指数退避 |
| `test_explicit_retry_after_overrides_backoff` | 服务端说 45s 就等 45s，可超过 30s 无头封顶 |
| `test_exponential_backoff_with_jitter` | attempt=1 → [2.0, 2.5]；attempt=3 → 8.0；attempt=9 → 封顶 30s |
| `test_jitter_stays_within_band` | 50 次采样全部落在 [4.0, 5.0]（防惊群，但不能失控） |

### 重试循环与取消

| 用例 | 断言 |
| --- | --- |
| `test_retries_then_succeeds` | 前两次 503、第三次成功 → 返回结果，共调 3 次 |
| `test_gives_up_after_max_retries` | max_retries=2 → 共调 3 次后抛原始异常 |
| `test_non_retryable_raises_immediately` | 401 → 只调 1 次 |
| `test_cancel_is_not_a_failure` | `TurnCancelled` 不被重试成 5 次 |
| `test_backoff_is_interruptible` | 已取消时 `sleep_interruptible(30)` **1 秒内**返回，不是等 30 秒 |
| `test_cancel_during_backoff_stops_further_calls` | 退避期间被取消 → 抛 `TurnCancelled` **且不再发起下一次请求** |
| `test_sleep_without_abort_callback_still_sleeps` | 不传 cid 时退化为普通分片 sleep，行为同改造前 |

### 流式（最容易静默失效的一组）

| 用例 | 断言 |
| --- | --- |
| `test_stream_retries_before_first_token` | 首块之前连接断 → 重开流，输出完整。这是最常见的失败点（建连/首字节） |
| **`test_stream_does_not_retry_after_producing_output`** | 已 yield 过 delta 后失败 → **直接抛，不重开流**。静默失效的线上表现是「攻略写到一半又从头写了一遍」 |
| `test_stream_gives_up_after_max_retries` | 总请求数 == `MAX_RETRIES + 1`。**这条钉住的是双层嵌套**（见踩坑文档） |
| `test_stream_non_retryable_raises_immediately` | overflow → 只调 1 次 |
| `test_stream_yields_finish_reason` | `("finish", "stop")` 仍被透出——它是 Phase 11 续写的判据，重试改造不能吃掉 |

---

## `tests/test_source_pages.py` — 来源全文落库与重取（20 条）

### 纯函数

| 用例 | 断言 |
| --- | --- |
| `test_keywords_split_chinese` | 「第3家酒店的取消政策是什么」能切出 `取消政策`，且无整句 token |
| `test_keywords_keep_place_name_chars` | `湖里区`/`中山路` 可被切出——虚词表刻意不含 中/上/下/里/出 |
| `test_keywords_drop_stopwords_and_dedupe` | 「推荐/攻略/行程」这类问句噪声词被丢弃 |
| `test_focus_excerpt_hits_the_right_window` | 命中「取消政策」→ 窗口含「免费取消」，长度受 limit 控制 |
| `test_focus_excerpt_returns_empty_on_miss` | 未命中返回**空串**。这里若悄悄给个头部截断，调用方就无从区分「找到了」和「没找到」，进度气泡会谎报 |
| `test_focus_excerpt_is_idempotent` | 同输入同输出（Phase 96 的教训：裁剪必须幂等） |
| `test_focus_excerpt_merges_overlapping_windows` | 相邻关键词窗口相交时合并，同一段正文不拼两遍 |
| `test_focus_excerpt_marks_discontinuity` | 远距离两段之间有「…」断点，否则模型当连续正文读 |

### 落库

| 用例 | 断言 |
| --- | --- |
| `test_save_and_load` | 存取往返一致 |
| `test_save_is_upsert_per_conversation_url` | 同会话同 URL 覆盖，表里只有 1 行 |
| `test_save_truncates_to_cap` | 超 `source_full_text_max_chars` 截断入库 |
| `test_save_skips_empty` | 空正文/空 cid 返回 None，不写脏行 |
| `test_prune_keeps_recent_only` | 超 `source_page_keep` 触发剪枝 |
| `test_prune_is_per_conversation` | 剪枝不跨会话误删 |
| `test_save_failure_returns_none_not_raises` | DB 挂了返回 None 而不是抛——全文是增强，不能拖垮采集 |

### 复用重取

| 用例 | 断言 |
| --- | --- |
| `test_refresh_focuses_on_current_question` | 追问「取消政策」→ 摘录换成含「免费取消」的窗口，其余字段原样 |
| `test_refresh_keeps_old_summary_on_miss` | 未命中 → 退回旧 summary（**降级方向永远是「和改造前一样」**） |
| `test_refresh_tolerates_legacy_sources_without_page_id` | 存量消息里没有 page_id 的来源不炸 |
| `test_refresh_handles_empty_and_no_keywords` | 空来源/无关键词安全返回 |
| `test_refresh_partial_hit_reports_accurate_count` | 两页只命中一页 → `hits == 1`。进度气泡播的「重新定位了 N 处」不能虚报 |

---

## `tests/test_history_summary_prompt.py` — 压缩顺序与提示词（14 条）

### 提示词纪律与标签（改造②）

| 用例 | 断言 |
| --- | --- |
| `test_system_states_prior_summary_is_discarded` | system 含「丢弃」「永久丢失」 |
| `test_system_states_conversation_wins_on_conflict` | system 含「冲突」「为准」 |
| `test_system_keeps_original_four_sections` | 原有四小节没被新纪律挤掉（「已排除的选项+原因」是防复读机的，opencode 都没有） |
| `test_listing_wraps_both_blocks_when_prior_exists` | 两个标签都在、旧摘要内容落在 `<prior-summary>` 块内、裸的「（此前的摘要）」前缀已移除 |
| `test_no_empty_prior_tag_when_absent` | 无旧摘要时**不出现空标签**——免得模型对着空标签脑补 |
| **`test_prior_summary_cannot_break_out_of_its_tag`** | 旧摘要正文含 `</prior-summary>` 时不穿透（同 Phase 69 ④）。旧摘要是上一次模型的输出，而我们刚把标签名写进了 system |
| `test_strip_tag_is_narrow` | 只剥同名标签，`<b>` 之类原样保留 |

### 触发条件不变

| 用例 | 断言 |
| --- | --- |
| `test_short_conversation_not_compacted` | 字数没超 → **根本没调模型**（Phase 91 的保真度回归防线） |
| `test_few_rounds_not_compacted` | 轮次不够 → 不压 |
| `test_compaction_failure_is_swallowed` | provider 挂了不抛异常 |

### 顺序（改造①）

| 用例 | 断言 |
| --- | --- |
| `test_guide_finalizes_before_compaction` | `finalize_guide` 里终稿在压缩之前 |
| `test_direct_finalizes_before_compaction` | `run_direct_answer` 同上 |
| `test_memory_extraction_stays_before_finalize` | `extract_and_save` **有**数据依赖（saved 进 meta），不能跟着挪走 |
| `test_research_path_already_correct` | research 链路本来就对，别在对齐时改坏 |

> ⚠️ 这三条顺序断言用 `rindex` 而非 `index`：`_finalize_streaming_message` 在取消分支里也
> 出现一次，比对首次出现会让断言变成**永真**。要比的是收尾时的顺序。

---

## 已知的环境性失败（与本次改造无关）

`tests/test_research_context.py` 5 条 + `tests/test_context_security.py` 1 条在本机失败：

```
WARNING app.tools.url_guard: 拒绝不安全 URL 'https://example.com/a'：该域名解析到内网/保留地址
```

本机 DNS 把 `example.com` 解析到内网/保留地址，触发 Phase 69 ② 的「解析 DNS 后复验」。
**改造前 `git stash` 验证过：同样这 6 条失败**，与本次无关。服务器上不复现。
