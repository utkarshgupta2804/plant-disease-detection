"""api/schemas.py — Pydantic models for Agri-Watch OJAS"""
from datetime import datetime
from typing import Optional, Any
from pydantic import BaseModel, Field


class SensorReadingOut(BaseModel):
    id: int
    temperature: Optional[float]
    humidity: Optional[float]
    nitrogen: Optional[float]
    phosphorus: Optional[float]
    potassium: Optional[float]
    tank_level_pct: Optional[float]
    concentration_pct: Optional[float]
    recorded_at: datetime
    class Config: from_attributes = True


class DiseaseResultOut(BaseModel):
    id: int
    disease: str
    confidence: Optional[float]
    severity: Optional[str]
    treatment: Optional[str]
    pump_a: Optional[int]
    pump_b: Optional[int]
    main_pump: Optional[int]
    spray_duration_s: Optional[int]
    notes: Optional[str]
    image_path: Optional[str]
    sensor_context: Optional[dict]
    gemini_error: Optional[str]
    recorded_at: datetime
    class Config: from_attributes = True


class MotorCommandIn(BaseModel):
    pump_a: bool = Field(default=False)
    pump_b: bool = Field(default=False)
    main_pump: bool = Field(default=True)
    duration_sec: int = Field(default=10, ge=1, le=300)
    trigger: str = Field(default="manual")


class MotorEventOut(BaseModel):
    id: int
    event_type: str
    trigger: Optional[str]
    pump_a: Optional[bool]
    pump_b: Optional[bool]
    main_pump: Optional[bool]
    duration_sec: Optional[int]
    recorded_at: datetime
    class Config: from_attributes = True


class LogOut(BaseModel):
    id: int
    level: str
    message: str
    source: Optional[str]
    extra: Optional[Any]
    created_at: datetime
    class Config: from_attributes = True


class ModeIn(BaseModel):
    mode: str = Field(..., pattern="^(auto|manual)$")


class ModeOut(BaseModel):
    mode: str
    updated_at: Optional[datetime]
