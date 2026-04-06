"""
config.py — Backend configuration for Agri-Watch OJAS
Hardware: RPi 4 + NodeMCU v3 ESP8266 (Serial JSON, no MQTT)
Team OJAS · NIT Hamirpur
"""
import os
from dotenv import load_dotenv

load_dotenv()


class Settings:
    # ── Database ──────────────────────────────────────────────────────────────
    DATABASE_URL: str = os.getenv("DATABASE_URL", "sqlite:///./agriwatch_ojas.db")

    # ── Serial (backend → NodeMCU via USB, /dev/ttyUSB0) ─────────────────────
    # If backend runs ON the RPi: /dev/ttyUSB0 (same port as rpi/main.py uses)
    # If backend on separate machine: use ser2net or point to that device
    SERIAL_PORT: str = os.getenv("SERIAL_PORT", "/dev/ttyUSB0")
    SERIAL_BAUD: int = int(os.getenv("SERIAL_BAUD", 115200))

    # ── CSV log (RPi writes pesticide_log.csv; backend tails it) ─────────────
    # Mount via NFS/SMB, or rsync from RPi to this path
    CSV_LOG_PATH: str = os.getenv("CSV_LOG_PATH", "/home/pi/pesticide_log.csv")

    # ── Pi Camera MJPEG stream ────────────────────────────────────────────────
    PI_HOST: str       = os.getenv("PI_HOST",       "raspberrypi.local")
    PI_STREAM_URL: str = os.getenv("PI_STREAM_URL", "http://raspberrypi.local:8080/stream")

    # ── Security ──────────────────────────────────────────────────────────────
    SECRET_KEY: str = os.getenv("SECRET_KEY", "change-this-in-production")

    # ── Alert thresholds (match rpi/config.py values) ─────────────────────────
    # DHT22 (GPIO4)
    TEMP_MIN: float     = float(os.getenv("TEMP_MIN",     15.0))
    TEMP_MAX: float     = float(os.getenv("TEMP_MAX",     40.0))
    HUMIDITY_MIN: float = float(os.getenv("HUMIDITY_MIN", 20.0))
    HUMIDITY_MAX: float = float(os.getenv("HUMIDITY_MAX", 95.0))
    # NPK RS485 (GPIO14/15/17 via MAX485)
    N_MIN: float = float(os.getenv("N_MIN", 10.0))
    P_MIN: float = float(os.getenv("P_MIN",  5.0))
    K_MIN: float = float(os.getenv("K_MIN",  5.0))
    # HC-SR04 US1 (GPIO23/24) and US2 (GPIO25/8)
    TANK_LEVEL_MIN: float    = float(os.getenv("TANK_LEVEL_MIN",    15.0))
    CONCENTRATION_MIN: float = float(os.getenv("CONCENTRATION_MIN", 10.0))


settings = Settings()
