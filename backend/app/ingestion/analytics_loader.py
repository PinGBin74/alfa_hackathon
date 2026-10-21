"""Загрузка PDF-материалов Альфа-Банка (Приложение 2) -> analytics_docs + analytics_chunks."""
import hashlib
from pathlib import Path

from pypdf import PdfReader
from sqlalchemy.orm import Session

from app.db.models import AnalyticsChunk, AnalyticsDoc

CHUNK_CHARS = 1500


def _chunks(text: str, size: int = CHUNK_CHARS) -> list[str]:
    paras, out, cur = [p.strip() for p in text.split("\n\n") if p.strip()], [], ""
    for p in paras:
        if len(cur) + len(p) > size and cur:
            out.append(cur)
            cur = ""
        cur += p + "\n\n"
    if cur.strip():
        out.append(cur.strip())
    return out


def load_dir(db: Session, directory: str = "data/bank_analytics") -> int:
    count = 0
    for pdf in sorted(Path(directory).glob("*.pdf")):
        doc_id = hashlib.sha1(pdf.name.encode()).hexdigest()[:12]
        if db.get(AnalyticsDoc, doc_id):
            continue
        db.add(AnalyticsDoc(doc_id=doc_id, title=pdf.stem, file_path=str(pdf)))
        reader = PdfReader(str(pdf))
        for page_no, page in enumerate(reader.pages, start=1):
            for ch in _chunks(page.extract_text() or ""):
                db.add(AnalyticsChunk(doc_id=doc_id, page=page_no, text=ch))
        count += 1
    db.commit()
    return count
