# =============================================================================
# nodemcu_serial.py — RPi ↔ NodeMCU v3 ESP8266 Serial JSON Bridge
#
# Physical link:
#   RPi USB-A port → NodeMCU Micro-USB = /dev/ttyUSB0 @ 115200 baud
#   (Simultaneously powers NodeMCU AND provides serial comms)
#
# Protocol: newline-terminated JSON, 115200 baud
#
# RPi → NodeMCU commands:
#   {"cmd": "PUMP_A",    "state": 1}          — L298N IN1 (D3) · Pump A
#   {"cmd": "PUMP_B",    "state": 0}          — L298N IN3 (D7) · Pump B
#   {"cmd": "MAIN_PUMP", "state": 1}          — Relay IN  (D4) · Main spray pump
#   {"cmd": "LED",       "color": "green"}    — LEDs: red|yellow|green|off
#   {"cmd": "OLED",      "line1": "…", "line2": "…", "line3": "…", "line4": "…"}
#   {"cmd": "STATUS"}
#
# NodeMCU → RPi responses:
#   {"status": "OK",      "pump_a": 0, "pump_b": 0, "main_pump": 0, "led": "green"}
#   {"status": "BOOT_OK", "msg": "NodeMCU ready"}
#   {"status": "ERROR",   "msg": "…"}
# =============================================================================

import json
import time
import logging
import threading
import serial

from config import SERIAL_PORT, SERIAL_BAUD, SERIAL_TIMEOUT

logger = logging.getLogger(__name__)

_ser  = None
_lock = threading.Lock()


def _get_serial() -> serial.Serial:
    global _ser
    if _ser is None or not _ser.is_open:
        _ser = serial.Serial(
            port          = SERIAL_PORT,
            baudrate      = SERIAL_BAUD,
            timeout       = SERIAL_TIMEOUT,
            write_timeout = 2,
        )
        time.sleep(2)   # allow NodeMCU to reset after USB connect
        logger.info("Serial opened: %s @ %d baud", SERIAL_PORT, SERIAL_BAUD)
    return _ser


def _send(payload: dict) -> dict | None:
    """
    Thread-safe: send one JSON command, return parsed response dict or None.
    """
    with _lock:
        try:
            ser = _get_serial()
            line = json.dumps(payload) + "\n"
            ser.reset_input_buffer()
            ser.write(line.encode("utf-8"))
            logger.debug("→ NodeMCU: %s", line.strip())

            raw = ser.readline().decode("utf-8", errors="replace").strip()
            if raw:
                logger.debug("← NodeMCU: %s", raw)
                return json.loads(raw)
        except json.JSONDecodeError as e:
            logger.warning("NodeMCU JSON error: %s | raw: %s", e, raw)
        except serial.SerialException as e:
            logger.error("Serial error: %s — will reconnect", e)
            global _ser
            _ser = None   # force reconnect on next call
    return None


# ─── Public command helpers ────────────────────────────────────────────────────

def pump_a(state: int) -> dict | None:
    """Pump A — L298N IN1 (NodeMCU D3/GPIO0). state: 1=ON, 0=OFF"""
    return _send({"cmd": "PUMP_A", "state": int(bool(state))})


def pump_b(state: int) -> dict | None:
    """Pump B — L298N IN3 (NodeMCU D7/GPIO13). state: 1=ON, 0=OFF"""
    return _send({"cmd": "PUMP_B", "state": int(bool(state))})


def main_pump(state: int) -> dict | None:
    """Main spray relay — Relay IN (NodeMCU D4/GPIO2, active-LOW). state: 1=ON, 0=OFF"""
    return _send({"cmd": "MAIN_PUMP", "state": int(bool(state))})


def set_led(color: str) -> dict | None:
    """
    Set status LED on NodeMCU.
    color: 'red'    → D0 (GPIO16)
           'yellow' → D5 (GPIO14)
           'green'  → D6 (GPIO12)
           'off'    → all LEDs off
    Only one LED is lit at a time.
    """
    return _send({"cmd": "LED", "color": color})


def update_oled(line1: str = "", line2: str = "",
                line3: str = "", line4: str = "") -> dict | None:
    """
    Send up to 4 lines of text to OLED (SSD1306 128×64, I2C 0x3C on D1/D2).
    Max 21 chars per line at default font size.
    """
    return _send({
        "cmd":   "OLED",
        "line1": str(line1)[:21],
        "line2": str(line2)[:21],
        "line3": str(line3)[:21],
        "line4": str(line4)[:21],
    })


def get_status() -> dict | None:
    """Request current state of all NodeMCU outputs."""
    return _send({"cmd": "STATUS"})


def apply_gemini_result(result: dict, spray_duration: int = 0) -> None:
    """
    Apply a full Gemini response dict to NodeMCU hardware in sequence:
      1. Update OLED with disease / severity / treatment
      2. Set status LED (green=healthy, yellow=mild/moderate, red=severe)
      3. Activate mixing pumps (pump_a, pump_b)
      4. Activate main spray relay for spray_duration seconds, then stop
      5. Return to idle

    All values match website DB model fields (DiseaseResult):
      pump_a, pump_b, main_pump, spray_duration_seconds
    """
    disease   = result.get("disease",   "unknown")
    severity  = result.get("severity",  "none")
    treatment = str(result.get("treatment", ""))[:21]
    spray_sec = max(0, int(spray_duration))

    # 1. OLED update
    update_oled(
        line1 = f"Disease:{disease}"[:21],
        line2 = f"Sev:{severity}"[:21],
        line3 = treatment,
        line4 = f"Spray:{spray_sec}s" if spray_sec > 0 else "No spray",
    )

    # 2. LED by severity
    led_map = {
        "none":     "green",
        "mild":     "yellow",
        "moderate": "yellow",
        "severe":   "red",
    }
    set_led(led_map.get(severity, "red"))

    # 3. Mixing pumps
    pump_a(result.get("pump_a", 0))
    pump_b(result.get("pump_b", 0))

    # 4. Main spray relay with timed run
    if result.get("main_pump", 0) and spray_sec > 0:
        main_pump(1)
        time.sleep(spray_sec)
        main_pump(0)
    else:
        main_pump(0)

    # 5. Idle
    time.sleep(2)
    if severity == "none":
        set_led("green")
    pump_a(0)
    pump_b(0)


def all_off() -> None:
    """Emergency stop — turn off all NodeMCU outputs immediately."""
    pump_a(0)
    pump_b(0)
    main_pump(0)
    set_led("red")
    update_oled("EMERGENCY STOP", "All outputs OFF", "", "")


def cleanup() -> None:
    global _ser
    with _lock:
        try:
            all_off()
        except Exception:
            pass
        if _ser and _ser.is_open:
            _ser.close()
        _ser = None
        logger.info("Serial port closed.")


# --- Quick self-test ---
if __name__ == "__main__":
    logging.basicConfig(level=logging.DEBUG)
    print("Status:", get_status())
    set_led("yellow")
    update_oled("Team OJAS", "NIT Hamirpur", "Serial OK", "")
    time.sleep(3)
    set_led("green")
    update_oled("System READY", "", "", "")
    time.sleep(2)
    cleanup()
