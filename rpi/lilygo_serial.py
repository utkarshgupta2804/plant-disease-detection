# =============================================================================
# lilygo_serial.py — RPi → LilyGo T-Display S3 AMOLED Log Streamer
# Team OJAS · NIT Hamirpur · Dept. of Electrical Engineering
#
# Physical link:
#   LilyGo USB-C → RPi USB-A = /dev/ttyUSB1 @ 115200 baud
#   (NodeMCU occupies /dev/ttyUSB0; LilyGo uses /dev/ttyUSB1)
#
# This module sends two types of data to the LilyGo display:
#
#   1. Plain text log lines  → auto-scroll log view (newest at bottom)
#      e.g.  "[INFO] Gemini → disease: Early Blight | severity: moderate"
#
#   2. JSON status packets   → live status bar update
#      {"lilygo":"status","disease":"…","severity":"…",
#       "pump_a":0,"pump_b":0,"main_pump":0,
#       "temp":28.5,"humidity":72.0,"tank":80.0,"conc":65.0}
#
# Usage in main.py:
#   import lilygo_serial
#   lilygo_serial.log("Some message")
#   lilygo_serial.send_status(gemini_result, sensor_data)
#   lilygo_serial.cleanup()
# =============================================================================

import json
import logging
import threading
import time
import os

import serial

logger = logging.getLogger(__name__)

LILYGO_PORT = os.getenv("LILYGO_PORT", "/dev/ttyUSB1")
LILYGO_BAUD = 115200

_ser  = None
_lock = threading.Lock()


def _get_serial():
    global _ser
    if _ser is None or not _ser.is_open:
        try:
            _ser = serial.Serial(
                port          = LILYGO_PORT,
                baudrate      = LILYGO_BAUD,
                timeout       = 1,
                write_timeout = 2,
            )
            time.sleep(1.5)   # LilyGo boot settle
            logger.info("LilyGo serial opened: %s @ %d", LILYGO_PORT, LILYGO_BAUD)
        except serial.SerialException as e:
            logger.warning("LilyGo not available (%s): %s", LILYGO_PORT, e)
            _ser = None
    return _ser


def _send_line(text: str):
    """Send one newline-terminated string. Silently skips if LilyGo not connected."""
    with _lock:
        try:
            ser = _get_serial()
            if ser is None:
                return
            data = (text.strip() + "\n").encode("utf-8", errors="replace")
            ser.write(data)
        except Exception as e:
            logger.debug("LilyGo send failed: %s", e)
            global _ser
            _ser = None   # force reconnect on next call


def log(message: str, level: str = "INFO"):
    """
    Send a plain-text log line to the LilyGo auto-scroll display.
    Format: "[LEVEL] message"
    """
    _send_line(f"[{level}] {message}")


def send_status(gemini_result: dict, sensor_data: dict):
    """
    Send a JSON status packet to update the LilyGo status bar.
    Parsed by parseStatusJson() in the LilyGo firmware.
    """
    packet = {
        "lilygo":   "status",
        "disease":  gemini_result.get("disease",   "—"),
        "severity": gemini_result.get("severity",  "none"),
        "pump_a":   gemini_result.get("pump_a",    0),
        "pump_b":   gemini_result.get("pump_b",    0),
        "main_pump":gemini_result.get("main_pump", 0),
        "temp":     sensor_data.get("temperature", -99),
        "humidity": sensor_data.get("humidity",    -99),
        "tank":     sensor_data.get("tank_level",  -99),
        "conc":     sensor_data.get("concentration",-99),
    }
    _send_line(json.dumps(packet))


def cleanup():
    global _ser
    with _lock:
        if _ser and _ser.is_open:
            try:
                _send_line("[INFO] RPi shutting down — display stream closed.")
            except Exception:
                pass
            _ser.close()
        _ser = None
        logger.info("LilyGo serial closed.")


# ─── Logging Handler — pipe Python logs to LilyGo ──────────────────────────
class LilyGoHandler(logging.Handler):
    """
    Attach to Python's logging system to mirror all log records
    to the LilyGo display automatically.

    Usage in main.py:
        import lilygo_serial
        logging.getLogger().addHandler(lilygo_serial.LilyGoHandler())
    """
    LEVEL_MAP = {
        logging.DEBUG:    "DBG",
        logging.INFO:     "INFO",
        logging.WARNING:  "WARN",
        logging.ERROR:    "ERR",
        logging.CRITICAL: "CRIT",
    }

    def emit(self, record: logging.LogRecord):
        try:
            lvl = self.LEVEL_MAP.get(record.levelno, "LOG")
            # Truncate message for display
            msg = self.format(record)
            # Strip timestamp prefix if present — LilyGo will show it scrolling
            # Keep under 80 chars so it fits on AMOLED at font size 10
            if len(msg) > 78:
                msg = msg[:75] + "…"
            _send_line(f"[{lvl}] {msg}")
        except Exception:
            pass   # never let display issues break the main loop


# --- Quick self-test ---
if __name__ == "__main__":
    logging.basicConfig(level=logging.DEBUG)
    print(f"Testing LilyGo on {LILYGO_PORT}…")
    log("=== Team OJAS · NIT Hamirpur ===")
    log("LilyGo serial test OK", "INFO")
    send_status(
        {"disease": "Early Blight", "severity": "moderate",
         "pump_a": 1, "pump_b": 0, "main_pump": 1},
        {"temperature": 28.5, "humidity": 72.0,
         "tank_level": 65.0, "concentration": 50.0},
    )
    time.sleep(2)
    cleanup()
