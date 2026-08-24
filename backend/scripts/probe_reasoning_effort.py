"""探测 DeepSeek 的 `thinking` / `reasoning_effort` 协议字段是否真的生效。

用法（**必须在服务器上跑**，本机连不上 api.deepseek.com）：

    ssh ubuntu@42.194.202.233 'cd /home/ubuntu/travel-agent/backend && \
        .venv/bin/python -m scripts.probe_reasoning_effort'

判定标准：**只看 `usage.completion_tokens_details.reasoning_tokens`**。
HTTP 200 不能作为「生效」的证据——未知字段被服务端静默忽略时同样返回 200，
那会拿到一个「改了但没效果」的假成功。
"""

import json
import statistics
import sys
import time

from openai import OpenAI

from app.config import settings

# 一段真实的抽取任务：从攻略 Markdown 里挑地点填 schema。
# 刻意选 Phase 102 实测烧掉 13124 思考 token 的那类任务形态。
EXTRACT_PROMPT = """从下面的行程片段里抽出所有地点，输出 JSON：
{"stops": [{"day": 天数, "name": "地点名", "type": "景点|餐饮|住宿"}]}

Day 1：上午到杭州东站，先去酒店放行李（杭州西湖柏悦酒店，湖滨银泰旁）。
中午在知味观（仁和路店）吃小笼和片儿川，人均 60。下午租车游西湖，
断桥残雪 → 白堤 → 平湖秋月 → 苏堤春晓，傍晚在雷峰塔看日落。
晚饭河坊街，推荐皇饭儿的西湖醋鱼。

Day 2：早上灵隐寺（飞来峰石窟一并看了），中午永福寺的素斋。
下午龙井村喝茶，狮峰山采茶体验。晚上住西溪湿地附近的悦榕庄。

Day 3：西溪湿地摇橹船，午饭在西溪天堂的外婆家。下午去良渚古城遗址公园，
晚上杭州东站返程。两人三天合计花费 6800 元。
"""

SYSTEM = "你是行程信息抽取助手，只输出 JSON，不要 markdown 代码块。"


def thinking_kwargs(effort: str | None) -> dict:
    """把语义档位翻成请求字段（与 client.py 的 _thinking_kwargs 保持同一张表）。

    上游 dsh `serialize.ts::resolveThinking` 的映射：
      off            → thinking=disabled，**不带** reasoning_effort
      low/high/max   → thinking=enabled + reasoning_effort=<档位>
    `thinking` 不是 openai SDK 的已知参数，必须走 extra_body（SDK 会把它合并到请求体顶层）。
    """
    if effort is None:
        return {}
    if effort == "off":
        return {"extra_body": {"thinking": {"type": "disabled"}}}
    return {
        "reasoning_effort": effort,
        "extra_body": {"thinking": {"type": "enabled"}},
    }


def probe(client: OpenAI, model: str, effort: str | None, rounds: int) -> dict:
    lat, reasoning, out, ok_json = [], [], [], 0
    err = None
    for _ in range(rounds):
        t0 = time.time()
        try:
            resp = client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": SYSTEM},
                    {"role": "user", "content": EXTRACT_PROMPT},
                ],
                max_tokens=3000,
                response_format={"type": "json_object"},
                **thinking_kwargs(effort),
            )
        except Exception as e:  # noqa: BLE001 — 探测脚本要把失败原因原样带回
            err = f"{type(e).__name__}: {e}"
            break
        lat.append(time.time() - t0)
        usage = resp.usage
        details = getattr(usage, "completion_tokens_details", None)
        reasoning.append(getattr(details, "reasoning_tokens", None) or 0)
        out.append(usage.completion_tokens or 0)
        raw = resp.choices[0].message.content or ""
        try:
            json.loads(raw)
            ok_json += 1
        except json.JSONDecodeError:
            pass
    med = lambda xs: round(statistics.median(xs), 1) if xs else None  # noqa: E731
    return {
        "model": model,
        "effort": effort or "(基线·不带字段)",
        "error": err,
        "n": len(lat),
        "latency_med_s": med(lat),
        "reasoning_tok_med": med(reasoning),
        "out_tok_med": med(out),
        "json_ok": f"{ok_json}/{len(lat)}" if lat else "-",
    }


def main() -> int:
    client = OpenAI(
        api_key=settings.deepseek_api_key,
        base_url=settings.deepseek_base_url,
        timeout=settings.llm_timeout_s,
    )
    models = [settings.model_extractor, settings.model_classifier]
    if settings.model_vision:
        models.append(settings.model_vision)
    rounds = 3

    rows = []
    for model in models:
        for effort in (None, "off", "low", "high"):
            row = probe(client, model, effort, rounds)
            rows.append(row)
            flag = "✗ " + (row["error"] or "") if row["error"] else "✓"
            print(
                f"{row['model']:<34} {row['effort']:<18} "
                f"延迟 {str(row['latency_med_s']):>6}s  "
                f"思考 {str(row['reasoning_tok_med']):>6}  "
                f"正文 {str(row['out_tok_med']):>5}  "
                f"json {row['json_ok']:>4}  {flag}",
                flush=True,
            )

    print("\n=== 判定 ===")
    print("（判「字段是否被接受」只看明确不同于默认的档位，如 off/low；"
          "与基线相当的档位不构成任何一侧的证据）")
    for model in models:
        base = next((r for r in rows if r["model"] == model and r["effort"].startswith("(")), None)
        if not base or base["error"] or base["reasoning_tok_med"] is None:
            print(f"{model}: 基线就没跑成，无法判定")
            continue
        for r in rows:
            if r["model"] != model or r["effort"].startswith("("):
                continue
            if r["error"]:
                print(f"{model} / {r['effort']}: ✗ 被拒绝 — {r['error']}")
            elif abs(r["reasoning_tok_med"] - base["reasoning_tok_med"]) <= max(
                60, 0.05 * (base["reasoning_tok_med"] or 1)
            ):
                # ⚠️ 「与基线相同」**不是**「被忽略」的证据：该档位恰好等于模型默认档时
                # 结果本来就该相同（实测 high 就是默认档）。这两个假设在这一档上观测不可分，
                # 所以只能如实报「无法区分」，判生效要看明确不同于默认的那一档（off/low）。
                # 见 docs/pitfalls/用与基线相同来判定字段未生效会误报默认档.md
                print(
                    f"{model} / {r['effort']}: ～ 与基线相当"
                    f"（{base['reasoning_tok_med']} vs {r['reasoning_tok_med']}）"
                    f"——该档位可能就是默认档，本次数据无法区分「生效」与「被忽略」"
                )
            else:
                delta = r["reasoning_tok_med"] - base["reasoning_tok_med"]
                print(
                    f"{model} / {r['effort']}: ✓ 生效，思考 token "
                    f"{base['reasoning_tok_med']} → {r['reasoning_tok_med']}（{delta:+}）"
                )
    print("\n原始数据：")
    print(json.dumps(rows, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
