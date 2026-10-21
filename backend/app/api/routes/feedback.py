from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.db.models import Feedback, User
from app.db.session import get_db
from app.observability.metrics import quality_snapshot
from app.schemas.news import FeedbackIn
from app.security.rbac import get_current_user

router = APIRouter()


@router.post("")
def send_feedback(body: FeedbackIn, user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict:
    db.add(Feedback(insight_id=body.insight_id, user_id=user.user_id, rating=body.rating, comment=body.comment))
    db.commit()
    return {"ok": True}


@router.get("/metrics")
def metrics(user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict:
    return quality_snapshot(db)
