# Мониторинг качества

## Метрики
`GET /api/feedback/metrics` - считаются без LLM по таблицам `insights`, `agent_traces`, `feedback`, `token_usage`
(`observability/metrics.py`, `ml/quality.py`; последние 500 инсайтов):
- Самопроверка: `verified_rate` - доля инсайтов, прошедших проверку; `verified_first_iteration_rate` - с первой
  итерации; `sanitizer_removals_per_insight` - сколько непроверенных пунктов удалено перед показом.
- Связь с источниками: `statements_with_sources_rate` - риски, возможности и выводы AI со ссылкой на источник;
  `why_with_client_features_rate` - пункты «почему важно» с признаками клиента.
- Аналитика банка: `bank_view_rate` - доля инсайтов с позицией Альфа-Банка.
- Обратная связь: `feedback_avg`, `feedback_count`, `negative_feedback_rate` (оценки `POST /api/feedback`),
  разрез по ролям `insights_by_role`.
- Стоимость и скорость: `avg_llm_cost_rub` и `avg_llm_latency_ms` на инсайт, `llm_tokens_in/out` и
  `llm_avg_latency_ms` на вызов LLM.
- Релевантность ленты в проде: доля открытых карточек из топ-5 (нужны события просмотра от фронтенда).

- Бюджет: `llm_spent_today_rub` из `llm_daily_budget_rub` (лимит общего ключа - 500 ₽/день).

Те же метрики - на экране «Качество AI» интерфейса; оценка «полезно / нет» с комментарием - под каждым разбором.

## Процесс
1. Каждый день - `GET /api/feedback/metrics`: падение `verified_rate` или `statements_with_sources_rate`, рост
   `negative_feedback_rate` или цены - повод разобрать трассы (`GET /api/insights/{insight_id}/trace`).
2. Раз в неделю - свежие новости: `eval/run_eval.py collect`, разметка эталона для новых новостей, затем `classify`,
   `ranking --set real`, `insights --set real --judge`. Синтетический набор (`ranking`, `insights`) - регрессия логики.
3. Разбор негативной обратной связи и замечаний судьи: правка промптов, таксономии (`ml/taxonomy.py`) и весов
   ранжирования; изменение принимается, только если eval не ухудшился.
4. Перед каждым релизом: unit-тесты и офлайн-eval (`ranking`, `ranking --set real`, `classify`).
