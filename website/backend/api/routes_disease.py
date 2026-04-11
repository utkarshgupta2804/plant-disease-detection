"""api/routes_disease.py — GET /disease/*"""
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func
from sqlalchemy.orm import Session

from db.database import get_db
from db.models import DiseaseResult
from api.schemas import DiseaseResultOut

router = APIRouter()


def _utcnow() -> datetime:
    # FIX: naive UTC datetime for consistent SQLite comparisons
    return datetime.now(timezone.utc).replace(tzinfo=None)


@router.get("/latest", response_model=Optional[DiseaseResultOut])
def get_latest(db: Session = Depends(get_db)):
    return db.query(DiseaseResult).order_by(DiseaseResult.id.desc()).first()


@router.get("/predictions", response_model=list[DiseaseResultOut])
def get_predictions(
    limit:    int = Query(50,  ge=1, le=500),
    offset:   int = Query(0,   ge=0),
    hours:    int = Query(168, ge=1, le=2160),
    severity: Optional[str] = None,
    db: Session = Depends(get_db),
):
    # FIX: was datetime.utcnow() — naive/aware mismatch silently returned 0 rows
    since = _utcnow() - timedelta(hours=hours)
    q = db.query(DiseaseResult).filter(DiseaseResult.recorded_at >= since)
    if severity:
        q = q.filter(DiseaseResult.severity == severity)
    return q.order_by(DiseaseResult.id.desc()).offset(offset).limit(limit).all()


@router.get("/summary")
def get_summary(
    hours: int = Query(168, ge=1, le=2160),
    db: Session = Depends(get_db),
):
    # FIX: same naive datetime fix
    since = _utcnow() - timedelta(hours=hours)
    by_d = (
        db.query(DiseaseResult.disease, func.count(DiseaseResult.id).label("count"))
        .filter(DiseaseResult.recorded_at >= since)
        .group_by(DiseaseResult.disease)
        .all()
    )
    by_s = (
        db.query(DiseaseResult.severity, func.count(DiseaseResult.id).label("count"))
        .filter(DiseaseResult.recorded_at >= since)
        .group_by(DiseaseResult.severity)
        .all()
    )
    return {
        "hours":       hours,
        "by_disease":  [{"disease":  r.disease,  "count": r.count} for r in by_d],
        "by_severity": [{"severity": r.severity, "count": r.count} for r in by_s],
    }


@router.get("/{result_id}", response_model=DiseaseResultOut)
def get_by_id(result_id: int, db: Session = Depends(get_db)):
    row = db.query(DiseaseResult).filter(DiseaseResult.id == result_id).first()
    if not row:
        raise HTTPException(404, "Not found")
    return row


@router.delete("/{result_id}")
def delete_result(result_id: int, db: Session = Depends(get_db)):
    row = db.query(DiseaseResult).filter(DiseaseResult.id == result_id).first()
    if not row:
        raise HTTPException(404, "Not found")
    db.delete(row)
    db.commit()
    return {"deleted": result_id}