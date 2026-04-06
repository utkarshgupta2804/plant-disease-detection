# =============================================================================
# sensor_ultrasonic.py — HC-SR04 Ultrasonic Distance → Percentage
#
# Wiring (verified against wiring reference doc):
#
#   SENSOR 1 — Pesticide Tank Level:
#     US1 VCC  → RPi Pin 2 (5V)       [HC-SR04 requires 5V, NOT 3.3V]
#     US1 TRIG → RPi GPIO23 / Pin 16  [10 µs HIGH pulse to trigger]
#     US1 ECHO → 1kΩ → GPIO24/Pin18 → 2kΩ → GND
#                [ECHO = 5V; voltage divider → ~3.33V safe for RPi GPIO]
#     US1 GND  → RPi GND
#
#   SENSOR 2 — Mix Concentration Level:
#     US2 VCC  → RPi Pin 4 (5V)       [HC-SR04 requires 5V, NOT 3.3V]
#     US2 TRIG → RPi GPIO25 / Pin 22  [10 µs HIGH pulse to trigger]
#     US2 ECHO → 1kΩ → GPIO8/Pin24 → 2kΩ → GND
#                [ECHO = 5V; voltage divider → ~3.33V safe for RPi GPIO]
#     US2 GND  → RPi GND
#
#   Voltage divider formula: V_gpio = 5V × 2kΩ/(1kΩ+2kΩ) = 3.33V ✓
#   Distance formula: distance_cm = (echo_pulse_µs × 0.0343) / 2
# =============================================================================

import time
import RPi.GPIO as GPIO

from config import (
    US1_TRIG, US1_ECHO, US1_EMPTY_CM, US1_FULL_CM,
    US2_TRIG, US2_ECHO, US2_EMPTY_CM, US2_FULL_CM,
)

_initialized = False


def _setup():
    global _initialized
    if not _initialized:
        GPIO.setmode(GPIO.BCM)
        GPIO.setwarnings(False)
        GPIO.setup(US1_TRIG, GPIO.OUT)
        GPIO.setup(US1_ECHO, GPIO.IN)
        GPIO.setup(US2_TRIG, GPIO.OUT)
        GPIO.setup(US2_ECHO, GPIO.IN)
        GPIO.output(US1_TRIG, GPIO.LOW)
        GPIO.output(US2_TRIG, GPIO.LOW)
        time.sleep(0.05)   # settling time
        _initialized = True


def _measure_distance_cm(trig_pin: int, echo_pin: int,
                          timeout: float = 0.04) -> float:
    """
    Fire a single HC-SR04 pulse and return distance in cm.
    ECHO pin is already voltage-divided (5V→3.33V) — safe for RPi GPIO.
    Raises RuntimeError on timeout.
    """
    _setup()

    # 10 µs trigger pulse
    GPIO.output(trig_pin, GPIO.HIGH)
    time.sleep(0.00001)          # 10 µs
    GPIO.output(trig_pin, GPIO.LOW)

    deadline = time.time() + timeout

    # Wait for ECHO HIGH
    while GPIO.input(echo_pin) == 0:
        if time.time() > deadline:
            raise RuntimeError(f"TRIG GPIO{trig_pin}: echo start timeout")
    pulse_start = time.time()

    # Wait for ECHO LOW
    while GPIO.input(echo_pin) == 1:
        if time.time() > deadline:
            raise RuntimeError(f"TRIG GPIO{trig_pin}: echo end timeout")
    pulse_end = time.time()

    duration_us  = (pulse_end - pulse_start) * 1_000_000
    distance_cm  = (duration_us * 0.0343) / 2
    return round(distance_cm, 1)


def _distance_to_percent(distance_cm: float,
                          empty_cm: float, full_cm: float) -> float:
    """
    Convert measured distance to fill percentage.
    Sensor mounted above liquid: large distance = empty, small = full.
    """
    span = empty_cm - full_cm
    if span <= 0:
        return 0.0
    pct = ((empty_cm - distance_cm) / span) * 100.0
    return round(max(0.0, min(100.0, pct)), 1)


def read_tank_level(samples: int = 5) -> dict:
    """
    Read pesticide tank fill level (Sensor 1: TRIG=GPIO23, ECHO=GPIO24).
    Returns: {"distance_cm": float, "level_pct": float}
    Raises RuntimeError if no valid readings.
    """
    distances = []
    for _ in range(samples):
        try:
            d = _measure_distance_cm(US1_TRIG, US1_ECHO)
            distances.append(d)
        except RuntimeError:
            pass
        time.sleep(0.06)

    if not distances:
        raise RuntimeError("Tank level sensor (US1 GPIO23/24) returned no valid readings")

    avg = sum(distances) / len(distances)
    pct = _distance_to_percent(avg, US1_EMPTY_CM, US1_FULL_CM)
    return {"distance_cm": round(avg, 1), "level_pct": pct}


def read_concentration(samples: int = 5) -> dict:
    """
    Read mixing concentration level (Sensor 2: TRIG=GPIO25, ECHO=GPIO8).
    Returns: {"distance_cm": float, "concentration_pct": float}
    Raises RuntimeError if no valid readings.
    """
    distances = []
    for _ in range(samples):
        try:
            d = _measure_distance_cm(US2_TRIG, US2_ECHO)
            distances.append(d)
        except RuntimeError:
            pass
        time.sleep(0.06)

    if not distances:
        raise RuntimeError("Concentration sensor (US2 GPIO25/8) returned no valid readings")

    avg = sum(distances) / len(distances)
    pct = _distance_to_percent(avg, US2_EMPTY_CM, US2_FULL_CM)
    return {"distance_cm": round(avg, 1), "concentration_pct": pct}


def cleanup():
    global _initialized
    if _initialized:
        try:
            GPIO.cleanup([US1_TRIG, US1_ECHO, US2_TRIG, US2_ECHO])
        except Exception:
            pass
        _initialized = False


# --- Quick self-test ---
if __name__ == "__main__":
    try:
        tank = read_tank_level()
        conc = read_concentration()
        print(f"Tank level   : {tank['level_pct']} %  ({tank['distance_cm']} cm)")
        print(f"Concentration: {conc['concentration_pct']} %  ({conc['distance_cm']} cm)")
    except RuntimeError as e:
        print(f"Error: {e}")
    finally:
        cleanup()
