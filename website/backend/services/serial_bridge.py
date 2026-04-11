"""
services/serial_bridge.py
Thread-safe serial bridge from the website backend to NodeMCU v3 ESP8266.

FIX 3: the background start() loop now proactively polls NodeMCU STATUS every
10 seconds and caches the result in _last_status.  HTTP handlers read that
cache instead of blocking the serial port inline.
"""
import json
import logging
import threading
import time

log = logging.getLogger(__name__)

try:
    import serial
    HAS_SERIAL = True
except ImportError:
    HAS_SERIAL = False
    log.warning("pyserial not installed — serial bridge running in stub mode.")


class SerialBridge:
    def __init__(self, port: str = "/dev/nodemcu", baud: int = 115200):
        self.port  = port
        self.baud  = baud
        self._ser  = None
        self._lock = threading.Lock()
        self._running    = False
        self._connected  = False
        self._last_status: dict = {}

    # ── Public API ────────────────────────────────────────────────────────────

    def is_connected(self) -> bool:
        return self._connected

    def get_status(self) -> dict:
        """Return the most recently cached NodeMCU status. Never blocks."""
        return dict(self._last_status)

    def send(self, payload: dict) -> dict | None:
        """
        Send one JSON command to NodeMCU and return parsed response.
        Called for motor commands (pump on/off) — not for status polling.
        Returns None on failure.
        """
        if not HAS_SERIAL:
            log.warning("Serial stub: would send %s", payload)
            return {"status": "OK_STUB"}

        with self._lock:
            if self._ser is None or not self._ser.is_open:
                if not self._try_connect():
                    return None
            try:
                line = json.dumps(payload) + "\n"
                self._ser.reset_input_buffer()
                self._ser.write(line.encode("utf-8"))
                raw = self._ser.readline().decode("utf-8", errors="replace").strip()
                if raw:
                    parsed = json.loads(raw)
                    self._last_status = parsed
                    return parsed
            except json.JSONDecodeError as e:
                log.warning("NodeMCU JSON error: %s", e)
            except Exception as e:
                log.error("Serial send error: %s", e)
                self._connected = False
                self._ser = None
        return None

    # ── Background loop ───────────────────────────────────────────────────────

    def start(self):
        if not self.port or self.port.upper() in ("DISABLED", "NONE"):
            log.info("Serial bridge disabled (SERIAL_PORT=%s).", self.port)
            return

        self._running = True
        log.info("Serial bridge background loop started on %s.", self.port)

        while self._running:
            with self._lock:
                # Reconnect if needed
                if self._ser is None or not self._ser.is_open:
                    self._try_connect()

                # FIX 3: poll STATUS in the background and cache the result.
                # HTTP handlers call get_status() which reads _last_status —
                # they never touch the serial port and never block.
                if self._connected:
                    try:
                        line = json.dumps({"cmd": "STATUS"}) + "\n"
                        self._ser.reset_input_buffer()
                        self._ser.write(line.encode("utf-8"))
                        raw = self._ser.readline().decode("utf-8", errors="replace").strip()
                        if raw:
                            self._last_status = json.loads(raw)
                    except Exception as e:
                        log.warning("Status probe failed: %s — will reconnect", e)
                        self._connected = False
                        try:
                            self._ser.close()
                        except Exception:
                            pass
                        self._ser = None

            time.sleep(10)  # probe every 10 s

    def stop(self):
        self._running = False
        with self._lock:
            if self._ser and self._ser.is_open:
                try:
                    self._ser.close()
                except Exception:
                    pass
        self._connected = False
        log.info("Serial bridge stopped.")

    # ── Internal ──────────────────────────────────────────────────────────────

    def _try_connect(self) -> bool:
        if not HAS_SERIAL:
            return False
        try:
            self._ser = serial.Serial(
                port          = self.port,
                baudrate      = self.baud,
                timeout       = 2,
                write_timeout = 2,
            )
            time.sleep(2)  # NodeMCU resets on USB connect
            self._connected = True
            log.info("Serial bridge connected: %s @ %d baud", self.port, self.baud)
            return True
        except Exception as e:
            log.warning("Serial bridge cannot connect to %s: %s", self.port, e)
            self._ser = None
            self._connected = False
            return False