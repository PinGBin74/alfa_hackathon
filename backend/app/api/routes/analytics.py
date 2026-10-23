"""Аналитика Альфа-Банка как первоисточник: документы, страница с извлечёнными позициями и сам PDF.

На эти ссылки ведут пункты «Позиция банка» (quote_ref = bank:<doc_id>:<page>) - пользователь видит, на какой
странице и какой дословной цитате основан вывод (критерии 02, 03, 10).
"""
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db.models import AnalyticsChunk, AnalyticsDoc, User
from app.db.session import get_db
from app.ml import bank_positions
from app.security.rbac import get_current_user

router = APIRouter()


def _docs_meta() -> dict[str, dict]:
    return {d["doc_id"]: d for d in bank_positions.load_positions_data().get("documents", [])}


def _doc_out(row: AnalyticsDoc | None, meta: dict, positions: int) -> dict:
    return {
        "doc_id": row.doc_id if row else meta.get("doc_id"),
        "title": (row.title if row else None) or meta.get("title"),
        "date": (row.published_at.date().isoformat() if row and row.published_at else None) or meta.get("date"),
        "stale": bool(meta.get("stale")), "stale_reason": meta.get("stale_reason"),
        "factors": (row.topics if row else None) or meta.get("factors") or [],
        "positions": positions, "has_file": row is not None and _pdf_path(row) is not None,
    }


def _pdf_path(row: AnalyticsDoc) -> Path | None:
    """Только файлы из папки аналитики: имя из БД, каталог - свой (без обхода путей)."""
    if not row.file_path:
        return None
    base = (Path(get_settings().data_dir) / "bank_analytics").resolve()
    path = (base / Path(row.file_path).name).resolve()
    return path if path.parent == base and path.suffix.lower() == ".pdf" and path.exists() else None


@router.get("")
def list_docs(user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> list[dict]:
    meta = _docs_meta()
    counts: dict[str, int] = {}
    for p in bank_positions.load_positions():
        counts[p["doc_id"]] = counts.get(p["doc_id"], 0) + 1
    rows = db.query(AnalyticsDoc).all()
    docs = [_doc_out(r, meta.get(r.doc_id, {}), counts.get(r.doc_id, 0)) for r in rows]
    return sorted(docs, key=lambda d: d["date"] or "", reverse=True)


@router.get("/{doc_id}/pages/{page}")
def get_page(doc_id: str, page: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict:
    """Страница материала: позиции банка с дословными цитатами и текст страницы (фрагменты PDF)."""
    row = db.get(AnalyticsDoc, doc_id)
    meta = _docs_meta().get(doc_id, {})
    if row is None and not meta:
        raise HTTPException(404, "Document not found")
    positions = [p for p in bank_positions.load_positions() if p["doc_id"] == doc_id and p["page"] == page]
    chunks = [t for (t,) in db.query(AnalyticsChunk.text).filter_by(doc_id=doc_id, page=page).order_by(AnalyticsChunk.chunk_id)]
    if not positions and not chunks:
        raise HTTPException(404, "Page not found")
    newer = {p["position_id"]: p for p in bank_positions.load_positions()}
    return {
        "source_id": f"bank:{doc_id}:{page}", "page": page,
        "document": _doc_out(row, meta, len(positions)),
        "positions": [{
            "position_id": p["position_id"], "thesis": p["thesis"], "quote": p["quote"], "factors": p.get("factors") or [],
            "forecast": p.get("forecast"), "horizon_passed": bool(p.get("horizon_passed")),
            "superseded_by": ({"position_id": p["superseded_by"], "doc_id": newer[p["superseded_by"]]["doc_id"],
                               "page": newer[p["superseded_by"]]["page"], "thesis": newer[p["superseded_by"]]["thesis"],
                               "date": newer[p["superseded_by"]].get("date")}
                              if p.get("superseded_by") in newer else None),
        } for p in positions],
        "text": "\n\n".join(chunks),
    }


@router.get("/{doc_id}/file")
def get_file(doc_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    row = db.get(AnalyticsDoc, doc_id)
    path = _pdf_path(row) if row else None
    if path is None:
        raise HTTPException(404, "File not found")
    return FileResponse(path, media_type="application/pdf", filename=path.name, content_disposition_type="inline")
