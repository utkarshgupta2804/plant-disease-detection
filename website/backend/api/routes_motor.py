"""api/routes_motor.py — POST /motor/on|off, GET /motor/status|history|stats"""
import logging
from datetime import datetime, timedelta
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import func
from sqlalchemy.orm import Session
from db.database import get_db
from db.models import MotorEvent, SystemConfig, SystemLog
from api.schemas import MotorCommandIn, MotorEventOut

log = logging.getLogger(__name__)
router = APIRouter()

_motor_state = {"running":False,"started_at":None,"pump_a":False,"pump_b":False,"main_pump":False}

def _get_serial(request): return getattr(request.app.state,"serial_bridge",None)
def _get_mode(db):
    cfg = db.query(SystemConfig).filter(SystemConfig.key=="mode").first()
    return cfg.value if cfg else "auto"
def _send(sb, cmd, state):
    if sb: sb.send({"cmd":cmd,"state":state})

@router.post("/on")
def motor_on(cmd:MotorCommandIn, request:Request, db:Session=Depends(get_db)):
    if _get_mode(db)!="manual": raise HTTPException(403,"Switch to manual mode first.")
    if _motor_state["running"]: return {"status":"already_running","started_at":_motor_state["started_at"]}
    sb = _get_serial(request)
    if cmd.pump_a:    _send(sb,"PUMP_A",1)
    if cmd.pump_b:    _send(sb,"PUMP_B",1)
    if cmd.main_pump: _send(sb,"MAIN_PUMP",1)
    if sb:
        sb.send({"cmd":"OLED","line1":"Manual Spray","line2":f"Dur:{cmd.duration_sec}s","line3":f"PA:{int(cmd.pump_a)} PB:{int(cmd.pump_b)}","line4":f"Main:{int(cmd.main_pump)}"})
        sb.send({"cmd":"LED","color":"yellow"})
    _motor_state.update({"running":True,"started_at":datetime.utcnow().isoformat(),"pump_a":cmd.pump_a,"pump_b":cmd.pump_b,"main_pump":cmd.main_pump})
    db.add(MotorEvent(event_type="on",trigger=cmd.trigger,pump_a=cmd.pump_a,pump_b=cmd.pump_b,main_pump=cmd.main_pump,duration_sec=cmd.duration_sec))
    db.add(SystemLog(level="INFO",message=f"Motor ON manual PA={cmd.pump_a} PB={cmd.pump_b} Main={cmd.main_pump} {cmd.duration_sec}s",source="routes_motor"))
    db.commit()
    return {"status":"motor_on","pump_a":cmd.pump_a,"pump_b":cmd.pump_b,"main_pump":cmd.main_pump,"duration_sec":cmd.duration_sec,"started_at":_motor_state["started_at"]}

@router.post("/off")
def motor_off(request:Request, db:Session=Depends(get_db)):
    sb = _get_serial(request)
    for c in ["PUMP_A","PUMP_B","MAIN_PUMP"]: _send(sb,c,0)
    if sb:
        sb.send({"cmd":"LED","color":"green"})
        sb.send({"cmd":"OLED","line1":"System Idle","line2":"All pumps OFF","line3":"","line4":""})
    _motor_state.update({"running":False,"started_at":None,"pump_a":False,"pump_b":False,"main_pump":False})
    db.add(MotorEvent(event_type="off",trigger="manual",pump_a=False,pump_b=False,main_pump=False))
    db.add(SystemLog(level="INFO",message="Motor OFF manual",source="routes_motor"))
    db.commit()
    return {"status":"motor_off"}

@router.get("/status")
def motor_status(request:Request, db:Session=Depends(get_db)):
    sb = _get_serial(request)
    return {**_motor_state,"mode":_get_mode(db),"serial_connected":sb.is_connected() if sb else False,"nodemcu":sb.get_status() if sb else {}}

@router.get("/history", response_model=list[MotorEventOut])
def motor_history(limit:int=Query(50,ge=1,le=500), offset:int=Query(0,ge=0), db:Session=Depends(get_db)):
    return db.query(MotorEvent).order_by(MotorEvent.id.desc()).offset(offset).limit(limit).all()

@router.get("/stats")
def motor_stats(db:Session=Depends(get_db)):
    now=datetime.utcnow(); today=now.replace(hour=0,minute=0,second=0,microsecond=0); week=now-timedelta(days=7)
    def cnt(since): return db.query(func.count(MotorEvent.id)).filter(MotorEvent.event_type.in_(["on","auto_on"])).filter(MotorEvent.recorded_at>=since).scalar() or 0
    def dur(since): return db.query(func.sum(MotorEvent.duration_sec)).filter(MotorEvent.event_type.in_(["on","auto_on"])).filter(MotorEvent.main_pump==True).filter(MotorEvent.recorded_at>=since).scalar() or 0
    return {"today":{"sessions":cnt(today),"spray_seconds":dur(today)},"this_week":{"sessions":cnt(week),"spray_seconds":dur(week)}}
