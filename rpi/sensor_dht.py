# =============================================================================
# sensor_dht.py — DHT22 Temperature & Humidity Reader
# Wiring (verified against wiring reference doc):
#   DHT22 Pin 1 (VCC)  → RPi Pin 1 (3.3V)
#   DHT22 Pin 2 (DATA) → RPi GPIO4 / Pin 7  [10 kΩ pull-up between VCC & DATA]
#   DHT22 Pin 3        → NC (not connected)
#   DHT22 Pin 4 (GND)  → RPi GND (Pin 6)
# =============================================================================

import time
import board
import adafruit_dht

_dht_device = None


def _get_device():
    global _dht_device
    if _dht_device is None:
        # board.D4 = BCM GPIO4 = physical Pin 7
        _dht_device = adafruit_dht.DHT22(board.D4)
    return _dht_device


def read_dht22(retries: int = 5, delay: float = 2.0) -> dict:
    """
    Read temperature (°C) and humidity (%) from DHT22.
    Returns: {"temperature": float, "humidity": float}
    Raises RuntimeError after all retries fail.
    """
    device = _get_device()
    last_error = None

    for attempt in range(retries):
        try:
            temperature = device.temperature
            humidity    = device.humidity
            if temperature is not None and humidity is not None:
                return {
                    "temperature": round(float(temperature), 1),
                    "humidity":    round(float(humidity), 1),
                }
        except RuntimeError as e:
            # DHT22 frequently needs retries on timing errors
            last_error = e
            time.sleep(delay)
        except Exception as e:
            last_error = e
            time.sleep(delay)

    raise RuntimeError(
        f"DHT22 failed after {retries} attempts. Last error: {last_error}"
    )


def cleanup():
    global _dht_device
    if _dht_device:
        try:
            _dht_device.exit()
        except Exception:
            pass
        _dht_device = None


# --- Quick self-test ---
if __name__ == "__main__":
    try:
        data = read_dht22()
        print(f"Temperature : {data['temperature']} °C")
        print(f"Humidity    : {data['humidity']} %")
    except RuntimeError as e:
        print(f"Error: {e}")
    finally:
        cleanup()
