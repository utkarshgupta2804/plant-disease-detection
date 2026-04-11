"""api/routes_sensors.py — GET /sensors/*"""
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy import func
from sqlalchemy.orm import Session

from db.database import get_db
from db.models import SensorReading
from api.schemas import SensorReadingOut
from config import settings

router = APIRouter()

SENSOR_FIELDS = [
    "temperature", "humidity", "nitrogen", "phosphorus",
    "potassium", "tank_level_pct", "concentration_pct",
]

THRESHOLDS = {
    "temperature":       (settings.TEMP_MIN,          settings.TEMP_MAX),
    "humidity":          (settings.HUMIDITY_MIN,      settings.HUMIDITY_MAX),
    "tank_level_pct":    (settings.TANK_LEVEL_MIN,    100.0),
    "concentration_pct": (settings.CONCENTRATION_MIN, 100.0),
}


def _utcnow() -> datetime:
    # FIX: always produce a naive UTC datetime for consistent SQLite comparisons.
    # datetime.utcnow() is deprecated in 3.12+; datetime.now(utc).replace(tzinfo=None)
    # gives the same naive value without the deprecation warning.
    return datetime.now(timezone.utc).replace(tzinfo=None)


@router.get("/status")
def get_status(request: Request, db: Session = Depends(get_db)):
    """
    Combined live status endpoint.
    Reads cached serial state only — never blocks on NodeMCU hardware.
    """
    latest: Optional[SensorReading] = (
        db.query(SensorReading)
        .order_by(SensorReading.id.desc())
        .first()
    )

    sensor_data: dict = {}
    if latest:
        sensor_data = {
            "temperature":       latest.temperature,
            "humidity":          latest.humidity,
            "nitrogen":          latest.nitrogen,
            "phosphorus":        latest.phosphorus,
            "potassium":         latest.potassium,
            "tank_level_pct":    latest.tank_level_pct,
            "concentration_pct": latest.concentration_pct,
            "recorded_at": (
                latest.recorded_at.isoformat() if latest.recorded_at else None
            ),
        }

    alerts: list[dict] = []
    for sensor, (lo, hi) in THRESHOLDS.items():
        val = sensor_data.get(sensor)
        if val is None:
            continue
        if val < lo:
            alerts.append({"sensor": sensor, "value": val,
                            "type": "below_threshold", "threshold": lo})
        elif val > hi:
            alerts.append({"sensor": sensor, "value": val,
                            "type": "above_threshold", "threshold": hi})

    # Read cache only — never call sb.send() inline
    sb = getattr(request.app.state, "serial_bridge", None)
    serial_connected = sb.is_connected() if sb else False
    serial_status    = sb.get_status()   if sb else {}

    return {
        "ok":               True,
        "has_reading":      latest is not None,
        "sensor_data":      sensor_data,
        "alerts":           alerts,
        "alert_count":      len(alerts),
        "serial_connected": serial_connected,
        "serial_status":    serial_status,
    }


@router.get("/latest", response_model=Optional[SensorReadingOut])
def get_latest(db: Session = Depends(get_db)):
    return db.query(SensorReading).order_by(SensorReading.id.desc()).first()


@router.get("/history", response_model=list[SensorReadingOut])
def get_history(
    limit:  int = Query(100, ge=1,  le=1000),
    offset: int = Query(0,   ge=0),
    hours:  int = Query(24,  ge=1,  le=720),
    db: Session = Depends(get_db),
):
    # FIX: use _utcnow() so the naive datetime matches what SQLite stores
    since = _utcnow() - timedelta(hours=hours)
    return (
        db.query(SensorReading)
        .filter(SensorReading.recorded_at >= since)
        .order_by(SensorReading.recorded_at.desc())
        .offset(offset)
        .limit(limit)
        .all()
    )


@router.get("/stats")
def get_stats(hours: int = Query(24, ge=1, le=720), db: Session = Depends(get_db)):
    since = _utcnow() - timedelta(hours=hours)
    stats: dict = {}
    for field in SENSOR_FIELDS:
        col = getattr(SensorReading, field)
        row = (
            db.query(
                func.min(col).label("min"),
                func.avg(col).label("avg"),
                func.max(col).label("max"),
                func.count(col).label("count"),
            )
            .filter(SensorReading.recorded_at >= since)
            .filter(col.isnot(None))
            .first()
        )
        stats[field] = {
            "min":   round(row.min, 2) if row.min is not None else None,
            "avg":   round(row.avg, 2) if row.avg is not None else None,
            "max":   round(row.max, 2) if row.max is not None else None,
            "count": row.count,
        }
    return {"hours": hours, "stats": stats}


@router.get("/alerts")
def get_alerts(db: Session = Depends(get_db)):
    latest = db.query(SensorReading).order_by(SensorReading.id.desc()).first()
    if not latest:
        return {"alerts": [], "latest": None}
    alerts: list[dict] = []
    for sensor, (lo, hi) in THRESHOLDS.items():
        val = getattr(latest, sensor)
        if val is None:
            continue
        if val < lo:
            alerts.append({"sensor": sensor, "value": val,
                            "type": "below_threshold", "threshold": lo})
        elif val > hi:
            alerts.append({"sensor": sensor, "value": val,
                            "type": "above_threshold", "threshold": hi})
    return {"alerts": alerts, "count": len(alerts), "latest_at": latest.recorded_at}