# 测试依赖真实 DNS，会被 VPN／代理搞红

**发现**：2026-09-02，跑全量后端单测时 6 条固定红：

```
tests/test_context_security.py::test_fetch_url_wraps_body_in_external_tags
tests/test_research_context.py::test_fetch_long_page_returns_preview_with_read_source_hint
tests/test_research_context.py::test_read_source_pages_through
tests/test_research_context.py::test_read_source_unknown_id_lists_available
tests/test_research_context.py::test_budget_note_after_60_percent
tests/test_research_context.py::test_urgent_note_after_80_percent
```

## 现象与真因

报错长这样，看着像抓取逻辑坏了：

```
assert '第 0-3000 字' in '没有编号为 s1 的来源。可用编号：（本轮还没有留存的来源）'
```

日志里才有真话：

```
WARNING app.tools.url_guard:url_guard.py:92
  拒绝不安全 URL 'https://example.com/a'：该域名解析到内网/保留地址
```

```
$ python -c "import socket; print(socket.gethostbyname('example.com'))"
198.18.1.232
```

`198.18.0.0/15` 是 RFC 2544 的基准测试保留段。本机挂着 VPN／分流代理，DNS 把
`example.com` 劫持到了这个段里，于是 **Phase 69 ② 的 `ensure_safe_url` 正确地拒绝了它**
——安全防线没坏，坏的是测试对**真实 DNS 解析**有依赖。

## 为什么它特别容易误导

1. **失败信息指向的是下游**（「没有编号为 s1 的来源」），而根因在上游三层之外的 URL 守卫。
2. `_fake_httpx` 已经把 HTTP 那一层 mock 掉了，看代码会以为「网络已经不参与了」——
   **但 `ensure_safe_url` 在 httpx 之前跑，而它做的是真 DNS 解析**（这正是 Phase 69 ②
   刻意加的「解析 DNS 后复验」，防域名解析到内网）。mock 了传输层不等于脱离了网络。
3. 换台机器（或关掉 VPN）就绿，于是很容易被当成偶发。

## 结论

**凡生产代码里有「真实解析／真实时钟／真实文件系统」的一步，测试就必须把那一步也接管，
否则测试的绿红取决于跑它的那台机器。** 这条与 Phase 93 那条
（「凡生产有失败静默降级的地方，评估都不能复用那条路径」）是一个道理的两面。

修法（未落地，与当次改动无关，单独做）：在这些用例里 monkeypatch
`app.tools.url_guard` 的解析函数，或给守卫一个测试用的可注入 resolver。
**不要**改成放行 `example.com` —— 那是把防线开个口子来迁就测试。
