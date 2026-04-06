# =============================================================================
# config.py — Intelligent Pesticide Sprinkling System
# Team OJAS · NIT Hamirpur · Dept. of Electrical Engineering
# Faculty: Dr. Katam Nishanth
#
# Pin assignments verified against:
#   "NodeMCU v3 ESP8266 — Complete Pin-by-Pin Wiring Reference"
#   Team OJAS · NIT Hamirpur
# =============================================================================

import os
from dotenv import load_dotenv

load_dotenv()

# --- Gemini API ---
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "YOUR_GEMINI_API_KEY_HERE")
GEMINI_MODEL   = "gemini-1.5-flash"

# --- Serial (RPi ↔ NodeMCU via USB-A → Micro-USB) ---
# RPi USB-A port → NodeMCU Micro-USB = /dev/ttyUSB0 @ 115200 baud
SERIAL_PORT    = os.getenv("SERIAL_PORT", "/dev/ttyUSB0")
SERIAL_BAUD    = 115200
SERIAL_TIMEOUT = 2          # seconds read timeout

# --- DHT22 (Temperature & Humidity) ---
# DHT22 Pin 2 (DATA) → RPi GPIO4 / Pin 7
# DHT22 Pin 1 (VCC)  → RPi Pin 1 (3.3V)
# DHT22 Pin 4 (GND)  → RPi GND
# 10 kΩ pull-up between VCC and DATA — mandatory
DHT22_PIN = 4               # BCM GPIO4 (physical Pin 7)

# --- NPK Soil Sensor via MAX485 RS485-to-TTL Converter ---
# MAX485 DI  (Pin 4) → RPi GPIO14 / Pin 8  (UART TX — Modbus commands out)
# MAX485 RO  (Pin 1) → RPi GPIO15 / Pin 10 (UART RX — NPK data in)
# MAX485 DE+RE (Pins 2+3 tied) → RPi GPIO17 / Pin 11 (direction: HIGH=TX, LOW=RX)
# MAX485 VCC (Pin 8) → RPi 3.3V (Pin 1)
# MAX485 GND (Pin 5) → RPi GND
# NPK Brown  (+12V)  → 12V battery +
# NPK Black  (GND)   → 12V battery –
# NPK Yellow (A+)    → MAX485 Pin A
# NPK Blue   (B–)    → MAX485 Pin B
NPK_PORT      = "/dev/ttyAMA0"   # UART on GPIO14/15
NPK_BAUD      = 9600
NPK_SLAVE_ID  = 1
NPK_DE_RE_PIN = 17               # BCM GPIO17 (Pin 11) — DE+RE direction ctrl

# --- Ultrasonic Sensor 1 (Pesticide Tank Level) ---
# US1 VCC  → RPi Pin 2 (5V)
# US1 TRIG → RPi GPIO23 / Pin 16
# US1 ECHO → 1kΩ → GPIO24 / Pin 18 → 2kΩ → GND  (voltage divider: 5V → ~3.33V)
# US1 GND  → RPi GND
US1_TRIG            = 23          # BCM GPIO23 (Pin 16)
US1_ECHO            = 24          # BCM GPIO24 (Pin 18) — after 1kΩ+2kΩ divider
US1_MAX_DISTANCE_CM = 30          # physical tank height in cm
US1_EMPTY_CM        = 28          # sensor reading when tank is empty
US1_FULL_CM         = 3           # sensor reading when tank is full

# --- Ultrasonic Sensor 2 (Mix Concentration Level) ---
# US2 VCC  → RPi Pin 4 (5V)
# US2 TRIG → RPi GPIO25 / Pin 22
# US2 ECHO → 1kΩ → GPIO8 / Pin 24 → 2kΩ → GND  (voltage divider: 5V → ~3.33V)
# US2 GND  → RPi GND
US2_TRIG            = 25          # BCM GPIO25 (Pin 22)
US2_ECHO            = 8           # BCM GPIO8  (Pin 24) — after 1kΩ+2kΩ divider
US2_MAX_DISTANCE_CM = 20
US2_EMPTY_CM        = 18
US2_FULL_CM         = 2

# --- Pi Camera v2 (CSI ribbon → RPi CSI port) ---
# Enable: sudo raspi-config → Interface Options → Camera → Enable
CAMERA_RESOLUTION  = (1920, 1080)
CAMERA_CAPTURE_PATH = "/tmp/plant_capture.jpg"

# --- CSV Log (tailed by the website backend's CSVWatcher) ---
LOG_FILE = "/home/pi/pesticide_log.csv"

# --- Main loop timing ---
LOOP_INTERVAL_SECONDS = 30        # how often the main loop runs

# --- Alert thresholds ---
MIN_TANK_LEVEL_PCT    = 15        # warn (and alert NodeMCU OLED) below this %
MIN_CONCENTRATION_PCT = 10        # warn below this %

# --- NodeMCU watchdog ---
# NodeMCU holds last pump state if no command arrives within 10 seconds
NODEMCU_WATCHDOG_SECONDS = 10
