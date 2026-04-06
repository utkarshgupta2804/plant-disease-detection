"""api/routes_camera.py — GET /camera/stream-url|latest"""
from datetime import datetime
from pathlib import Path
from fastapi import APIRouter
from config import settings

router = APIRouter()
CAPTURE_PATH = "/tmp/plant_capture.jpg"

@router.get("/stream-url")
def get_stream_url():
    return {"url":f"http://{settings.PI_HOST}:8080/stream","host":settings.PI_HOST,"port":8080,"format":"MJPEG","note":"libcamera-vid -t 0 --inline --listen -o tcp://0.0.0.0:8080"}

@router.get("/latest")
def latest_capture():
    p=Path(CAPTURE_PATH)
    if not p.exists(): return {"available":False,"path":CAPTURE_PATH}
    return {"available":True,"path":str(p),"size_kb":round(p.stat().st_size/1024,1),"captured_at":datetime.fromtimestamp(p.stat().st_mtime).isoformat()}
