"""把 `extract.yaml` 里登记的攻略样本从库里拉到 `evals/samples/`（2026-08-14）。

样本不进 git（真实用户会话产物），但**必须固定不变**——评估集的输入一旦漂移，
前后对照就没有意义了。所以这里按 `message_id` 拉，落盘后校验 `sha256`，
对不上直接报错而不是将就着用。

用法（backend/ 下，需要能连到库：本地先跑 scripts/db_tunnel.sh）：

    .venv/bin/python -m evals.fetch_samples
"""

from __future__ import annotations

import hashlib
import pathlib
import sys

ROOT = pathlib.Path(__file__).parent
SAMPLES = ROOT / "samples"


def digest(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def load_specs() -> list[dict]:
    import yaml

    rows = yaml.safe_load((ROOT / "extract.yaml").read_text(encoding="utf-8")) or []
    return [r for r in rows if r.get("message_id")]


def main() -> int:
    from sqlalchemy import select

    from app.db.models import TravelMessage
    from app.db.session import get_session

    SAMPLES.mkdir(parents=True, exist_ok=True)
    specs = load_specs()
    bad = 0
    with get_session() as db:
        for spec in specs:
            path = SAMPLES / f"{spec['id']}.md"
            row = db.execute(
                select(TravelMessage).where(TravelMessage.id == spec["message_id"])
            ).scalar_one_or_none()
            if row is None:
                print(f"✗ {spec['id']}：库里找不到 {spec['message_id']}", file=sys.stderr)
                bad += 1
                continue
            text = (row.content or "").strip() + "\n"
            got = digest(text)
            if got != spec["sha256"]:
                print(f"✗ {spec['id']}：内容哈希 {got} ≠ 登记的 {spec['sha256']}"
                      "（样本被改过？期望值可能已经对不上了）", file=sys.stderr)
                bad += 1
                continue
            path.write_text(text, encoding="utf-8")
            print(f"✓ {spec['id']}　{len(text)} 字")
    print(f"\n{len(specs) - bad}/{len(specs)} 条就位 → {SAMPLES}")
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
