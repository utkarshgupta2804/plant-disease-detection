# =============================================================================
# lilygo_serial.py — RPi → LilyGo T-Display S3 AMOLED Log Streamer
# Team OJAS · NIT Hamirpur · Dept. of Electrical Engineering
#
# Physical link:
#   LilyGo USB-C → RPi USB-A  →  /dev/lilygo  (udev symlink, always stable)
#
# Two message types:
#   1. Plain text log lines   → auto-scroll log on AMOLED
#      Format: "[LEVEL] message\n"
#
#   2. JSON status packets    → live status bar
#      {"lilygo":"status","disease":"…","severity":"…",
#       "pump_a":0,"pump_b":0,"main_pump":0,
#       "temp":28.5,"humidity":72.0,"tank":80.0,"conc":65.0}
#
# Key fixes vs previous version:
#   - Port read from config.py (not env var) — consistent with whole project
#   - Serial opened lazily on first use, NOT at import time
#     (prevents crash if LilyGo not plugged in at boot)
#   - LilyGoHandler.emit() guards against being called before logging is
#     fully initialised (no recursive logging)
#   - _send_line() never raises — display issues never break main loop
#   - Auto-reconnect on write failure
# =============================================================================

import json
import logging
import threading
import time

import serial

from config import LILYGO_PORT, LILYGO_BAUD

logger = logging.getLogger(__name__)

_ser       : serial.Serial | None = None
_lock      = threading.Lock()
_connected = False     # True once we've successfully opened the port


# ─── Internal helpers ──────────────────────────────────────────────────────────

def _open_serial() -> serial.Serial | None:
    """
    Try to open the LilyGo serial port.
    Returns the Serial object on success, None on failure.
    Does NOT raise.
    """
    try:
        ser = serial.Serial(
            port          = LILYGO_PORT,
            baudrate      = LILYGO_BAUD,
            timeout       = 1,
            write_timeout = 2,
        )
        time.sleep(1.5)     # LilyGo CDC boot settle (important for T-Display S3)
        return ser
    except serial.SerialException:
        return None


def _get_serial() -> serial.Serial | None:
    """
    Return the open Serial instance, reconnecting if needed.
    Thread-safe. Never raises.
    """
    global _ser, _connected
    if _ser is not None and _ser.is_open:
        return _ser
    # Try to open / reopen
    _ser = _open_serial()
    if _ser is not None:
        if not _connected:
            # Log only to Python logger (not back through LilyGoHandler — avoid loop)
            logger.info("LilyGo connected: %s @ %d baud", LILYGO_PORT, LILYGO_BAUD)
            _connected = True
    else:
        if _connected:
            logger.warning("LilyGo disconnected — will retry on next send.")
            _connected = False
    return _ser


def _send_line(text: str) -> bool:
    """
    Send one newline-terminated UTF-8 string to the LilyGo.
    Returns True on success, False if LilyGo is unavailable.
    Never raises.
    """
    global _ser
    with _lock:
        try:
            ser = _get_serial()
            if ser is None:
                return False
            data = (text.rstrip("\n") + "\n").encode("utf-8", errors="replace")
            ser.write(data)
            return True
        except Exception:
            # Force reconnect on next call
            try:
                if _ser and _ser.is_open:
                    _ser.close()
            except Exception:
                pass
            _ser = None
            return False


# ─── Public API ────────────────────────────────────────────────────────────────

def log(message: str, level: str = "INFO") -> None:
    """Send a plain-text log line to the LilyGo auto-scroll display."""
    _send_line(f"[{level}] {message}")


def send_status(gemini_result: dict, sensor_data: dict) -> None:
    """Send a JSON status packet to update the LilyGo status bar."""
    packet = {
        "lilygo":    "status",
        "disease":   gemini_result.get("disease",       "—"),
        "severity":  gemini_result.get("severity",      "none"),
        "pump_a":    gemini_result.get("pump_a",        0),
        "pump_b":    gemini_result.get("pump_b",        0),
        "main_pump": gemini_result.get("main_pump",     0),
        "temp":      sensor_data.get("temperature",     -99),
        "humidity":  sensor_data.get("humidity",        -99),
        "tank":      sensor_data.get("tank_level",      -99),
        "conc":      sensor_data.get("concentration",   -99),
    }
    _send_line(json.dumps(packet))


def cleanup() -> None:
    """Close the serial port cleanly on shutdown."""
    global _ser
    with _lock:
        if _ser and _ser.is_open:
            try:
                _send_line("[INFO] RPi shutting down — display stream closed.")
                time.sleep(0.1)
                _ser.close()
            except Exception:
                pass
        _ser = None
    logger.info("LilyGo serial closed.")


# ─── Logging Handler ───────────────────────────────────────────────────────────

class LilyGoHandler(logging.Handler):
    """
    Attach to Python's root logger to mirror all log records to the
    LilyGo AMOLED display automatically.

    Usage in main.py (attach AFTER basicConfig):
        logging.getLogger().addHandler(lilygo_serial.LilyGoHandler())

    Safe:
        - Never lets display failure propagate to the main application
        - Skips its own logger's records to prevent infinite recursion
        - Truncates long messages to 78 chars for AMOLED readability
    """

    _LEVEL_MAP = {
        logging.DEBUG:    "DBG",
        logging.INFO:     "INFO",
        logging.WARNING:  "WARN",
        logging.ERROR:    "ERR",
        logging.CRITICAL: "CRIT",
    }

    # Loggers whose records we must NOT forward (would cause recursion)
    _SKIP_NAMES = {"lilygo_serial", "serial", "root"}

    def emit(self, record: logging.LogRecord) -> None:
        # Guard: skip own logger to prevent infinite loop
        if record.name in self._SKIP_NAMES:
            return
        try:
            lvl = self._LEVEL_MAP.get(record.levelno, "LOG")
            msg = self.format(record)
            # Truncate to 78 chars for AMOLED @ small font
            if len(msg) > 78:
                msg = msg[:75] + "…"
            _send_line(f"[{lvl}] {msg}")
        except Exception:
            pass   # display issues must never crash the main loop


# --- Quick self-test ---
if __name__ == "__main__":
    import sys
    logging.basicConfig(level=logging.DEBUG)
    print(f"Testing LilyGo on {LILYGO_PORT} @ {LILYGO_BAUD} baud …")

    log("=== Team OJAS · NIT Hamirpur ===")
    log("LilyGo serial test", "INFO")
    send_status(
        {"disease": "Early Blight", "severity": "moderate",
         "pump_a": 1, "pump_b": 0, "main_pump": 1},
        {"temperature": 28.5, "humidity": 72.0,
         "tank_level": 65.0, "concentration": 50.0},
    )
    time.sleep(2)
    cleanup()
    print("Done.")
