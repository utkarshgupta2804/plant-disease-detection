"""api/schemas.py — Pydantic models for Agri-Watch OJAS"""
from datetime import datetime
from typing import Optional, Any
from pydantic import BaseModel, Field


class SensorReadingOut(BaseModel):
    id: int
    temperature: Optional[float] = None
    humidity: Optional[float] = None
    nitrogen: Optional[float] = None
    phosphorus: Optional[float] = None
    potassium: Optional[float] = None
    tank_level_pct: Optional[float] = None
    concentration_pct: Optional[float] = None
    recorded_at: Optional[datetime] = None  # FIX: was non-Optional, caused 500 on null

    class Config:
        from_attributes = True


class DiseaseResultOut(BaseModel):
    id: int
    disease: str
    confidence: Optional[float] = None
    severity: Optional[str] = None
    treatment: Optional[str] = None
    pump_a: Optional[int] = None
    pump_b: Optional[int] = None
    main_pump: Optional[int] = None
    spray_duration_s: Optional[int] = None
    notes: Optional[str] = None
    image_path: Optional[str] = None
    sensor_context: Optional[dict] = None
    gemini_error: Optional[str] = None
    recorded_at: Optional[datetime] = None  # FIX: was non-Optional, caused 500 on null

    class Config:
        from_attributes = True


class MotorCommandIn(BaseModel):
    pump_a: bool = Field(default=False)
    pump_b: bool = Field(default=False)
    main_pump: bool = Field(default=True)
    duration_sec: int = Field(default=10, ge=1, le=300)
    trigger: str = Field(default="manual")


class MotorEventOut(BaseModel):
    id: int
    event_type: str
    trigger: Optional[str] = None
    pump_a: Optional[bool] = None
    pump_b: Optional[bool] = None
    main_pump: Optional[bool] = None
    duration_sec: Optional[int] = None
    recorded_at: Optional[datetime] = None  # FIX: was non-Optional, caused 500 on null

    class Config:
        from_attributes = True


class LogOut(BaseModel):
    id: int
    level: str
    message: str
    source: Optional[str] = None
    extra: Optional[Any] = None
    created_at: Optional[datetime] = None  # FIX: was non-Optional, caused 500 on null

    class Config:
        from_attributes = True


class ModeIn(BaseModel):
    mode: str = Field(..., pattern="^(auto|manual)$")


class ModeOut(BaseModel):
    mode: str
    updated_at: Optional[datetime] = None