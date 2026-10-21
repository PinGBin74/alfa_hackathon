"""Самопроверка: полнота, непротиворечивость, обоснованность."""
from app.agent.state import AgentState


def verify(state: AgentState) -> dict:
    """Детерминированные проверки. LLM-проверку (противоречия, фактология) добавить отдельным шагом."""
    issues: list[str] = []
    d = state.draft or {}
    known = state.source_ids()

    for fact in d.get("what_happened", {}).get("confirmed_facts", []):
        if fact.get("source_id") not in known:
            issues.append(f"fact without known source: {fact.get('source_id')}")

    for bp in d.get("bank_position", []):
        if not any(sid.startswith(f"bank:{bp.get('analytics_doc_id')}") for sid in known):
            issues.append(f"bank_position references unretrieved doc: {bp.get('analytics_doc_id')}")

    if not d.get("why_it_matters"):
        issues.append("why_it_matters is empty (no link to client features)")
    if not d.get("ai_inference") and not d.get("bank_position"):
        issues.append("no inference or bank position")

    result = {"passed": not issues, "issues": issues, "iterations": state.iterations}
    state.verification = result
    return result
