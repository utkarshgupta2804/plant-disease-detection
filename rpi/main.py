# =============================================================================
# main.py — Intelligent Pesticide Sprinkling System — Main Loop
# Team OJAS · NIT Hamirpur · Dept. of Electrical Engineering
# Faculty: Dr. Katam Nishanth
#
# Device map (all paths are persistent udev symlinks):
#   /dev/npk      → NPK MAX485 on RPi PL011 UART (/dev/ttyAMA0)
#   /dev/lilygo   → LilyGo T-Display S3 AMOLED   (USB CDC)
#   /dev/nodemcu  → NodeMCU ESP32/8266             (USB CH340/CP2102)
#
# Execution order each 30-second cycle:
#   1. Capture plant image  (Pi Camera v2 via CSI)
#   2. Read sensors         (DHT22, NPK, US1, US2)
#   3. Send to Gemini       (image + sensor data)
#   4. Parse Gemini result
#   5. Send commands        → NodeMCU (/dev/nodemcu)
#   6. Send status + logs   → LilyGo  (/dev/lilygo)
#   7. Append row           → pesticide_log.csv
# =============================================================================

import csv
import logging
import signal
import sys
import time
from datetime import datetime
from pathlib import Path

import camera_capture
import gemini_client
import nodemcu_serial
import lilygo_serial
import sensor_dht
import sensor_npk
import sensor_ultrasonic
from config import (
    LILYGO_PORT,
    NODEMCU_PORT,
    NPK_PORT,
    LOG_FILE,
    LOOP_INTERVAL_SECONDS,
    MIN_TANK_LEVEL_PCT,
    MIN_CONCENTRATION_PCT,
)

# ─── Logging ──────────────────────────────────────────────────────────────────
logging.basicConfig(
    level   = logging.INFO,
    format  = "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers = [
        logging.StreamHandler(sys.stdout),
        logging.FileHandler("pesticide_system.log"),
    ],
)
logger = logging.getLogger("main")

# Attach LilyGo handler AFTER basicConfig so the handler itself can safely
# call logger.info() internally without recursion.
# The handler is lazy — it won't open the serial port until the first message.
_lilygo_handler = lilygo_serial.LilyGoHandler()
_lilygo_handler.setFormatter(logging.Formatter("%(name)s: %(message)s"))
logging.getLogger().addHandler(_lilygo_handler)

# ─── CSV schema ───────────────────────────────────────────────────────────────
CSV_HEADERS = [
    "timestamp",
    "temperature_c", "humidity_pct",
    "N_mgkg", "P_mgkg", "K_mgkg",
    "tank_level_pct", "concentration_pct",
    "disease", "severity", "confidence",
    "treatment", "pump_a", "pump_b", "main_pump",
    "spray_duration_s", "notes",
]


def _ensure_csv():
    p = Path(LOG_FILE)
    p.parent.mkdir(parents=True, exist_ok=True)
    if not p.exists():
        with open(p, "w", newline="") as f:
            csv.DictWriter(f, fieldnames=CSV_HEADERS).writeheader()


def _log_to_csv(sensor_data: dict, gemini_result: dict):
    row = {
        "timestamp":         datetime.now().isoformat(),
        "temperature_c":     sensor_data.get("temperature",   ""),
        "humidity_pct":      sensor_data.get("humidity",      ""),
        "N_mgkg":            sensor_data.get("N",             ""),
        "P_mgkg":            sensor_data.get("P",             ""),
        "K_mgkg":            sensor_data.get("K",             ""),
        "tank_level_pct":    sensor_data.get("tank_level",    ""),
        "concentration_pct": sensor_data.get("concentration", ""),
        "disease":           gemini_result.get("disease",     ""),
        "severity":          gemini_result.get("severity",    ""),
        "confidence":        gemini_result.get("confidence",  ""),
        "treatment":         gemini_result.get("treatment",   ""),
        "pump_a":            gemini_result.get("pump_a",      0),
        "pump_b":            gemini_result.get("pump_b",      0),
        "main_pump":         gemini_result.get("main_pump",   0),
        "spray_duration_s":  gemini_result.get("spray_duration_seconds", 0),
        "notes":             gemini_result.get("notes",       ""),
    }
    with open(LOG_FILE, "a", newline="") as f:
        csv.DictWriter(f, fieldnames=CSV_HEADERS).writerow(row)
    logger.info("Logged to CSV: %s", LOG_FILE)


# ─── Sensor helpers ───────────────────────────────────────────────────────────

def _read_all_sensors() -> dict:
    data = {}

    # DHT22 — GPIO4
    try:
        dht = sensor_dht.read_dht22()
        data.update(dht)
        logger.info("DHT22 → Temp:%.1f°C  Hum:%.1f%%",
                    dht["temperature"], dht["humidity"])
    except RuntimeError as e:
        logger.warning("DHT22 failed: %s", e)
        data["temperature"] = None
        data["humidity"]    = None

    # NPK — /dev/npk (ttyAMA0 PL011), MAX485 on GPIO14/15/17
    try:
        npk = sensor_npk.read_npk()
        data.update(npk)
        logger.info("NPK → N:%d P:%d K:%d mg/kg",
                    npk["N"], npk["P"], npk["K"])
    except RuntimeError as e:
        logger.warning("NPK failed: %s", e)
        data["N"] = data["P"] = data["K"] = None

    # Tank level — HC-SR04 US1, TRIG=GPIO23, ECHO=GPIO24
    try:
        us1 = sensor_ultrasonic.read_tank_level()
        data["tank_level"] = us1["level_pct"]
        logger.info("Tank level → %.1f%%", us1["level_pct"])
        if us1["level_pct"] < MIN_TANK_LEVEL_PCT:
            logger.warning("⚠ Tank LOW: %.1f%%", us1["level_pct"])
            nodemcu_serial.update_oled(
                "TANK LOW!",
                f"{us1['level_pct']:.0f}% remaining",
                "Refill soon", "")
            lilygo_serial.log(f"⚠ TANK LOW: {us1['level_pct']:.1f}%", "WARN")
    except RuntimeError as e:
        logger.warning("US1 (tank) failed: %s", e)
        data["tank_level"] = None

    # Mix concentration — HC-SR04 US2, TRIG=GPIO25, ECHO=GPIO8
    try:
        us2 = sensor_ultrasonic.read_concentration()
        data["concentration"] = us2["concentration_pct"]
        logger.info("Concentration → %.1f%%", us2["concentration_pct"])
        if us2["concentration_pct"] < MIN_CONCENTRATION_PCT:
            logger.warning("⚠ Mix conc LOW: %.1f%%", us2["concentration_pct"])
            lilygo_serial.log(
                f"⚠ MIX LOW: {us2['concentration_pct']:.1f}%", "WARN")
    except RuntimeError as e:
        logger.warning("US2 (concentration) failed: %s", e)
        data["concentration"] = None

    return data


# ─── Graceful shutdown ────────────────────────────────────────────────────────

_running = True


def _shutdown(signum, frame):
    global _running
    logger.info("Shutdown signal received — finishing current cycle…")
    _running = False


signal.signal(signal.SIGINT,  _shutdown)
signal.signal(signal.SIGTERM, _shutdown)


# ─── Main loop ────────────────────────────────────────────────────────────────

def main():
    logger.info("=" * 55)
    logger.info("Intelligent Pesticide Sprinkling System STARTING")
    logger.info("Team OJAS · NIT Hamirpur · Dr. Katam Nishanth")
    logger.info("Device map:")
    logger.info("  NPK      → %s  (ttyAMA0 PL011)", NPK_PORT)
    logger.info("  LilyGo   → %s",                  LILYGO_PORT)
    logger.info("  NodeMCU  → %s",                  NODEMCU_PORT)
    logger.info("=" * 55)

    _ensure_csv()

    # Boot messages — LilyGo serial opened lazily here on first log() call
    lilygo_serial.log("=== OJAS System BOOT ===")
    lilygo_serial.log(f"NPK     → {NPK_PORT}")
    lilygo_serial.log(f"LilyGo  → {LILYGO_PORT}")
    lilygo_serial.log(f"NodeMCU → {NODEMCU_PORT}")

    nodemcu_serial.update_oled("Team OJAS", "NIT Hamirpur", "System BOOT", "")
    nodemcu_serial.set_led("yellow")
    time.sleep(2)
    nodemcu_serial.set_led("green")
    nodemcu_serial.update_oled("System READY", "Waiting 1st cycle", "", "")

    while _running:
        cycle_start = time.time()
        logger.info("─── New cycle ───")
        lilygo_serial.log("─── New scan cycle ───")

        nodemcu_serial.set_led("yellow")
        nodemcu_serial.update_oled("Scanning…", "Please wait", "", "")

        # 1. Camera
        image_path = None
        try:
            image_path = camera_capture.capture_image()
            logger.info("Image captured: %s", image_path)
            lilygo_serial.log("Camera: captured OK")
        except Exception as e:
            logger.error("Camera failed: %s", e)
            lilygo_serial.log(f"Camera FAIL: {e}", "ERR")

        # 2. Sensors
        sensor_data = _read_all_sensors()

        # 3 & 4. Gemini
        if image_path:
            lilygo_serial.log("Gemini: sending image+sensors…")
            gemini_result = gemini_client.analyse(image_path, sensor_data)
            lilygo_serial.log(
                f"Gemini: {gemini_result['disease']} "
                f"[{gemini_result['severity']}] "
                f"{gemini_result['confidence']*100:.0f}% conf"
            )
        else:
            logger.warning("No image — skipping Gemini analysis")
            lilygo_serial.log("Gemini: SKIPPED (no image)", "WARN")
            gemini_result = {
                "disease": "unknown", "severity": "none",
                "confidence": 0.0,
                "treatment": "No image — manual inspection required.",
                "pump_a": 0, "pump_b": 0, "main_pump": 0,
                "spray_duration_seconds": 0,
                "notes": "Camera unavailable.",
            }

        # 5. NodeMCU commands
        spray_sec = gemini_result.get("spray_duration_seconds", 0)
        lilygo_serial.log(
            f"NodeMCU: PA={gemini_result['pump_a']} "
            f"PB={gemini_result['pump_b']} "
            f"Main={gemini_result['main_pump']} "
            f"Spray={spray_sec}s"
        )
        nodemcu_serial.apply_gemini_result(gemini_result, spray_duration=spray_sec)

        # 6. LilyGo status bar + treatment line
        lilygo_serial.send_status(gemini_result, sensor_data)
        if gemini_result.get("treatment"):
            lilygo_serial.log(f"Rx: {gemini_result['treatment'][:70]}")

        # 7. CSV log
        _log_to_csv(sensor_data, gemini_result)

        # Sleep until next cycle (interruptible)
        elapsed   = time.time() - cycle_start
        sleep_for = max(0, LOOP_INTERVAL_SECONDS - elapsed)
        logger.info("Cycle done %.1fs — sleeping %.1fs", elapsed, sleep_for)
        lilygo_serial.log(f"Cycle done in {elapsed:.1f}s  next in {sleep_for:.0f}s")

        for _ in range(int(sleep_for * 10)):
            if not _running:
                break
            time.sleep(0.1)

    # ── Shutdown ──────────────────────────────────────────────────────────────
    logger.info("Shutting down…")
    lilygo_serial.log("=== OJAS System SHUTDOWN ===")
    nodemcu_serial.update_oled("System OFF", "Goodbye!", "", "")
    nodemcu_serial.set_led("red")
    time.sleep(1)
    nodemcu_serial.all_off()
    nodemcu_serial.cleanup()
    camera_capture.cleanup()
    sensor_dht.cleanup()
    sensor_npk.cleanup()
    sensor_ultrasonic.cleanup()
    lilygo_serial.cleanup()
    logger.info("Shutdown complete.")


if __name__ == "__main__":
    main()
