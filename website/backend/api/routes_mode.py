"""api/routes_mode.py — GET/POST /mode/"""
import logging
from datetime import datetime
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from db.database import get_db
from db.models import SystemConfig, SystemLog
from api.schemas import ModeIn, ModeOut

log = logging.getLogger(__name__)
router = APIRouter()

def _get_or_create(db):
    cfg = db.query(SystemConfig).filter(SystemConfig.key=="mode").first()
    if not cfg:
        cfg = SystemConfig(key="mode",value="auto"); db.add(cfg); db.commit(); db.refresh(cfg)
    return cfg

@router.get("/", response_model=ModeOut)
def get_mode(db:Session=Depends(get_db)):
    cfg=_get_or_create(db); return ModeOut(mode=cfg.value,updated_at=cfg.updated_at)

@router.post("/", response_model=ModeOut)
def set_mode(body:ModeIn, db:Session=Depends(get_db)):
    cfg=_get_or_create(db); old=cfg.value; cfg.value=body.mode; cfg.updated_at=datetime.utcnow()
    db.add(SystemLog(level="INFO",message=f"Mode: {old}→{body.mode}",source="routes_mode")); db.commit()
    return ModeOut(mode=body.mode,updated_at=cfg.updated_at)
