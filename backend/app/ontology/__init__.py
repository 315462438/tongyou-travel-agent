"""本体层（Phase 86）

把 Palantir 本体的三件套落到本项目：

- **Object**（`objects.py`）：有稳定 id 的业务实体（Trip / Day / Stop / Expense …），
  是所有下游消费者的**唯一事实源**。
- **Link**（`objects.py` 的 link 访问器）：实体间的类型化关系，显式声明而非靠外键隐含。
- **Action**（`actions.py`）：唯一的写入通道，带类型参数 + 前置校验 + 审计。

为什么要有这一层：此前 `poster.py` / `budget.py` / 行程导入各自用 LLM 从攻略 Markdown
**再解析一遍**，同一份行程被解析三次、结果互不一致，而且都截断（`guide[:5000]`/`[:6000]`），
长攻略后半段的花费和点位直接丢失。现在攻略终稿后只抽取一次成 `TripObject`，
poster/budget/行程板全部从对象图**投影**（`projections.py`）。
"""

from app.ontology.objects import (  # noqa: F401
    SCHEMA_VERSION,
    DayObject,
    ExpenseObject,
    FoodObject,
    LodgingObject,
    ReservationObject,
    SpecialtyObject,
    StopObject,
    TripObject,
    oid,
)
