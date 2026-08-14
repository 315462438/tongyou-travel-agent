"""幂等中段截断（Phase 89，借鉴 dsh 的 compaction-tool-result-pruner）

## 为什么要有这个模块

项目里到处在截断长文本（工具结果预览、来源摘录、进度文案摘要），但没有一处保证
**截过一次的东西再截一次不会变**。不幂等的截断有两个真实后果：

1. 同一段内容在链路里被截多次，每次都少一点，最后剩个头尾拼盘；
2. 排查时无法判断「这段是原文还是被截过的」——因为截断痕迹本身也会被截掉。

dsh 的 pruner 在**配置校验期**就用一条数学约束根治了它：

    headChars + marker + tailChars <= thresholdChars

于是「任何超预算输入的输出都严格小于输入、且必然落在阈值内」，第二遍自然不产生
任何替换。这里把同一条约束搬过来。

## 与尾部截断的区别

`text[:limit]` 这种尾部截断本身就是幂等的（截过的已经 ≤ limit）。需要这个模块的是
**中段截断**——保留头尾、挖掉中间，因为它会往结果里插入标记，长度不再单调可预测。
"""

from __future__ import annotations

# 中段省略标记。固定不变：它同时是给模型的信号和给排查者的痕迹。
MARKER = "\n\n[……中间内容已省略……]\n\n"


class TruncateBudget:
    """一组头/尾/阈值预算，构造时即校验幂等约束。

    **失败要响**：预算配错了静默回落默认值，会让这个 bug 一直藏着（dsh 的 fail-loud）。
    """

    def __init__(self, threshold: int, head: int, tail: int, marker: str = MARKER) -> None:
        if threshold < 1:
            raise ValueError(f"threshold 必须为正，收到 {threshold}")
        if head < 0 or tail < 0:
            raise ValueError(f"head/tail 不能为负，收到 head={head} tail={tail}")
        # 核心约束：截断结果必须能装进阈值，否则第二遍还会再截一次（永远收敛不了）
        if head + len(marker) + tail > threshold:
            raise ValueError(
                f"预算不自洽：head({head}) + marker({len(marker)}) + tail({tail}) "
                f"> threshold({threshold})，这样截出来的结果仍超阈值，会被反复截断"
            )
        self.threshold = threshold
        self.head = head
        self.tail = tail
        self.marker = marker

    def apply(self, text: str) -> str:
        """未超阈值原样返回；超了就截成 头 + 标记 + 尾。

        幂等：输出长度 = head + len(marker) + tail <= threshold，
        所以对输出再调一次一定走「未超阈值」分支，原样返回。
        """
        s = text or ""
        if len(s) <= self.threshold:
            return s
        if self.tail == 0:
            return s[: self.head] + self.marker
        return s[: self.head] + self.marker + s[-self.tail :]

    def was_truncated(self, text: str) -> bool:
        """这段文本是不是被本预算截过——排查时用来区分原文与截断产物。"""
        return self.marker in (text or "")


# 工具结果预览：留足开头（模型主要靠它判断这个来源有没有用）+ 一小段结尾
TOOL_RESULT = TruncateBudget(threshold=8192, head=4096, tail=1024)

# 进度/摘要类短文本：只保留开头，尾部无意义
BRIEF = TruncateBudget(threshold=200, head=160, tail=0, marker="…")
