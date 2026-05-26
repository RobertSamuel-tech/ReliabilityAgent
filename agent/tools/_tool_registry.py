"""In-process tool call registry keyed by trace_id."""
from collections import defaultdict

_registry: dict[str, list[str]] = defaultdict(list)


def record_tool_call(trace_id: str, tool_name: str) -> None:
    if trace_id:
        _registry[trace_id].append(tool_name)


def get_tool_count(trace_id: str) -> int:
    return len(_registry.get(trace_id, []))


def get_tool_names(trace_id: str) -> list[str]:
    return list(_registry.get(trace_id, []))
