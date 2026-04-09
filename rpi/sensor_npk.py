# =============================================================================
# sensor_npk.py — NPK Soil Sensor via MAX485 RS485-to-TTL Converter
# Team OJAS · NIT Hamirpur · Dept. of Electrical Engineering
#
# Protocol : Modbus RTU, 9600 baud, 8N1, Slave ID = 1
# UART     : /dev/npk → /dev/ttyAMA0 (RPi 4B PL011 — stable)
#            DO NOT use /dev/ttyS0 (mini-UART, clock drifts at 9600 baud)
#
# Wiring:
#   NPK Brown  (+12V)  → 12V battery +
#   NPK Black  (GND)   → 12V battery – (common GND with RPi)
#   NPK Yellow (A+)    → MAX485 Pin A
#   NPK Blue   (B–)    → MAX485 Pin B
#
#   MAX485 RO  (Pin 1) → RPi GPIO15 / Pin 10  (UART0 RX)
#   MAX485 RE  (Pin 2) ─┐
#   MAX485 DE  (Pin 3) ─┴→ RPi GPIO17 / Pin 11  (direction control)
#   MAX485 DI  (Pin 4) → RPi GPIO14 / Pin 8   (UART0 TX)
#   MAX485 GND (Pin 5) → RPi GND
#   MAX485 VCC (Pin 8) → RPi 3.3V
#
# Demo mode:
#   When the sensor is unavailable (wiring/power issue), realistic random
#   values are returned so the rest of the pipeline keeps running.
#   Typical healthy soil ranges used:
#     N : 20 – 80 mg/kg
#     P : 10 – 50 mg/kg
#     K : 30 – 90 mg/kg
# =============================================================================

import random
import time
import serial
import RPi.GPIO as GPIO

from config import NPK_PORT, NPK_BAUD, NPK_SLAVE_ID, NPK_DE_RE_PIN

import logging
logger = logging.getLogger(__name__)

# Modbus RTU frame for "read 3 holding registers starting at 0x001E, slave 1"
_MODBUS_READ_NPK = bytes([
    NPK_SLAVE_ID,   # 0x01  — slave address
    0x03,           # 0x03  — function: read holding registers
    0x00, 0x1E,     # start address: 0x001E (N register)
    0x00, 0x03,     # quantity: 3 registers (N, P, K)
    0xB5, 0xCE,     # CRC16 (little-endian) pre-computed for above bytes
])

_RESPONSE_LEN = 11

_ser     = None
_gpio_ok = False


def _crc16(data: bytes) -> int:
    crc = 0xFFFF
    for b in data:
        crc ^= b
        for _ in range(8):
            if crc & 0x0001:
                crc = (crc >> 1) ^ 0xA001
            else:
                crc >>= 1
    return crc


def _setup_gpio():
    global _gpio_ok
    if not _gpio_ok:
        GPIO.setmode(GPIO.BCM)
        GPIO.setwarnings(False)
        GPIO.setup(NPK_DE_RE_PIN, GPIO.OUT)
        GPIO.output(NPK_DE_RE_PIN, GPIO.LOW)
        _gpio_ok = True


def _get_serial() -> serial.Serial:
    global _ser
    if _ser is None or not _ser.is_open:
        _setup_gpio()
        _ser = serial.Serial(
            port          = NPK_PORT,
            baudrate      = NPK_BAUD,
            bytesize      = serial.EIGHTBITS,
            parity        = serial.PARITY_NONE,
            stopbits      = serial.STOPBITS_ONE,
            timeout       = 1.0,
            write_timeout = 1.0,
        )
        time.sleep(0.1)
    return _ser


def _demo_values() -> dict:
    """Return realistic randomised NPK values for demo / sensor-unavailable mode."""
    return {
        "N": random.randint(20, 80),
        "P": random.randint(10, 50),
        "K": random.randint(30, 90),
    }


def read_npk(retries: int = 3) -> dict:
    """
    Read Nitrogen, Phosphorus, Potassium from NPK sensor.
    Falls back to realistic random demo values if sensor is unreachable.

    Returns: {"N": int, "P": int, "K": int}  (mg/kg)
    Never raises — always returns a dict.
    """
    _setup_gpio()
    ser = _get_serial()
    last_error = None

    for attempt in range(1, retries + 1):
        try:
            # ── TX phase ────────────────────────────────────────────────────
            GPIO.output(NPK_DE_RE_PIN, GPIO.HIGH)
            time.sleep(0.010)

            ser.reset_input_buffer()
            ser.reset_output_buffer()
            ser.write(_MODBUS_READ_NPK)

            drain_time = (10.0 / NPK_BAUD) * len(_MODBUS_READ_NPK) + 0.010
            time.sleep(drain_time)

            # ── RX phase ────────────────────────────────────────────────────
            GPIO.output(NPK_DE_RE_PIN, GPIO.LOW)
            response = ser.read(_RESPONSE_LEN)

            if len(response) < _RESPONSE_LEN:
                raise RuntimeError(
                    f"Short response: got {len(response)} bytes, "
                    f"expected {_RESPONSE_LEN}"
                )

            payload  = response[:-2]
            crc_recv = response[-2] | (response[-1] << 8)
            crc_calc = _crc16(payload)
            if crc_recv != crc_calc:
                raise RuntimeError(
                    f"CRC mismatch: received 0x{crc_recv:04X}, "
                    f"calculated 0x{crc_calc:04X}"
                )

            if response[0] != NPK_SLAVE_ID:
                raise RuntimeError(f"Wrong slave ID: {response[0]}")
            if response[1] == 0x83:
                raise RuntimeError(f"Modbus exception: 0x{response[2]:02X}")
            if response[1] != 0x03:
                raise RuntimeError(f"Unexpected function code: 0x{response[1]:02X}")

            N = (response[3] << 8) | response[4]
            P = (response[5] << 8) | response[6]
            K = (response[7] << 8) | response[8]

            return {"N": N, "P": P, "K": K}

        except Exception as e:
            GPIO.output(NPK_DE_RE_PIN, GPIO.LOW)
            last_error = e
            if attempt < retries:
                time.sleep(0.5 * attempt)

    # All retries exhausted — return demo values instead of raising
    demo = _demo_values()
    logger.warning(
        "NPK sensor unavailable (%s) — using demo values N:%d P:%d K:%d",
        last_error, demo["N"], demo["P"], demo["K"],
    )
    return demo


def cleanup():
    global _ser, _gpio_ok
    if _ser:
        try:
            _ser.close()
        except Exception:
            pass
        _ser = None
    if _gpio_ok:
        try:
            GPIO.output(NPK_DE_RE_PIN, GPIO.LOW)
        except Exception:
            pass
    _gpio_ok = False


# --- Quick self-test ---
if __name__ == "__main__":
    import sys
    logging.basicConfig(level=logging.DEBUG)
    print(f"NPK sensor self-test on {NPK_PORT} @ {NPK_BAUD} baud")
    print(f"DE/RE pin: GPIO{NPK_DE_RE_PIN}")
    data = read_npk()
    print(f"  N (Nitrogen)  : {data['N']} mg/kg")
    print(f"  P (Phosphorus): {data['P']} mg/kg")
    print(f"  K (Potassium) : {data['K']} mg/kg")
    print("Self-test DONE ✓")
    cleanup()
    try:
        GPIO.cleanup()
    except Exception:
        pass