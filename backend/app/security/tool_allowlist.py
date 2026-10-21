"""Белый список инструментов агента. Всё остальное запрещено.

Агент только читает данные и формирует инсайт: никаких записей в банковские
системы, отправки сообщений, произвольных HTTP-запросов или shell.
"""

ALLOWED_TOOLS: frozenset[str] = frozenset(
    {
        "get_client_profile",
        "get_counterparty_graph",
        "search_news",
        "search_bank_analytics",
        "get_news_item",
    }
)


class ToolNotAllowed(Exception):
    pass


def check(tool_name: str) -> None:
    if tool_name not in ALLOWED_TOOLS:
        raise ToolNotAllowed(f"Tool '{tool_name}' is not allowed")
