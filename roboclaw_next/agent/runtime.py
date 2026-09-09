"""Runtime that executes the RoboClaw Next Agent loop."""

from __future__ import annotations

from typing import Any

from roboclaw_next.agent.budget import TokenEstimator
from roboclaw_next.agent.context_builder import ContextBuilder
from roboclaw_next.agent.message import AgentMessage
from roboclaw_next.agent.session import AgentSession
from roboclaw_next.llm.openai_compatible import LLMProvider
from roboclaw_next.llm.types import LLMResponse
from roboclaw_next.tools import ToolExecutionContext, ToolRegistry, ToolResult


class AgentRuntime:
    """持有模型与工具，并驱动一次 Session 的 Agent 执行循环。"""

    def __init__(
        self,
        provider: LLMProvider,
        tool_registry: ToolRegistry,
        context_builder: ContextBuilder,
        estimator: TokenEstimator,
    ) -> None:
        self.provider = provider
        self.tool_registry = tool_registry
        self.context_builder = context_builder
        # 与 ContextBuilder 共用输入用量估算器，每轮测量并自我校准。
        self.estimator = estimator

    async def run(
        self,
        session: AgentSession,
        *,
        max_iterations: int = 8,
        trace: bool = False,
    ) -> str | None:
        """持续执行模型和工具调用，直到模型给出最终回答。"""

        # max_iterations 用于防止 Agent 进入无限工具调用循环。
        for iteration in range(1, max_iterations + 1):
            tool_definitions = self.tool_registry.definitions()
            if trace:
                print(
                    f"\n[agent] iteration {iteration}: "
                    "send messages and tool definitions to LLM"
                )
                print(f"[agent] available tools: {_tool_names(tool_definitions)}")

            # `await` 会暂停当前协程，直到模型调用完成并返回结果。
            # 如需让请求在后台执行，应显式使用 asyncio.create_task(...)
            context_messages = await self.context_builder.build(
                session,
                tool_definitions,
            )
            payload = [message.to_provider_dict() for message in context_messages]

            # 只遍历一次 payload：breakdown 给出构成，校正系数单独应用。
            breakdown = self.estimator.breakdown(payload, tool_definitions)
            estimated = self.estimator.apply_correction(breakdown.total)

            response = await self.provider.chat_with_retry(
                payload,
                tools=tool_definitions,
            )

            # 更新每一轮上下文长度的估计矫正系数
            self.estimator.observe(
                breakdown.total,
                response.usage.get("prompt_tokens"),
            )

            if trace:
                print(f"[llm] finish_reason: {response.finish_reason}")
                print(
                    "[llm] tool_calls: "
                    f"{[tool_call.name for tool_call in response.tool_calls]}"
                )
                print(_context_usage_line(response, session, context_messages))
                print(f"[est] {breakdown.format_line()}")
                print(
                    _estimate_accuracy_line(
                        estimated,
                        response.usage.get("prompt_tokens"),
                        self.estimator,
                    )
                )
            if not response.has_tool_calls:
                session.append(AgentMessage(role="assistant", content=response.content))
                return response.content

            session.append(
                AgentMessage(
                    role="assistant",
                    content=response.content,
                    tool_calls=response.tool_calls,
                )
            )
            for tool_call in response.tool_calls:
                context = ToolExecutionContext(
                    tool_call_id=tool_call.id,
                    session_id=session.session_id,
                )
                if trace:
                    print(f"[tool] call {tool_call.name} with {tool_call.arguments}")
                try:
                    result = await self.tool_registry.invoke(
                        tool_call.name,
                        tool_call.arguments,
                        context,
                    )
                except Exception as exc:
                    # 即使工具调用抛出 Python 异常，也必须生成配对的 tool
                    # message，否则后续发送给 LLM 的消息序列是不完整的。
                    result = ToolResult(
                        content=f"Tool execution failed: {exc}",
                        is_error=True,
                    )
                if trace:
                    print(f"[tool] result: {result.as_text()}")
                session.append(
                    AgentMessage(
                        role="tool",
                        tool_call_id=tool_call.id,
                        name=tool_call.name,
                        content=result.as_text(),
                    )
                )

        # 轮数耗尽时补一条不带 tool_calls 的 assistant message。否则这一轮的
        # 最后一条是 tool message，_split_turns 会认为 turn 未完成，用户再发
        # 下一条消息时 ContextBuilder 就会直接抛 ValueError。
        session.append(
            AgentMessage(
                role="assistant",
                content=(
                    f"Reached the limit of {max_iterations} tool-calling "
                    "iterations for this turn; no final answer was produced."
                ),
            )
        )
        return None


def _estimate_accuracy_line(
    estimated: int,
    actual: int | None,
    estimator: TokenEstimator,
) -> str:
    """对比事前估算与事后真实用量，用于观察估算器是否收敛。

    `correction` 已经吸收了本次观测，因此这里的 error 反映的是校正之前的偏差；
    随着样本增加它应当趋近于 0 或转为正数。
    """

    if not actual:
        # Provider 未返回 usage，或返回 0：两种情况都无法计算误差。
        return (
            f"[est] estimated={estimated} actual=n/a "
            f"correction={estimator.correction:.2f}"
        )
    error = (estimated - actual) / actual
    return (
        f"[est] estimated={estimated} actual={actual} error={error:+.0%} "
        f"correction={estimator.correction:.2f} samples={estimator.samples}"
    )


def _context_usage_line(
    response: LLMResponse,
    session: AgentSession,
    context_messages: list[AgentMessage],
) -> str:
    """把本次模型调用的上下文用量整理成一行。

    这里只做观测，不参与任何决策。`prompt_tokens` 由 Provider 返回，是本次请求
    的真实输入用量；后续实现 token 预算时，可以用它校准本地估算。

    `cursor` 变化说明这一次 build 触发了摘要，因此可以从这一行看出上下文在
    哪一步被压缩、压缩前后差多少。
    """

    # Provider 未返回 usage 时（例如请求失败）显示 n/a，而不是 None。
    prompt_tokens = response.usage.get("prompt_tokens", "n/a")
    completion_tokens = response.usage.get("completion_tokens", "n/a")
    summary_chars = len(session.summary) if session.summary else 0
    return (
        "[ctx] "
        f"prompt={prompt_tokens} completion={completion_tokens} "
        f"| sent={len(context_messages)}/{len(session.messages)} messages "
        f"| cursor={session.summary_cursor} summary={summary_chars}ch"
    )



def _tool_names(tool_definitions: list[dict[str, Any]]) -> list[str]:
    names: list[str] = []
    for definition in tool_definitions:
        function = definition.get("function", {})
        name = function.get("name")
        if isinstance(name, str):
            names.append(name)
    return names
