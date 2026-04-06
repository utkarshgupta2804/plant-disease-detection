"""
db/models.py — SQLAlchemy ORM models for Agri-Watch OJAS
Hardware: RPi 4 + NodeMCU v3 ESP8266

Sensor columns match rpi/main.py CSV_HEADERS exactly:
  temperature_c → temperature, humidity_pct → humidity,
  N_mgkg → nitrogen, P_mgkg → phosphorus, K_mgkg → potassium,
  tank_level_pct → tank_level_pct (HC-SR04 US1 · GPIO23/24),
  concentration_pct → concentration_pct (HC-SR04 US2 · GPIO25/8)

Motor columns match NodeMCU serial commands:
  pump_a    → L298N IN1 (D3/GPIO0)
  pump_b    → L298N IN3 (D7/GPIO13)
  main_pump → Relay IN  (D4/GPIO2, active-LOW)
"""

from datetime import datetime
from sqlalchemy import (
    Column, Integer, Float, String, Text, Boolean, DateTime, JSON, Index,
)
from db.database import Base


# =============================================================================
# SENSOR READINGS
# =============================================================================
class SensorReading(Base):
    __tablename__ = "sensor_readings"

    id = Column(Integer, primary_key=True, index=True)

    # DHT22 — GPIO4 / Pin 7 (1-Wire, 10kΩ pull-up to 3.3V)
    temperature = Column(Float, nullable=True)   # °C
    humidity    = Column(Float, nullable=True)   # %

    # NPK RS485 — GPIO14/15 via MAX485, DE/RE on GPIO17
    nitrogen   = Column(Float, nullable=True)    # mg/kg
    phosphorus = Column(Float, nullable=True)    # mg/kg
    potassium  = Column(Float, nullable=True)    # mg/kg

    # HC-SR04 Ultrasonic Sensors (5V supply, ECHO via 1kΩ+2kΩ voltage divider)
    # US1: TRIG=GPIO23/Pin16, ECHO=GPIO24/Pin18
    tank_level_pct    = Column(Float, nullable=True)   # % full

    # US2: TRIG=GPIO25/Pin22, ECHO=GPIO8/Pin24
    concentration_pct = Column(Float, nullable=True)   # % mix

    pi_timestamp = Column(Float,    nullable=True)
    recorded_at  = Column(DateTime, default=datetime.utcnow, index=True)


# =============================================================================
# DISEASE DETECTION RESULTS (from Gemini 1.5 Flash Vision API)
# =============================================================================
class DiseaseResult(Base):
    __tablename__ = "disease_results"

    id = Column(Integer, primary_key=True, index=True)

    disease    = Column(String(128), nullable=False, default="unknown")
    confidence = Column(Float,       nullable=True)       # 0.0–1.0
    severity   = Column(String(32),  nullable=True)       # none|mild|moderate|severe
    treatment  = Column(Text,        nullable=True)

    # NodeMCU pump/relay commands issued for this detection
    pump_a           = Column(Integer, nullable=True)    # 0|1 → L298N IN1 (D3)
    pump_b           = Column(Integer, nullable=True)    # 0|1 → L298N IN3 (D7)
    main_pump        = Column(Integer, nullable=True)    # 0|1 → Relay IN (D4, active-LOW)
    spray_duration_s = Column(Integer, nullable=True)   # seconds

    notes        = Column(Text,        nullable=True)
    image_path   = Column(String(256), nullable=True)    # /tmp/plant_capture.jpg
    sensor_context  = Column(JSON,     nullable=True)    # snapshot of sensor_data dict
    gemini_error    = Column(String(256), nullable=True)

    recorded_at = Column(DateTime, default=datetime.utcnow, index=True)


# =============================================================================
# MOTOR EVENTS (spray sessions)
# =============================================================================
class MotorEvent(Base):
    __tablename__ = "motor_events"

    id = Column(Integer, primary_key=True, index=True)

    event_type = Column(String(16), nullable=False)   # on|off|auto_on|auto_off
    trigger    = Column(String(32), nullable=True)    # manual|auto_disease

    # NodeMCU outputs for this event
    pump_a    = Column(Boolean, default=False)   # L298N IN1 (D3)
    pump_b    = Column(Boolean, default=False)   # L298N IN3 (D7)
    main_pump = Column(Boolean, default=False)   # Relay IN  (D4, active-LOW)

    duration_sec = Column(Integer, nullable=True)

    recorded_at = Column(DateTime, default=datetime.utcnow, index=True)


# =============================================================================
# SYSTEM LOGS
# =============================================================================
class SystemLog(Base):
    __tablename__ = "system_logs"

    id      = Column(Integer,    primary_key=True, index=True)
    level   = Column(String(16), nullable=False, default="INFO")
    message = Column(Text,       nullable=False)
    source  = Column(String(64), nullable=True)
    extra   = Column(JSON,       nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow, index=True)

    __table_args__ = (
        Index("ix_system_logs_level", "level"),
    )


# =============================================================================
# SYSTEM CONFIG (key-value store — used for auto/manual mode)
# =============================================================================
class SystemConfig(Base):
    __tablename__ = "system_config"

    id    = Column(Integer,    primary_key=True)
    key   = Column(String(64), unique=True, nullable=False, index=True)
    value = Column(Text,       nullable=False)

    updated_at = Column(
        DateTime,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
    )
