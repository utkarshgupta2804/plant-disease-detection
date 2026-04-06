"""
services/csv_watcher.py
Tails the Raspberry Pi's /home/pi/pesticide_log.csv and inserts new rows
into the SQLite database as SensorReading, DiseaseResult, MotorEvent, and
SystemLog records.

CSV columns written by rpi/main.py (_log_to_csv):
  timestamp, temperature_c, humidity_pct,
  N_mgkg, P_mgkg, K_mgkg,
  tank_level_pct, concentration_pct,
  disease, severity, confidence,
  treatment, pump_a, pump_b, main_pump,
  spray_duration_s, notes

Hardware context for pump columns:
  pump_a    → NodeMCU L298N IN1 (D3/GPIO0)   — mixing pump A
  pump_b    → NodeMCU L298N IN3 (D7/GPIO13)  — mixing pump B
  main_pump → NodeMCU Relay IN  (D4/GPIO2)   — 12V spray pump (active-LOW relay)

This replaces the MQTT bridge from the original Agri-Watch v1 project.
No broker required — the RPi writes CSV; this service reads it.
"""
import csv
import logging
import os
import time
from datetime import datetime

from db.database import SessionLocal
from db.models import SensorReading, DiseaseResult, MotorEvent, SystemLog

log = logging.getLogger(__name__)
POLL_INTERVAL = 5  # seconds between file polls


class CSVWatcher:
    def __init__(self, csv_path: str):
        self.csv_path = csv_path
        self._running  = False
        self._last_pos = 0   # byte position of last read

    def start(self):
        self._running = True
        log.info("CSV watcher started: %s", self.csv_path)

        # Skip existing data on startup — only process new rows going forward
        if os.path.exists(self.csv_path):
            self._last_pos = os.path.getsize(self.csv_path)
            log.info("CSV watcher: skipped %d existing bytes", self._last_pos)

        while self._running:
            try:
                self._poll()
            except Exception as e:
                log.error("CSV watcher error: %s", e)
            time.sleep(POLL_INTERVAL)

    def stop(self):
        self._running = False
        log.info("CSV watcher stopped.")

    def _poll(self):
        if not os.path.exists(self.csv_path):
            return

        size = os.path.getsize(self.csv_path)
        if size <= self._last_pos:
            return   # no new data

        with open(self.csv_path, "r", newline="") as f:
            # If at beginning, DictReader reads the header automatically.
            # If mid-file, inject field names from file header.
            if self._last_pos > 0:
                f.seek(0)
                headers = next(csv.reader(f))
                f.seek(self._last_pos)
                reader = csv.DictReader(f, fieldnames=headers)
            else:
                f.seek(self._last_pos)
                reader = csv.DictReader(f)

            new_rows = list(reader)
            self._last_pos = f.tell()

        for row in new_rows:
            self._insert_row(row)

    def _safe_float(self, val) -> float | None:
        try:
            v = float(val)
            return None if v != v else v   # reject NaN
        except (TypeError, ValueError):
            return None

    def _safe_int(self, val) -> int | None:
        try:
            return int(float(val))
        except (TypeError, ValueError):
            return None

    def _insert_row(self, row: dict):
        db = SessionLocal()
        try:
            temp     = self._safe_float(row.get("temperature_c"))
            humidity = self._safe_float(row.get("humidity_pct"))
            N        = self._safe_float(row.get("N_mgkg"))
            P        = self._safe_float(row.get("P_mgkg"))
            K        = self._safe_float(row.get("K_mgkg"))
            tank     = self._safe_float(row.get("tank_level_pct"))
            conc     = self._safe_float(row.get("concentration_pct"))

            disease_name  = row.get("disease", "unknown")
            severity      = row.get("severity", "none")
            spray_dur     = self._safe_int(row.get("spray_duration_s")) or 0
            pump_a_val    = self._safe_int(row.get("pump_a"))  or 0
            pump_b_val    = self._safe_int(row.get("pump_b"))  or 0
            main_pump_val = self._safe_int(row.get("main_pump")) or 0

            # ── SensorReading ─────────────────────────────────────────────────
            db.add(SensorReading(
                temperature       = temp,
                humidity          = humidity,
                nitrogen          = N,
                phosphorus        = P,
                potassium         = K,
                tank_level_pct    = tank,    # HC-SR04 US1 (GPIO23/24)
                concentration_pct = conc,    # HC-SR04 US2 (GPIO25/8)
            ))

            # ── DiseaseResult ─────────────────────────────────────────────────
            db.add(DiseaseResult(
                disease          = disease_name,
                confidence       = self._safe_float(row.get("confidence")),
                severity         = severity,
                treatment        = row.get("treatment", ""),
                pump_a           = pump_a_val,        # L298N IN1 (D3)
                pump_b           = pump_b_val,        # L298N IN3 (D7)
                main_pump        = main_pump_val,     # Relay IN  (D4, active-LOW)
                spray_duration_s = spray_dur,
                notes            = row.get("notes", ""),
                sensor_context   = {
                    "temperature": temp, "humidity": humidity,
                    "N": N, "P": P, "K": K,
                    "tank_level_pct": tank,
                    "concentration_pct": conc,
                },
            ))

            # ── MotorEvent (only if spray actually ran) ───────────────────────
            if spray_dur > 0 and main_pump_val:
                db.add(MotorEvent(
                    event_type   = "auto_on",
                    trigger      = "auto_disease",
                    pump_a       = bool(pump_a_val),
                    pump_b       = bool(pump_b_val),
                    main_pump    = bool(main_pump_val),
                    duration_sec = spray_dur,
                ))

            # ── SystemLog ────────────────────────────────────────────────────
            db.add(SystemLog(
                level   = "INFO",
                message = (
                    f"Gemini: {disease_name} | sev={severity} | "
                    f"spray={spray_dur}s | "
                    f"T={temp}°C H={humidity}% "
                    f"N={N} P={P} K={K}"
                ),
                source  = "csv_watcher",
            ))

            db.commit()
            log.debug("Inserted row: %s @ %s", disease_name, row.get("timestamp"))

        except Exception as e:
            db.rollback()
            log.error("CSV row insert failed: %s | row: %s", e, row)
        finally:
            db.close()
