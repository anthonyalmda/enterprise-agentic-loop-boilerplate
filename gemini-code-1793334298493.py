"""
Anthropic Agentic Loop featuring:
- 3-Breakpoint Ephemeral Prompt Caching (Tools + Static System + Dynamic Turn History)
- Parallel non-blocking tool execution via asyncio.to_thread
- PII-safe error boundary
"""
import asyncio
import json
from typing import Any, Callable, Dict, List
from anthropic import AsyncAnthropic

MAX_TOOL_OUTPUT_CHARS = 60_000


async def _execute_single_tool(
    name: str, args: Dict[str, Any], registry: Dict[str, Callable]
) -> Dict[str, Any]:
    tool_fn = registry.get(name)
    if not tool_fn:
        return {"type": "tool_result", "is_error": True, "content": f"Unknown tool: {name}"}
    try:
        raw_output = await asyncio.to_thread(tool_fn, **args)
        serialized = json.dumps(raw_output, ensure_ascii=False, default=str)
        if len(serialized) > MAX_TOOL_OUTPUT_CHARS:
            serialized = serialized[:MAX_TOOL_OUTPUT_CHARS] + "... [TRUNCATED]"
        return {"type": "tool_result", "is_error": False, "content": serialized}
    except Exception as exc:
        # Log only exception class name in production to avoid leaking PII in stack traces
        return {"type": "tool_result", "is_error": True, "content": f"ToolError: {type(exc).__name__}"}


async def run_agent_turn(
    client: AsyncAnthropic,
    *,
    static_system_prompt: str,
    dynamic_context: str,
    tools_schema: List[Dict[str, Any]],
    tool_registry: Dict[str, Callable],
    messages: List[Dict[str, Any]],
    model: str = "claude-sonnet-4-20250514",
) -> str:
    # Breakpoint 1: Cache the entire tool catalog schema on the last tool definition
    cached_tools = [dict(t) for t in tools_schema]
    if cached_tools:
        cached_tools[-1]["cache_control"] = {"type": "ephemeral"}

    # Breakpoint 2: Cache static rules while keeping dynamic conversation context uncached
    system_blocks = [
        {"type": "text", "text": static_system_prompt, "cache_control": {"type": "ephemeral"}},
        {"type": "text", "text": f"Active Context:\n{dynamic_context}"},
    ]

    while True:
        response = await client.messages.create(
            model=model,
            max_tokens=4096,
            system=system_blocks,
            tools=cached_tools,
            messages=messages,
        )

        messages.append({"role": "assistant", "content": response.content})

        if response.stop_reason != "tool_use":
            return "".join(block.text for block in response.content if block.type == "text")

        tool_calls = [b for b in response.content if b.type == "tool_use"]
        results = await asyncio.gather(
            *(_execute_single_tool(tc.name, tc.input, tool_registry) for tc in tool_calls)
        )

        tool_result_blocks = [
            {
                "type": "tool_result",
                "tool_use_id": tc.id,
                "content": res["content"],
                "is_error": res["is_error"],
            }
            for tc, res in zip(tool_calls, results)
        ]
        # Breakpoint 3: Cache conversation prefix across multi-step tool rounds
        tool_result_blocks[-1]["cache_control"] = {"type": "ephemeral"}
        messages.append({"role": "user", "content": tool_result_blocks})