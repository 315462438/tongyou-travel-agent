# Task Plan — Phase 41：行程记账本（多人 AA + 一键结算）

## 目标（用户原话）

预算那块搞个**多用户记账本**：谁垫付了什么随手记，最后**一键总结谁出了多少钱**、
谁该给谁转多少——多人出行的核心痛点。

## 方案

### 数据模型

`travel_trip_expense`：id / trip_id / payer_user_id（垫付人）/ amount / title /
category（餐饮·交通·门票·住宿·购物·其他）/ participants_json（参与分摊的 user_id 列表，
默认记账时的全体成员）/ created_by / created_at。

### 结算算法（纯函数，零 LLM）

`settle_expenses(expenses) -> {total, by_category, per_person, transfers}`：
- per_person：每人 垫付(paid) / 应摊(share=Σ 各笔 amount/参与人数) / 差额(balance)；
- transfers：**最小转账次数**贪心——欠款人按额度从大到小匹配债权人（Splitwise 同款），
  分账除不尽的零头归垫付人（误差 <0.01 不生成转账）。

### API

- `GET/POST /{id}/expenses`、`DELETE /{id}/expenses/{eid}`（本人或 owner 可删）；
- `GET /{id}/expenses/summary`：结算结果 + 可复制的文字账单；
- 记账/删账写入修改记录（Phase 38 event）。

### 前端（右栏新增「🧾 记账本」面板）

- 流水列表：垫付人头像 + 标题 + 分类 chip + 金额；本人可删；
- 记一笔：金额 + 标题 + 分类下拉 + 参与人 chips（默认全员，点选排除）；
- **一键结算**弹窗：总支出/分类小计/每人「垫付 vs 应摊 vs 差额」表格 +
  「bob → alice ¥133」转账清单 + 复制文字账单按钮；
- 预算面板联动：门票预估之外显示「已记账实际支出 ¥X」。

## 验收

- settle 纯函数：三人不均摊样例（含部分人参与的账目）结算正确、转账清单金额守恒、
  零头处理（自动化）；
- API：成员才能记账、只能删自己的（owner 例外）、summary 各字段正确（自动化）；
- 线上双账号：A/B 各记几笔 → 双方实时看到 → 一键结算给出正确转账建议。
