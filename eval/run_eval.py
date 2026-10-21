"""Оценка качества на golden set (критерий 05: устойчивость на невиданных новостях).

Формат golden_set.jsonl, одна запись на строку:
{"client_id": "...", "news_id": "...", "expected_relevant": true, "must_mention": ["ставк"]}

TODO: реализовать прогон через orchestrator.run и подсчёт метрик
(релевантность ленты, наличие ссылок на источники, прохождение verifier).
"""
import json
import sys
from pathlib import Path


def main(path: str = "eval/golden_set.jsonl") -> None:
    p = Path(path)
    if not p.exists():
        print(f"{path} not found")
        sys.exit(1)
    rows = [json.loads(line) for line in p.read_text(encoding="utf-8").splitlines() if line.strip()]
    print(f"{len(rows)} cases loaded (runner not implemented)")


if __name__ == "__main__":
    main(*sys.argv[1:])
