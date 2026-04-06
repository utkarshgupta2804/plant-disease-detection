# =============================================================================
# sensor_npk.py — NPK Soil Sensor via MAX485 RS485-to-TTL Converter
# Protocol: Modbus RTU, 9600 baud, 8N1, Slave ID = 1
#
# Wiring (verified against wiring reference doc):
#   NPK Brown  (+12V)     → 12V battery +
#   NPK Black  (GND)      → 12V battery – (common GND)
#   NPK Yellow (A+)       → MAX485 Pin A  (RS485 A+ non-inverting)
#   NPK Blue   (B–)       → MAX485 Pin B  (RS485 B– inverting)
#
#   MAX485 RO  (Pin 1)    → RPi GPIO15 / Pin 10  (UART RX — NPK data in)
#   MAX485 RE  (Pin 2) ─┐
#   MAX485 DE  (Pin 3) ─┴→ RPi GPIO17 / Pin 11  (direction: HIGH=TX, LOW=RX)
#   MAX485 DI  (Pin 4)    → RPi GPIO14 / Pin 8   (UART TX — Modbus commands out)
#   MAX485 GND (Pin 5)    → RPi GND
#   MAX485 A   (Pin 6)    → NPK Yellow wire (A+)
#   MAX485 B   (Pin 7)    → NPK Blue wire (B–)
#   MAX485 VCC (Pin 8)    → RPi 3.3V (Pin 1)
# =============================================================================

import time
import minimalmodbus
import serial
import RPi.GPIO as GPIO

from config import NPK_PORT, NPK_BAUD, NPK_SLAVE_ID, NPK_DE_RE_PIN

_instrument = None


def _setup_gpio():
    GPIO.setmode(GPIO.BCM)
    GPIO.setwarnings(False)
    GPIO.setup(NPK_DE_RE_PIN, GPIO.OUT)
    GPIO.output(NPK_DE_RE_PIN, GPIO.LOW)   # Default: receive mode


def _get_instrument() -> minimalmodbus.Instrument:
    global _instrument
    if _instrument is None:
        _setup_gpio()
        inst = minimalmodbus.Instrument(NPK_PORT, NPK_SLAVE_ID)
        inst.serial.baudrate = NPK_BAUD
        inst.serial.bytesize = 8
        inst.serial.parity   = serial.PARITY_NONE
        inst.serial.stopbits = 1
        inst.serial.timeout  = 1.0
        inst.mode = minimalmodbus.MODE_RTU
        _instrument = inst
    return _instrument


def _read_register(register: int, retries: int = 3) -> int:
    """Read a single holding register with MAX485 DE/RE direction switching."""
    inst = _get_instrument()
    last_error = None

    for attempt in range(retries):
        try:
            GPIO.output(NPK_DE_RE_PIN, GPIO.HIGH)   # TX mode (HIGH = transmit)
            time.sleep(0.01)
            value = inst.read_register(register, 0, functioncode=3)
            GPIO.output(NPK_DE_RE_PIN, GPIO.LOW)    # RX mode (LOW = receive)
            return value
        except Exception as e:
            GPIO.output(NPK_DE_RE_PIN, GPIO.LOW)
            last_error = e
            time.sleep(0.5)

    raise RuntimeError(
        f"NPK register 0x{register:04X} failed after {retries} attempts: {last_error}"
    )


def read_npk(retries: int = 3) -> dict:
    """
    Read Nitrogen, Phosphorus, Potassium from NPK sensor.
    Registers: 0x001E = N, 0x001F = P, 0x0020 = K (standard RS485 NPK mapping)
    Returns: {"N": int, "P": int, "K": int}  (mg/kg)
    Raises RuntimeError on failure.
    """
    N = _read_register(0x001E, retries)
    P = _read_register(0x001F, retries)
    K = _read_register(0x0020, retries)
    return {"N": N, "P": P, "K": K}


def cleanup():
    global _instrument
    if _instrument:
        try:
            _instrument.serial.close()
        except Exception:
            pass
        _instrument = None
    try:
        GPIO.output(NPK_DE_RE_PIN, GPIO.LOW)
    except Exception:
        pass


# --- Quick self-test ---
if __name__ == "__main__":
    try:
        data = read_npk()
        print(f"N (Nitrogen)  : {data['N']} mg/kg")
        print(f"P (Phosphorus): {data['P']} mg/kg")
        print(f"K (Potassium) : {data['K']} mg/kg")
    except RuntimeError as e:
        print(f"Error: {e}")
    finally:
        cleanup()
        GPIO.cleanup()
