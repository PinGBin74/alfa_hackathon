# Промпт планировщика (черновик)

Дано: тип события, краткий профиль клиента.
Нужно: список шагов (инструмент + зачем) из разрешённых: get_client_profile, get_counterparty_graph,
get_news_item, search_news, search_bank_analytics. Вернуть JSON `{"plan": [{"tool": "...", "why": "..."}]}`.
