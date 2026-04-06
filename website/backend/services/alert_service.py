"""
services/alert_service.py
Checks sensor readings against thresholds for the OJAS hardware.

Sensors monitored:
  DHT22       → temperature (°C), humidity (%)     [GPIO4]
  NPK RS485   → nitrogen, phosphorus, potassium (mg/kg) [GPIO14/15/17 via MAX485]
  HC-SR04 US1 → tank_level_pct (%)                [GPIO23 TRIG / GPIO24 ECHO]
  HC-SR04 US2 → concentration_pct (%)             [GPIO25 TRIG / GPIO8  ECHO]
"""
import logging

log = logging.getLogger(__name__)


class AlertService:
    def __init__(self, settings):
        # Range thresholds (low, high)
        self.thresholds = {
            "temperature":       (settings.TEMP_MIN,         settings.TEMP_MAX),
            "humidity":          (settings.HUMIDITY_MIN,     settings.HUMIDITY_MAX),
            "tank_level_pct":    (settings.TANK_LEVEL_MIN,   100.0),
            "concentration_pct": (settings.CONCENTRATION_MIN, 100.0),
        }
        # Minimum-only thresholds (no upper bound)
        self.min_only = {
            "nitrogen":   settings.N_MIN,
            "phosphorus": settings.P_MIN,
            "potassium":  settings.K_MIN,
        }

    def check(self, sensor_data: dict) -> list[dict]:
        """
        Returns a list of alert dicts for any out-of-range values.
        Each alert: {"sensor": str, "value": float, "type": str, "threshold": float}
        """
        alerts = []

        for sensor, (low, high) in self.thresholds.items():
            value = sensor_data.get(sensor)
            if value is None:
                continue
            if value < low:
                alerts.append({
                    "sensor": sensor, "value": value,
                    "type": "below_threshold", "threshold": low,
                })
                log.warning("ALERT: %s=%.1f below min %.1f", sensor, value, low)
            elif value > high:
                alerts.append({
                    "sensor": sensor, "value": value,
                    "type": "above_threshold", "threshold": high,
                })

        for sensor, min_val in self.min_only.items():
            value = sensor_data.get(sensor)
            if value is not None and value < min_val:
                alerts.append({
                    "sensor": sensor, "value": value,
                    "type": "below_threshold", "threshold": min_val,
                })
                log.warning("ALERT: %s=%.1f below min %.1f", sensor, value, min_val)

        return alerts
