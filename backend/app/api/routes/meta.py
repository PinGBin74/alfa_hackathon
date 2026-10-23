"""Справочники для интерфейса: названия факторов, классов ОКВЭД2 и ролей (единый источник - таксономия)."""
from fastapi import APIRouter

from app.agent.context import PRODUCT_FLAGS, ROLE_NAMES
from app.ml import taxonomy

router = APIRouter()


@router.get("")
def meta() -> dict:
    return {
        "factors": {code: f.label for code, f in taxonomy.FACTORS.items()},
        "okved2": taxonomy.OKVED2_CLASSES,
        "roles": ROLE_NAMES,
        "products": {attr: {"feature": code, "label": label} for attr, (code, label) in PRODUCT_FLAGS.items()},
    }
