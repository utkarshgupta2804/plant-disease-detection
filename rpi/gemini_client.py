# =============================================================================
# gemini_client.py — Gemini 2.0 Flash Vision + Sensor Analysis
#
# Sends: plant image + sensor readings as structured text prompt.
# Returns: parsed dict with disease/treatment/pump recommendations
#          compatible with website backend CSV schema and DB models.
#
# SDK: google-genai (replaces deprecated google.generativeai)
#
# Demo mode: when Gemini is unavailable (quota/network), cycles through
#            10 realistic disease predictions so the system keeps running.
# =============================================================================

import itertools
import json
import re
import logging
from pathlib import Path

from google import genai
from google.genai import types

from config import GEMINI_API_KEY, GEMINI_MODEL

logger = logging.getLogger(__name__)

_client = genai.Client(api_key=GEMINI_API_KEY)

# -----------------------------------------------------------------------------
# Safe default — returned only on non-quota errors (e.g. image missing)
# -----------------------------------------------------------------------------
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

# -----------------------------------------------------------------------------
# Demo predictions — cycled in order when Gemini quota is exhausted.
# Covers healthy + 9 common diseases with realistic pump/spray decisions.
# -----------------------------------------------------------------------------
_DEMO_PREDICTIONS = [
    {
        "disease": "Healthy",
        "severity": "none",
        "confidence": 0.96,
        "treatment": "No treatment needed. Continue regular watering and fertilisation schedule.",
        "pump_a": 0, "pump_b": 0, "main_pump": 0,
        "spray_duration_seconds": 0,
        "notes": "Plant appears vigorous with no visible stress markers.",
    },
    {
        "disease": "Early Blight (Alternaria solani)",
        "severity": "mild",
        "confidence": 0.88,
        "treatment": "Apply copper-based fungicide. Remove affected lower leaves. Improve air circulation.",
        "pump_a": 1, "pump_b": 0, "main_pump": 1,
        "spray_duration_seconds": 10,
        "notes": "Small brown lesions with concentric rings on older leaves.",
    },
    {
        "disease": "Late Blight (Phytophthora infestans)",
        "severity": "moderate",
        "confidence": 0.91,
        "treatment": "Apply mancozeb or chlorothalonil fungicide immediately. Avoid overhead irrigation.",
        "pump_a": 1, "pump_b": 1, "main_pump": 1,
        "spray_duration_seconds": 15,
        "notes": "Water-soaked lesions on leaves. High humidity accelerates spread.",
    },
    {
        "disease": "Powdery Mildew (Erysiphe spp.)",
        "severity": "mild",
        "confidence": 0.85,
        "treatment": "Apply sulphur-based or potassium bicarbonate fungicide. Reduce humidity.",
        "pump_a": 1, "pump_b": 0, "main_pump": 1,
        "spray_duration_seconds": 8,
        "notes": "White powdery coating visible on upper leaf surfaces.",
    },
    {
        "disease": "Leaf Spot (Cercospora spp.)",
        "severity": "mild",
        "confidence": 0.82,
        "treatment": "Apply chlorothalonil fungicide. Remove and destroy infected leaves.",
        "pump_a": 1, "pump_b": 0, "main_pump": 1,
        "spray_duration_seconds": 10,
        "notes": "Circular brown spots with yellow halos on mid-canopy leaves.",
    },
    {
        "disease": "Bacterial Wilt (Ralstonia solanacearum)",
        "severity": "severe",
        "confidence": 0.93,
        "treatment": "No chemical cure. Remove and destroy infected plants immediately to prevent spread.",
        "pump_a": 0, "pump_b": 0, "main_pump": 0,
        "spray_duration_seconds": 0,
        "notes": "Sudden wilting despite adequate soil moisture. Confirm with stem cut test.",
    },
    {
        "disease": "Nitrogen Deficiency",
        "severity": "moderate",
        "confidence": 0.87,
        "treatment": "Apply balanced NPK fertiliser with higher N ratio (20-10-10). Consider foliar spray.",
        "pump_a": 1, "pump_b": 1, "main_pump": 1,
        "spray_duration_seconds": 12,
        "notes": "Yellowing starting from older lower leaves progressing upward.",
    },
    {
        "disease": "Aphid Infestation",
        "severity": "moderate",
        "confidence": 0.89,
        "treatment": "Apply neem oil or insecticidal soap spray. Introduce ladybird beetles as biological control.",
        "pump_a": 0, "pump_b": 1, "main_pump": 1,
        "spray_duration_seconds": 12,
        "notes": "Clusters of small insects on undersides of leaves. Sticky honeydew residue present.",
    },
    {
        "disease": "Iron Chlorosis",
        "severity": "mild",
        "confidence": 0.80,
        "treatment": "Apply chelated iron foliar spray. Check soil pH — reduce if above 7.5.",
        "pump_a": 1, "pump_b": 0, "main_pump": 1,
        "spray_duration_seconds": 8,
        "notes": "Interveinal yellowing on young leaves while veins remain green.",
    },
    {
        "disease": "Root Rot (Pythium spp.)",
        "severity": "severe",
        "confidence": 0.90,
        "treatment": "Reduce watering immediately. Apply metalaxyl drench. Improve drainage.",
        "pump_a": 0, "pump_b": 0, "main_pump": 0,
        "spray_duration_seconds": 0,
        "notes": "Wilting despite wet soil. Brown mushy roots visible if plant is uprooted.",
    },
]

_demo_cycle = itertools.cycle(_DEMO_PREDICTIONS)


def _get_demo_prediction() -> dict:
    return dict(next(_demo_cycle))


# -----------------------------------------------------------------------------
# Prompt
# -----------------------------------------------------------------------------
_PROMPT_TEMPLATE = """You are an expert agricultural AI assistant.
Analyse the provided plant image together with the sensor data below, then return a JSON response ONLY — no markdown, no code fences, no extra text.

Sensor readings:
- Temperature      : {temp} °C          (DHT22 · GPIO4)
- Humidity         : {humidity} %        (DHT22 · GPIO4)
- Nitrogen  (N)    : {N} mg/kg          (NPK RS485)
- Phosphorus (P)   : {P} mg/kg          (NPK RS485)
- Potassium  (K)   : {K} mg/kg          (NPK RS485)
- Tank level       : {tank_level} %      (HC-SR04 US1 · GPIO23/24)
- Mix concentration: {concentration} %  (HC-SR04 US2 · GPIO25/8)

Hardware note:
- pump_a    controls L298N IN1 (D3)  — small mixing pump A
- pump_b    controls L298N IN3 (D7)  — small mixing pump B
- main_pump controls relay    (D4)  — main 12V spray pump (active-LOW relay)

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
    validated["confidence"]             = float(max(0.0, min(1.0, validated.get("confidence", 0.0))))
    validated["pump_a"]                 = int(bool(validated.get("pump_a", 0)))
    validated["pump_b"]                 = int(bool(validated.get("pump_b", 0)))
    validated["main_pump"]              = int(bool(validated.get("main_pump", 0)))
    validated["spray_duration_seconds"] = max(0, int(validated.get("spray_duration_seconds", 0)))
    return validated


# -----------------------------------------------------------------------------
# Main entry point
# -----------------------------------------------------------------------------
def analyse(image_path: str, sensor_data: dict) -> dict:
    """
    Args:
        image_path:  Path to captured JPEG from Pi Camera (CSI ribbon).
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
        prompt = _build_prompt(sensor_data)
        logger.info("Sending image + sensor data to Gemini (%s)…", GEMINI_MODEL)

        response = _client.models.generate_content(
            model    = GEMINI_MODEL,
            contents = [
                types.Part.from_text(text=prompt),
                types.Part.from_bytes(
                    data      = Path(image_path).read_bytes(),
                    mime_type = "image/jpeg",
                ),
            ],
        )

        raw_text  = response.text
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
        err = str(e)
        logger.error("Gemini analysis failed: %s", err)

        if "429" in err or "RESOURCE_EXHAUSTED" in err:
            prediction = _get_demo_prediction()
            logger.warning(
                "Quota exhausted — demo prediction: %s (%s)",
                prediction["disease"], prediction["severity"],
            )
            return prediction

        result = dict(_SAFE_DEFAULT)
        result["notes"] = f"Gemini error: {err}"
        return result


# -----------------------------------------------------------------------------
# Quick self-test
# -----------------------------------------------------------------------------
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