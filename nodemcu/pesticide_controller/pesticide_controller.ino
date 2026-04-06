// =============================================================================
// pesticide_controller.ino — NodeMCU v3 ESP8266 Firmware
// Team OJAS · NIT Hamirpur · Dept. of Electrical Engineering
// Faculty: Dr. Katam Nishanth
//
// Peripheral controller for Intelligent Pesticide Sprinkling System.
// Communicates with Raspberry Pi 4 via USB serial (115200 baud).
//
// ─── HARDWARE WIRING (from "NodeMCU v3 ESP8266 — Complete Pin-by-Pin
//     Wiring Reference", Team OJAS · NIT Hamirpur) ──────────────────────────
//
//  NodeMCU Pin │ GPIO  │ Connected To             │ Notes
//  ────────────┼───────┼──────────────────────────┼─────────────────────────
//  D0          │ 16    │ Red LED via 220 Ω        │ HIGH=ON; no PWM on GPIO16
//  D1          │ 5     │ OLED SCL                 │ I2C clock (Wire.begin)
//  D2          │ 4     │ OLED SDA                 │ I2C data  (Wire.begin)
//  D3          │ 0     │ L298N IN1 (Pump A)       │ Boot HIGH → add 10kΩ
//              │       │                          │ pull-down on L298N IN1
//  D4          │ 2     │ Relay IN (main pump)     │ Boot HIGH → relay OFF
//              │       │                          │ (active-LOW relay = safe)
//  D5          │ 14    │ Yellow LED via 220 Ω     │ HIGH=ON
//  D6          │ 12    │ Green LED via 220 Ω      │ HIGH=ON
//  D7          │ 13    │ L298N IN3 (Pump B)       │ Boot LOW → Pump B OFF
//  D8          │ 15    │ 10kΩ → GND               │ MUST be LOW at boot;
//              │       │                          │ not used as output
//  TX/RX       │ 1/3   │ USB serial → RPi         │ /dev/ttyUSB0, 115200 baud
//
//  L298N connections:
//    IN1 ← D3 (GPIO0) │ IN2 ← GND (permanent) │ ENA ← 3.3V (always enabled)
//    IN3 ← D7 (GPIO13)│ IN4 ← GND (permanent) │ ENB ← 3.3V (always enabled)
//    VCC ← 12V battery│ GND ← common GND
//    OUT1/OUT2 → Pump A +/–  │  OUT3/OUT4 → Pump B +/–
//
//  Relay module:
//    VCC ← NodeMCU VIN (5V)  │ GND ← common GND
//    IN  ← D4 (GPIO2, active-LOW: LOW=relay ON, HIGH=relay OFF)
//    COM ← 12V battery +     │ NO → Main pump + wire
//    Main pump – → 12V battery –
//
//  OLED (SSD1306 / SH1106 128×64 I2C):
//    GND ← NodeMCU GND  │ VCC ← NodeMCU 3V3
//    SCL ← D1 (GPIO5)   │ SDA ← D2 (GPIO4)
//    I2C address: 0x3C
//
//  Status LEDs (all via 220 Ω series resistor):
//    Red    → D0 (GPIO16) → GND
//    Yellow → D5 (GPIO14) → GND
//    Green  → D6 (GPIO12) → GND
//
// ─── SERIAL PROTOCOL (JSON, newline-terminated, 115200 baud) ─────────────────
//
//  RPi → NodeMCU:
//    {"cmd":"PUMP_A",    "state":1}          → L298N IN1 (D3)
//    {"cmd":"PUMP_B",    "state":0}          → L298N IN3 (D7)
//    {"cmd":"MAIN_PUMP", "state":1}          → Relay IN  (D4, active-LOW)
//    {"cmd":"LED",       "color":"green"}    → red|yellow|green|off
//    {"cmd":"OLED","line1":"…","line2":"…","line3":"…","line4":"…"}
//    {"cmd":"STATUS"}
//
//  NodeMCU → RPi:
//    {"status":"OK","pump_a":0,"pump_b":0,"main_pump":0,"led":"green"}
//    {"status":"BOOT_OK","msg":"NodeMCU ready"}
//    {"status":"ERROR","msg":"…"}
//
// ─── DESIGN RULES ────────────────────────────────────────────────────────────
//   • Completely non-blocking — NO delay() in main loop (only in setup)
//   • 10-second watchdog: if RPi silent → red LED flash + OLED warning
//   • Holds last known pump state on watchdog (no abrupt shutdown mid-spray)
// =============================================================================

#include <Wire.h>
#include <Adafruit_GFX.h>
#include <Adafruit_SSD1306.h>
#include <ArduinoJson.h>

// ─── Pin Definitions (NodeMCU v3 silkscreen labels) ──────────────────────────
#define PIN_LED_RED     D0    // GPIO16 — Red LED via 220Ω; no PWM on GPIO16
#define PIN_OLED_SCL    D1    // GPIO5  — I2C SCL (handled by Wire.begin)
#define PIN_OLED_SDA    D2    // GPIO4  — I2C SDA (handled by Wire.begin)
#define PIN_PUMP_A      D3    // GPIO0  — L298N IN1; 10kΩ pull-down on IN1 for boot safety
#define PIN_RELAY       D4    // GPIO2  — Relay IN; active-LOW; HIGH at boot = relay OFF
#define PIN_LED_YELLOW  D5    // GPIO14 — Yellow LED via 220Ω
#define PIN_LED_GREEN   D6    // GPIO12 — Green LED via 220Ω
#define PIN_PUMP_B      D7    // GPIO13 — L298N IN3; LOW at boot = Pump B OFF (safe)
// D8 (GPIO15) is tied to GND via 10kΩ — MUST be LOW at boot — NOT used as output

// ─── OLED Configuration ───────────────────────────────────────────────────────
#define OLED_WIDTH   128
#define OLED_HEIGHT   64
#define OLED_ADDR    0x3C    // Standard I2C address; try 0x3D if display is blank
#define OLED_RESET    -1     // No dedicated reset pin on I2C module

Adafruit_SSD1306 oled(OLED_WIDTH, OLED_HEIGHT, &Wire, OLED_RESET);
bool oledOk = false;

// ─── Watchdog ─────────────────────────────────────────────────────────────────
#define WATCHDOG_MS  10000UL    // 10 seconds — matches NODEMCU_WATCHDOG_SECONDS in RPi config
unsigned long lastCmdTime = 0;
bool watchdogFired        = false;

// ─── System State ─────────────────────────────────────────────────────────────
struct State {
  bool   pumpA    = false;
  bool   pumpB    = false;
  bool   mainPump = false;
  String led      = "off";    // "red" | "yellow" | "green" | "off"
} state;

// ─── OLED Lines ───────────────────────────────────────────────────────────────
String oledLines[4] = {"", "", "", ""};

// ─── OLED Helper ──────────────────────────────────────────────────────────────
void oledShow() {
  if (!oledOk) return;
  oled.clearDisplay();
  oled.setTextSize(1);
  oled.setTextColor(SSD1306_WHITE);
  for (int i = 0; i < 4; i++) {
    oled.setCursor(0, i * 16);
    oled.print(oledLines[i].substring(0, 21));   // 21 chars max at 6×8 font
  }
  oled.display();
}

void oledMsg(const String& l1, const String& l2 = "",
             const String& l3 = "", const String& l4 = "") {
  oledLines[0] = l1;
  oledLines[1] = l2;
  oledLines[2] = l3;
  oledLines[3] = l4;
  oledShow();
}

// ─── LED Control ─────────────────────────────────────────────────────────────
// Only one LED lit at a time (matching RPi nodemcu_serial.py set_led logic).
// GPIO16 (D0) has no PWM — simple digital ON/OFF only.
void setLed(const String& color) {
  digitalWrite(PIN_LED_RED,    LOW);
  digitalWrite(PIN_LED_YELLOW, LOW);
  digitalWrite(PIN_LED_GREEN,  LOW);

  if      (color == "red")    digitalWrite(PIN_LED_RED,    HIGH);
  else if (color == "yellow") digitalWrite(PIN_LED_YELLOW, HIGH);
  else if (color == "green")  digitalWrite(PIN_LED_GREEN,  HIGH);
  // "off" → all remain LOW

  state.led = color;
}

// ─── Pump A Control ───────────────────────────────────────────────────────────
// D3 (GPIO0): HIGH = Pump A ON (L298N IN1 HIGH, IN2 tied GND → forward)
// BOOT SAFETY: 10kΩ pull-down on L298N IN1 prevents boot pulse from starting pump.
void setPumpA(bool on) {
  digitalWrite(PIN_PUMP_A, on ? HIGH : LOW);
  state.pumpA = on;
}

// ─── Pump B Control ───────────────────────────────────────────────────────────
// D7 (GPIO13): HIGH = Pump B ON (L298N IN3 HIGH, IN4 tied GND → forward)
// Boot state LOW → Pump B is safely OFF during boot.
void setPumpB(bool on) {
  digitalWrite(PIN_PUMP_B, on ? HIGH : LOW);
  state.pumpB = on;
}

// ─── Main Spray Relay Control ─────────────────────────────────────────────────
// D4 (GPIO2): Active-LOW relay. LOW = relay ON = pump runs. HIGH = relay OFF.
// Boot state HIGH → relay stays OFF during boot (safe).
// Relay COM → 12V battery +; Relay NO → Main pump + wire.
void setMainPump(bool on) {
  digitalWrite(PIN_RELAY, on ? LOW : HIGH);    // active-LOW: LOW=ON, HIGH=OFF
  state.mainPump = on;
}

// ─── Status Response ──────────────────────────────────────────────────────────
void sendStatus(bool ok = true, const String& msg = "") {
  StaticJsonDocument<256> doc;
  if (ok) {
    doc["status"]    = "OK";
    doc["pump_a"]    = state.pumpA    ? 1 : 0;
    doc["pump_b"]    = state.pumpB    ? 1 : 0;
    doc["main_pump"] = state.mainPump ? 1 : 0;
    doc["led"]       = state.led;
  } else {
    doc["status"] = "ERROR";
    doc["msg"]    = msg;
  }
  serializeJson(doc, Serial);
  Serial.println();
}

// ─── Command Dispatcher ───────────────────────────────────────────────────────
void handleCommand(const String& raw) {
  StaticJsonDocument<512> doc;
  DeserializationError err = deserializeJson(doc, raw);

  if (err) {
    sendStatus(false, String("JSON parse error: ") + err.c_str());
    return;
  }

  // Reset watchdog on every valid command
  lastCmdTime   = millis();
  watchdogFired = false;

  const char* cmd = doc["cmd"] | "";

  // ── PUMP_A ── L298N IN1 (D3/GPIO0)
  if (strcmp(cmd, "PUMP_A") == 0) {
    setPumpA(doc["state"] == 1);
    sendStatus();

  // ── PUMP_B ── L298N IN3 (D7/GPIO13)
  } else if (strcmp(cmd, "PUMP_B") == 0) {
    setPumpB(doc["state"] == 1);
    sendStatus();

  // ── MAIN_PUMP ── Relay IN (D4/GPIO2, active-LOW)
  } else if (strcmp(cmd, "MAIN_PUMP") == 0) {
    setMainPump(doc["state"] == 1);
    sendStatus();

  // ── LED ── Red(D0) | Yellow(D5) | Green(D6) | off
  } else if (strcmp(cmd, "LED") == 0) {
    const char* color = doc["color"] | "off";
    setLed(String(color));
    sendStatus();

  // ── OLED ── SSD1306 128×64 I2C on D1/D2 (GPIO5/GPIO4), addr 0x3C
  } else if (strcmp(cmd, "OLED") == 0) {
    oledLines[0] = doc["line1"] | "";
    oledLines[1] = doc["line2"] | "";
    oledLines[2] = doc["line3"] | "";
    oledLines[3] = doc["line4"] | "";
    oledShow();
    sendStatus();

  // ── STATUS ── return current state of all outputs
  } else if (strcmp(cmd, "STATUS") == 0) {
    sendStatus();

  } else {
    sendStatus(false, String("Unknown cmd: ") + cmd);
  }
}

// ─── Non-blocking Serial Accumulator ─────────────────────────────────────────
String serialBuf = "";

void checkSerial() {
  while (Serial.available()) {
    char c = (char)Serial.read();
    if (c == '\n' || c == '\r') {
      serialBuf.trim();
      if (serialBuf.length() > 0) {
        handleCommand(serialBuf);
        serialBuf = "";
      }
    } else {
      if (serialBuf.length() < 512) serialBuf += c;
    }
  }
}

// ─── Watchdog Check ───────────────────────────────────────────────────────────
// Matches NODEMCU_WATCHDOG_SECONDS = 10 in RPi config.py.
// Holds last pump state — does NOT force outputs off (safe: no mid-spray abort).
void checkWatchdog() {
  if (!watchdogFired && (millis() - lastCmdTime) > WATCHDOG_MS) {
    watchdogFired = true;
    setLed("red");
    oledMsg("RPi TIMEOUT", "Holding last state", "Check USB cable", "");
    // Pump states held — no change to setPumpA/B/setMainPump
  }
}

// ─── setup() ─────────────────────────────────────────────────────────────────
void setup() {
  Serial.begin(115200);
  Serial.println();   // flush any boot garbage on TX line

  // ── LEDs: output, default LOW (off) ──────────────────────────────────────
  pinMode(PIN_LED_RED,    OUTPUT); digitalWrite(PIN_LED_RED,    LOW);
  pinMode(PIN_LED_YELLOW, OUTPUT); digitalWrite(PIN_LED_YELLOW, LOW);
  pinMode(PIN_LED_GREEN,  OUTPUT); digitalWrite(PIN_LED_GREEN,  LOW);

  // ── Pump A (D3 / GPIO0) ──────────────────────────────────────────────────
  // GPIO0 has internal pull-up → HIGH at boot.
  // The 10kΩ pull-down on L298N IN1 holds IN1 LOW during boot preventing
  // accidental pump activation. We take over GPIO immediately after boot.
  pinMode(PIN_PUMP_A, OUTPUT);
  digitalWrite(PIN_PUMP_A, LOW);   // ensure IN1 is LOW under firmware control

  // ── Main Relay (D4 / GPIO2) ──────────────────────────────────────────────
  // GPIO2 has internal pull-up → HIGH at boot.
  // Active-LOW relay: HIGH = relay OFF → pump off during boot (safe).
  pinMode(PIN_RELAY, OUTPUT);
  digitalWrite(PIN_RELAY, HIGH);   // HIGH = relay OFF

  // ── Pump B (D7 / GPIO13) ─────────────────────────────────────────────────
  // GPIO13 is LOW at boot → Pump B is already OFF at boot (safe).
  pinMode(PIN_PUMP_B, OUTPUT);
  digitalWrite(PIN_PUMP_B, LOW);

  // ── OLED (I2C: SDA=D2/GPIO4, SCL=D1/GPIO5, addr=0x3C) ───────────────────
  Wire.begin(D2, D1);    // Wire.begin(SDA, SCL) — D2=GPIO4, D1=GPIO5
  if (oled.begin(SSD1306_SWITCHCAPVCC, OLED_ADDR)) {
    oledOk = true;
    oled.clearDisplay();
    oled.display();
    oledMsg("Team OJAS", "NIT Hamirpur", "System READY", "");
  }
  // If OLED init fails, system still works — serial comms + pumps function normally

  // ── Boot LED sequence: yellow → green ────────────────────────────────────
  setLed("yellow");
  delay(500);     // single delay in setup only — acceptable
  setLed("green");

  lastCmdTime = millis();

  // Announce readiness to RPi
  StaticJsonDocument<128> boot;
  boot["status"] = "BOOT_OK";
  boot["msg"]    = "NodeMCU ready";
  serializeJson(boot, Serial);
  Serial.println();
}

// ─── loop() — completely non-blocking ────────────────────────────────────────
void loop() {
  checkSerial();
  checkWatchdog();
  // Future: add millis()-based periodic tasks here
}
