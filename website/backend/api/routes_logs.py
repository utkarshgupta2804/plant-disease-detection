"""api/routes_logs.py — GET/POST/DELETE /logs/*"""
import csv, io
from datetime import datetime, timedelta
from typing import Optional
from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session
from db.database import get_db
from db.models import SystemLog
from api.schemas import LogOut

router = APIRouter()

@router.get("/", response_model=list[LogOut])
def get_logs(limit:int=Query(100,ge=1,le=1000), offset:int=Query(0,ge=0), level:Optional[str]=None, source:Optional[str]=None, hours:int=Query(24,ge=1,le=720), search:Optional[str]=None, db:Session=Depends(get_db)):
    since = datetime.utcnow()-timedelta(hours=hours)
    q = db.query(SystemLog).filter(SystemLog.created_at>=since)
    if level:  q = q.filter(SystemLog.level==level.upper())
    if source: q = q.filter(SystemLog.source.ilike(f"%{source}%"))
    if search: q = q.filter(SystemLog.message.ilike(f"%{search}%"))
    return q.order_by(SystemLog.id.desc()).offset(offset).limit(limit).all()

@router.get("/export")
def export_logs(hours:int=Query(24,ge=1,le=720), level:Optional[str]=None, db:Session=Depends(get_db)):
    since = datetime.utcnow()-timedelta(hours=hours)
    q = db.query(SystemLog).filter(SystemLog.created_at>=since)
    if level: q = q.filter(SystemLog.level==level.upper())
    rows = q.order_by(SystemLog.created_at.asc()).all()
    def gen():
        buf=io.StringIO(); w=csv.writer(buf); w.writerow(["id","level","source","message","created_at"]); yield buf.getvalue()
        for r in rows:
            buf=io.StringIO(); w=csv.writer(buf); w.writerow([r.id,r.level,r.source or "",r.message,r.created_at.isoformat()]); yield buf.getvalue()
    fn=f"ojas_logs_{datetime.utcnow().strftime('%Y%m%d_%H%M')}.csv"
    return StreamingResponse(gen(),media_type="text/csv",headers={"Content-Disposition":f"attachment; filename={fn}"})

@router.post("/", response_model=LogOut, status_code=201)
def create_log(level:str, message:str, source:Optional[str]=None, db:Session=Depends(get_db)):
    entry=SystemLog(level=level.upper(),message=message,source=source); db.add(entry); db.commit(); db.refresh(entry); return entry

@router.delete("/clear")
def clear_logs(days:int=Query(7,ge=1,le=365), db:Session=Depends(get_db)):
    cutoff=datetime.utcnow()-timedelta(days=days); deleted=db.query(SystemLog).filter(SystemLog.created_at<cutoff).delete(); db.commit()
    return {"deleted":deleted,"cutoff":cutoff.isoformat()}
