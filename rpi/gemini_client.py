# =============================================================================
# gemini_client.py — Gemini 1.5 Flash Vision + Sensor Analysis
#
# Sends: plant image (PIL) + sensor readings as structured text prompt.
# Returns: parsed dict with disease/treatment/pump recommendations
#          compatible with website backend CSV schema and DB models.
# =============================================================================

import json
import re
import logging
from pathlib import Path

import google.generativeai as genai
from PIL import Image

from config import GEMINI_API_KEY, GEMINI_MODEL

logger = logging.getLogger(__name__)

genai.configure(api_key=GEMINI_API_KEY)
_model = genai.GenerativeModel(GEMINI_MODEL)

# Safe default returned on any parse / API failure
_SAFE_DEFAULT = {
    "disease":                "unknown",
    "severity":               "none",
    "confidence":             0.0,
    "treatment":              "Unable to analyse. Manual inspection recommended.",
    "pump_a":                 0,
    "pump_b":                 0,
    "main_pump":              0,
    "spray_duration_seconds": 0,
    "notes":                  "Gemini response could not be parsed.",
}

# Prompt instructs Gemini to return ONLY the JSON we need.
# Field names match the RPi CSV headers AND the website DB models:
#   pump_a, pump_b, main_pump  → NodeMCU L298N / relay control
#   spray_duration_seconds      → written as spray_duration_s in CSV
_PROMPT_TEMPLATE = """You are an expert agricultural AI assistant.
Analyse the provided plant image together with the sensor data below, then return a JSON response ONLY — no markdown, no code fences, no extra text.

Sensor readings:
- Temperature     : {temp} °C          (DHT22 · GPIO4)
- Humidity        : {humidity} %        (DHT22 · GPIO4)
- Nitrogen  (N)   : {N} mg/kg          (NPK RS485)
- Phosphorus (P)  : {P} mg/kg          (NPK RS485)
- Potassium  (K)  : {K} mg/kg          (NPK RS485)
- Tank level      : {tank_level} %      (HC-SR04 US1 · GPIO23/24)
- Mix concentration: {concentration} %  (HC-SR04 US2 · GPIO25/8)

Hardware note:
- pump_a   controls L298N IN1 (D3)  — small mixing pump A
- pump_b   controls L298N IN3 (D7)  — small mixing pump B
- main_pump controls relay   (D4)  — main 12V spray pump (active-LOW relay)

Respond ONLY with this exact JSON structure:
{{
  "disease": "disease name or 'healthy'",
  "severity": "none | mild | moderate | severe",
  "confidence": 0.0,
  "treatment": "specific actionable treatment recommendation",
  "pump_a": 0,
  "pump_b": 0,
  "main_pump": 0,
  "spray_duration_seconds": 0,
  "notes": "any additional observation"
}}"""


def _build_prompt(sensor_data: dict) -> str:
    return _PROMPT_TEMPLATE.format(
        temp          = sensor_data.get("temperature",   "N/A"),
        humidity      = sensor_data.get("humidity",      "N/A"),
        N             = sensor_data.get("N",             "N/A"),
        P             = sensor_data.get("P",             "N/A"),
        K             = sensor_data.get("K",             "N/A"),
        tank_level    = sensor_data.get("tank_level",    "N/A"),
        concentration = sensor_data.get("concentration", "N/A"),
    )


def _extract_json(raw: str) -> dict:
    """Robustly extract JSON from Gemini response."""
    clean = re.sub(r"```(?:json)?", "", raw, flags=re.IGNORECASE).strip()
    try:
        return json.loads(clean)
    except json.JSONDecodeError:
        pass
    match = re.search(r"\{.*\}", clean, re.DOTALL)
    if match:
        try:
            return json.loads(match.group())
        except json.JSONDecodeError:
            pass
    raise ValueError(f"No valid JSON found in Gemini response:\n{raw[:500]}")


def _validate(data: dict) -> dict:
    """Overlay parsed values onto safe defaults and enforce types."""
    validated = dict(_SAFE_DEFAULT)
    validated.update(data)
    validated["confidence"]            = float(max(0.0, min(1.0, validated.get("confidence", 0.0))))
    validated["pump_a"]                = int(bool(validated.get("pump_a", 0)))
    validated["pump_b"]                = int(bool(validated.get("pump_b", 0)))
    validated["main_pump"]             = int(bool(validated.get("main_pump", 0)))
    validated["spray_duration_seconds"] = max(0, int(validated.get("spray_duration_seconds", 0)))
    return validated


def analyse(image_path: str, sensor_data: dict) -> dict:
    """
    Main entry point.
    Args:
        image_path:  Path to captured JPEG from Pi Camera v2 (CSI ribbon).
        sensor_data: Dict with keys: temperature, humidity, N, P, K,
                     tank_level, concentration.
    Returns:
        Validated dict compatible with:
          - RPi CSV columns  (via main.py _log_to_csv)
          - Website backend DB models (SensorReading, DiseaseResult)
          - NodeMCU serial commands (pump_a, pump_b, main_pump)
    """
    if not Path(image_path).exists():
        logger.error("Image not found: %s", image_path)
        result = dict(_SAFE_DEFAULT)
        result["notes"] = f"Image file not found: {image_path}"
        return result

    try:
        image  = Image.open(image_path)
        prompt = _build_prompt(sensor_data)

        logger.info("Sending image + sensor data to Gemini (%s)…", GEMINI_MODEL)
        response = _model.generate_content([prompt, image])
        raw_text = response.text
        logger.debug("Gemini raw: %s", raw_text[:300])

        parsed    = _extract_json(raw_text)
        validated = _validate(parsed)

        logger.info(
            "Gemini → disease: %s | severity: %s | confidence: %.2f | "
            "pump_a: %d | pump_b: %d | main_pump: %d | spray: %ds",
            validated["disease"], validated["severity"], validated["confidence"],
            validated["pump_a"], validated["pump_b"], validated["main_pump"],
            validated["spray_duration_seconds"],
        )
        return validated

    except Exception as e:
        logger.error("Gemini analysis failed: %s", e)
        result = dict(_SAFE_DEFAULT)
        result["notes"] = f"Gemini error: {e}"
        return result


# --- Quick self-test ---
if __name__ == "__main__":
    import sys
    logging.basicConfig(level=logging.DEBUG)
    test_image = sys.argv[1] if len(sys.argv) > 1 else "/tmp/plant_capture.jpg"
    test_sensors = {
        "temperature": 28.5, "humidity": 72.0,
        "N": 42, "P": 18, "K": 55,
        "tank_level": 80.0, "concentration": 65.0,
    }
    result = analyse(test_image, test_sensors)
    print(json.dumps(result, indent=2))
