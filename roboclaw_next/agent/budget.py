from __future__ import annotations

import json
import math
from dataclasses import dataclass
from typing import Any


# 每条消息除内容外的固定开销（role、分隔符等），取一个偏保守的估计。
MESSAGE_OVERHEAD_TOKENS = 4

# 每 4 个字符估一个 token。这是英文文本的常用经验值，对中文会明显低估。
CHARS_PER_TOKEN = 4.0


class ContextOverflow(RuntimeError):
    """用尽所有降级手段后，上下文仍然超出硬上限。

    显式抛出而不是把请求照发出去，是因为后者的失败形态更糟：Provider 返回
    400，错误文本被当成模型回答写进历史，那一轮还会被判定为完整轮次、日后
    参与摘要。与其污染会话，不如在发送前就明确失败。
    """


@dataclass(frozen=True)
class Budget:
    """一次请求的输入 token 预算。

    `trigger_ratio` 取 0.75。留出的 25% 余量同时承担三件事：

    1. 吸收估算误差；
    2. 上下文填到 70~80% 之后模型质量本身开始下降，不只是溢出问题；
    3. **容纳压缩调用自身** —— 摘要要把触发线以下的全部历史重新发出去，这次
       调用必须放得进同一个窗口。主流实现同样在阈值算术里显式扣掉这块空间
       （Claude Code 是固定的 13,000 tokens），因此可以一次压完而不必分批。
    """

    context_window: int
    reserve_output: int
    trigger_ratio: float = 0.75

    def __post_init__(self) -> None:
        if self.context_window <= self.reserve_output:
            raise ValueError("context_window must be larger than reserve_output.")
        if not 0.0 < self.trigger_ratio <= 1.0:
            raise ValueError("trigger_ratio must be in (0, 1].")

    @property
    def limit(self) -> int:
        """输入部分的硬上限：窗口减去为输出预留的部分。"""

        return self.context_window - self.reserve_output

    @property
    def trigger(self) -> int:
        """超过这个值就应当压缩。"""

        return int(self.limit * self.trigger_ratio)


@dataclass(frozen=True)
class ContextBreakdown:
    """一次请求的输入 token 构成，按来源拆分。

    按 role 拆分而不是按「摘要/历史」拆分，因为前者不依赖任何内容约定，而且
    `tool_results` 这一项正好回答降级阶梯最关心的问题：把旧的工具结果裁掉，
    到底能省多少。
    """

    tools: int
    system: int
    user: int
    assistant: int
    tool_results: int

    @property
    def messages(self) -> int:
        return self.system + self.user + self.assistant + self.tool_results

    @property
    def total(self) -> int:
        return self.tools + self.messages

    def share(self, value: int) -> float:
        """某一项占总量的比例，便于判断裁哪里最划算。"""

        return value / self.total if self.total else 0.0

    def format_line(self) -> str:
        """压成一行便于在 trace 中输出。"""

        return (
            f"total={self.total} "
            f"tools={self.tools}({self.share(self.tools):.0%}) "
            f"system={self.system} user={self.user} "
            f"assistant={self.assistant} "
            f"tool_results={self.tool_results}({self.share(self.tool_results):.0%})"
        )


class TokenEstimator:
    """按字符启发式估算输入 token，并用真实用量持续校准。

    校准策略是「只向上修正」：保留观测到的最大低估比例。预算场景下低估比高估
    危险得多 —— 高估只是压缩得早一点，低估会直接撞上下文上限。
    """

    def __init__(self) -> None:
        self._correction = 1.0
        self._samples = 0

    @property
    def correction(self) -> float:
        """当前校正系数，1.0 表示尚未观测到低估。"""

        return self._correction

    @property
    def samples(self) -> int:
        return self._samples

    def count_text(self, text: str) -> int:
        """估算一段文本的 token 数，不含消息级开销。"""

        if not text:
            return 0
        return math.ceil(len(text) / CHARS_PER_TOKEN)

    def count_payload(self, payload: Any) -> int:
        """估算任意可 JSON 序列化结构的 token 数。

        按序列化后的形态计算，因为那才是真正送上网络的内容 —— 字段名、括号和
        引号同样占 token。
        """

        return self.count_text(json.dumps(payload, ensure_ascii=False))

    def breakdown(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
    ) -> ContextBreakdown:
        """按来源拆分一次请求的输入开销。

        `messages` 是已经转成 Provider 字典的消息，`tools` 是工具定义列表 ——
        两者都取实际发送的形态。
        """

        buckets = {"system": 0, "user": 0, "assistant": 0, "tool": 0}
        for message in messages:
            role = message.get("role")
            cost = MESSAGE_OVERHEAD_TOKENS + self.count_payload(message)
            buckets[role if role in buckets else "user"] += cost

        return ContextBreakdown(
            tools=self.count_payload(tools) if tools else 0,
            system=buckets["system"],
            user=buckets["user"],
            assistant=buckets["assistant"],
            tool_results=buckets["tool"],
        )

    def estimate(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
    ) -> int:
        """估算这次请求的输入 token 总量，并应用当前校正系数。"""

        return self.apply_correction(self.breakdown(messages, tools).total)

    def apply_correction(self, raw_estimate: int) -> int:
        """把校正系数应用到已经算好的原始估算上。

        调用方如果已经取过 `breakdown()`，用这个方法即可，不必让 `estimate()`
        把同一批消息再遍历一遍。
        """

        return math.ceil(raw_estimate * self._correction)

    def observe(self, raw_estimate: int, actual: int | None) -> None:
        """用一次真实用量校准。

        `raw_estimate` 必须是**未经校正**的原始估算（即 `breakdown().total`），
        `actual` 是 Provider 返回的 `usage.prompt_tokens`，缺失时忽略本次观测。

        传入已校正的值会让系数停在一个低于真实需求的不动点上：校正后的估算更
        接近真值，算出的比值随之变小，`max` 便再也不会抬高系数。
        """

        if actual is None or raw_estimate <= 0 or actual <= 0:
            return
        self._samples += 1
        self._correction = max(self._correction, actual / raw_estimate)
