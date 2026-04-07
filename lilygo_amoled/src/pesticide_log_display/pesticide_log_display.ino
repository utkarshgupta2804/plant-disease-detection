// =============================================================================
// pesticide_log_display.ino  v3.0
// Team OJAS · NIT Hamirpur · Intelligent Pesticide System
// Faculty: Dr. Katam Nishanth
//
// APPROACH: TFT_eSPI Sprite (framebuffer) → amoled.pushColors()
//   • Zero LVGL — eliminates ALL color format / byte-swap issues
//   • TFT_eSPI draws into PSRAM sprite, pushColors sends it to RM67162
//   • This is the exact pattern from official LilyGo TFT_eSPI_Sprite example
//
// Required libs  (install via Arduino Library Manager):
//   • LilyGo-AMOLED-Series  (latest)
//   • TFT_eSPI               (bundled in LilyGo libdeps — use THAT copy)
//   • ArduinoJson 6.x
//
// Board settings:
//   Board   : ESP32S3 Dev Module
//   PSRAM   : OPI PSRAM  ← REQUIRED
//   Flash   : 16 MB (128Mb)
//   USB CDC on Boot: Enabled
// =============================================================================

#include <Arduino.h>
#include <LilyGo_AMOLED.h>
#include <TFT_eSPI.h>
#include <ArduinoJson.h>

// ─── Hardware ─────────────────────────────────────────────────────────────────
LilyGo_Class  amoled;
TFT_eSPI       tft   = TFT_eSPI();
TFT_eSprite    spr   = TFT_eSprite(&tft);   // full-screen PSRAM framebuffer

#define W  536
#define H  240

// ─── Layout constants ─────────────────────────────────────────────────────────
#define BAR_H       74    // top status bar height
#define LOG_Y       (BAR_H + 1)
#define LOG_LINE_H  21    // pixel height per log row  (fits font size 2)
#define MAX_LOGS    ((H - LOG_Y) / LOG_LINE_H)   // = 7

// ─── Colour palette (RGB565) ──────────────────────────────────────────────────
// Use TFT_eSPI's colour macro:  tft.color565(r,g,b)
// Pre-computed here for speed:
#define C_BLACK      0x0000
#define C_BG         0x0882   // #0D1208 → near-black green
#define C_SURFACE    0x1129   // #122116 → dark green surface
#define C_BORDER     0x1CA3   // #1A3A1A
#define C_GREEN_BR   0x57E8   // #50E048  bright green (pump on / ready)
#define C_GREEN_MID  0x4DC3   // #4DB828  mid green
#define C_GREEN_DIM  0x2582   // #244810  dim green text
#define C_AMBER_BR   0xFDC0   // #FDB800
#define C_AMBER_DIM  0x8480   // #844000
#define C_RED_BR     0xF820   // #FF0400
#define C_RED_MID    0xE040   // #E00800
#define C_TEAL       0x07D5   // #00FAA8
#define C_WHITE      0xFFFF
#define C_LGREY      0x8C51   // #8C8A88
#define C_DGREY      0x2965   // #294CA8  — not used, kept for reference

// Severity badge colours
struct SevColors { uint16_t bg, border, text; };
SevColors sevNone     = {0x0100, 0x0D00, 0x3DE0};  // dark-green bg, green text
SevColors sevMild     = {0x2100, 0x4200, 0xFDC0};  // dark-amber bg, amber text
SevColors sevModerate = {0x3100, 0x6200, 0xFCA0};
SevColors sevSevere   = {0x4000, 0x8000, 0xF820};  // dark-red bg, red text

// ─── State ────────────────────────────────────────────────────────────────────
struct SystemStatus {
    String  disease   = "Awaiting RPi...";
    String  severity  = "none";
    bool    pump_a    = false;
    bool    pump_b    = false;
    bool    main_pump = false;
    float   temp      = -99;
    float   humidity  = -99;
    float   tank      = -99;
    float   conc      = -99;
} sys;

// Circular log ring buffer
#define LOG_BUF  48
struct LogLine { String text; uint16_t color; };
LogLine  logRing[LOG_BUF];
int      logHead  = 0;
int      logCount = 0;

String   rxBuf   = "";
uint32_t uptimeSec = 0;
bool     needsRedraw = true;

// ─── Helpers ──────────────────────────────────────────────────────────────────
String fmtF(float v, int d = 1) {
    if (v < -90) return "---";
    char b[12]; snprintf(b, sizeof(b), "%.*f", d, v); return b;
}
String fmtUptime(uint32_t s) {
    char b[12];
    snprintf(b, sizeof(b), "%02lu:%02lu:%02lu",
             s/3600, (s%3600)/60, s%60);
    return b;
}
SevColors pickSev() {
    if (sys.severity == "severe")   return sevSevere;
    if (sys.severity == "moderate") return sevModerate;
    if (sys.severity == "mild")     return sevMild;
    return sevNone;
}
String sevLabel() {
    String s = sys.severity; s.toUpperCase(); return s;
}

// ─── Log functions ────────────────────────────────────────────────────────────
void pushLog(const String &txt, uint16_t col) {
    logRing[logHead] = {txt, col};
    logHead = (logHead + 1) % LOG_BUF;
    if (logCount < LOG_BUF) logCount++;
    needsRedraw = true;
}

// ─── Draw routines ────────────────────────────────────────────────────────────

// Draw a filled rounded-rect badge with centred text
void drawBadge(int x, int y, int w, int h, int r,
               uint16_t bg, uint16_t border, uint16_t fg,
               const String &label, uint8_t fontSz)
{
    spr.fillRoundRect(x, y, w, h, r, bg);
    spr.drawRoundRect(x, y, w, h, r, border);
    spr.setTextColor(fg, bg);
    spr.setTextSize(fontSz);
    spr.setTextDatum(MC_DATUM);
    spr.drawString(label, x + w/2, y + h/2);
    spr.setTextDatum(TL_DATUM);
}

// Draw pump indicator dot with label below
void drawPump(int cx, int cy, bool on, bool isMain, const char *lbl) {
    uint16_t col = on ? (isMain ? C_RED_BR : C_GREEN_BR) : C_SURFACE;
    uint16_t bcol = on ? (isMain ? C_RED_MID : C_GREEN_MID) : C_BORDER;
    spr.fillCircle(cx, cy, 6, col);
    spr.drawCircle(cx, cy, 6, bcol);
    spr.setTextColor(on ? C_LGREY : C_GREEN_DIM, C_BLACK);
    spr.setTextSize(1);
    spr.setTextDatum(MC_DATUM);
    spr.drawString(lbl, cx, cy + 11);
    spr.setTextDatum(TL_DATUM);
}

// Draw a metric (small label + large value)
void drawMetric(int x, int y, const char *cap, const String &val,
                uint16_t valCol, uint8_t valSz = 2)
{
    spr.setTextColor(C_GREEN_DIM, C_BLACK);
    spr.setTextSize(1);
    spr.drawString(cap, x, y);
    spr.setTextColor(valCol, C_BLACK);
    spr.setTextSize(valSz);
    spr.drawString(val, x, y + 10);
}

// Full frame render
void renderFrame() {
    spr.fillSprite(C_BLACK);  // clears entire framebuffer

    // ── Status bar background ────────────────────────────────────────────
    spr.fillRect(0, 0, W, BAR_H, C_SURFACE);
    spr.drawRect(0, 0, W, BAR_H, C_BORDER);

    // ── Left block: disease name ─────────────────────────────────────────
    spr.setTextColor(C_GREEN_DIM, C_SURFACE);
    spr.setTextSize(1);
    spr.drawString("DISEASE DETECTED", 8, 6);

    spr.setTextColor(C_WHITE, C_SURFACE);
    spr.setTextSize(2);
    // Clip name to fit — max ~22 chars at size 2 on 340px wide space
    String dname = sys.disease;
    if (dname.length() > 22) dname = dname.substring(0, 21) + ".";
    spr.drawString(dname, 8, 22);

    // ── Left block: sensor row ───────────────────────────────────────────
    // Size-2 font = 12px wide per char, 16px tall
    drawMetric(8,   48, "TEMP",    fmtF(sys.temp) + "C",  C_AMBER_BR);
    drawMetric(108, 48, "HUM",     fmtF(sys.humidity)+"%", C_TEAL);
    drawMetric(198, 48, "TANK",
               fmtF(sys.tank) + "%",
               (sys.tank >= 0 && sys.tank < 15) ? C_RED_BR : C_GREEN_MID);
    drawMetric(288, 48, "MIX",     fmtF(sys.conc)+"%",    C_GREEN_MID);

    // ── Right block: severity badge ──────────────────────────────────────
    SevColors sc = pickSev();
    drawBadge(376, 6, 148, 28, 4,
              sc.bg, sc.border, sc.text, sevLabel(), 2);

    // ── Right block: uptime ──────────────────────────────────────────────
    spr.setTextColor(C_GREEN_DIM, C_SURFACE);
    spr.setTextSize(1);
    spr.setTextDatum(TR_DATUM);
    spr.drawString(fmtUptime(uptimeSec), W - 8, 40);
    spr.setTextDatum(TL_DATUM);

    // ── Right block: pump dots ───────────────────────────────────────────
    drawPump(396, 56, sys.pump_a,    false, "PA");
    drawPump(430, 56, sys.pump_b,    false, "PB");
    drawPump(464, 56, sys.main_pump, true,  "MN");

    // ── Separator line ───────────────────────────────────────────────────
    spr.drawFastHLine(0, BAR_H, W, C_BORDER);

    // ── Log area ─────────────────────────────────────────────────────────
    int visible = min(logCount, MAX_LOGS);
    int startIdx = (logHead - visible + LOG_BUF) % LOG_BUF;

    for (int i = 0; i < MAX_LOGS; i++) {
        int ly = LOG_Y + i * LOG_LINE_H + 2;
        if (i < visible) {
            int idx = (startIdx + i) % LOG_BUF;
            spr.setTextColor(logRing[idx].color, C_BLACK);
            spr.setTextSize(1);
            // Use drawString at larger custom font if available,
            // or default font — still readable at 536px width
            spr.setTextFont(2);   // TFT_eSPI font 2 = 16px clean
            spr.drawString(logRing[idx].text, 6, ly);
        }
    }

    // Dim "TEAM OJAS" watermark at bottom-right (subtle branding)
    spr.setTextColor(0x0882, C_BLACK);  // nearly invisible on black
    spr.setTextSize(1);
    spr.setTextFont(1);
    spr.setTextDatum(BR_DATUM);
    spr.drawString("OJAS v3 NIT-H", W - 2, H - 1);
    spr.setTextDatum(TL_DATUM);

    // ── Push to display ──────────────────────────────────────────────────
    amoled.pushColors(0, 0, W, H, (uint16_t *)spr.getPointer());
}

// ─── JSON parser ──────────────────────────────────────────────────────────────
bool parseJson(const String &raw) {
    StaticJsonDocument<512> doc;
    if (deserializeJson(doc, raw) != DeserializationError::Ok) return false;
    if (!doc.containsKey("lilygo")) return false;

    sys.disease   = doc["disease"]   | "Unknown";
    sys.severity  = doc["severity"]  | "none";
    sys.pump_a    = doc["pump_a"]    | 0;
    sys.pump_b    = doc["pump_b"]    | 0;
    sys.main_pump = doc["main_pump"] | 0;
    sys.temp      = doc["temp"]      | -99.0f;
    sys.humidity  = doc["humidity"]  | -99.0f;
    sys.tank      = doc["tank"]      | -99.0f;
    sys.conc      = doc["conc"]      | -99.0f;
    return true;
}

// ─── Colour picker for log lines ──────────────────────────────────────────────
uint16_t logColor(const String &line) {
    if (line.indexOf("[ERROR]")  >= 0 || line.indexOf("FAIL")     >= 0 ||
        line.indexOf("severe")   >= 0 || line.indexOf("CRITICAL")  >= 0)
        return C_RED_BR;
    if (line.indexOf("[WARN]")   >= 0 || line.indexOf("moderate") >= 0 ||
        line.indexOf("mild")     >= 0)
        return C_AMBER_BR;
    if (line.indexOf("READY")    >= 0 || line.indexOf("healthy")  >= 0 ||
        line.indexOf("Spray OFF")>= 0 || line.indexOf("DONE")     >= 0)
        return C_GREEN_BR;
    if (line.indexOf("GEMINI")   >= 0 || line.indexOf("Gemini")   >= 0 ||
        line.indexOf("[DIAG]")   >= 0)
        return C_TEAL;
    if (line.indexOf("[STATUS]") >= 0)
        return C_GREEN_MID;
    if (line.startsWith("===") || line.startsWith("▸"))
        return C_GREEN_BR;
    return C_GREEN_DIM;
}

// ─── Serial reader ─────────────────────────────────────────────────────────────
void checkSerial() {
    while (Serial.available()) {
        char c = (char)Serial.read();
        if (c == '\n' || c == '\r') {
            rxBuf.trim();
            if (rxBuf.length() > 0) {
                if (rxBuf.startsWith("{")) {
                    if (parseJson(rxBuf)) {
                        // Build a compact status log line
                        String sline = "[STATUS] " + sys.disease
                            + " | " + sys.severity
                            + " | T:" + fmtF(sys.temp)
                            + " H:" + fmtF(sys.humidity) + "%";
                        pushLog(sline, logColor(sline));
                    } else {
                        pushLog(rxBuf, C_AMBER_DIM);
                    }
                } else {
                    pushLog(rxBuf, logColor(rxBuf));
                }
                rxBuf = "";
                needsRedraw = true;
            }
        } else {
            if (rxBuf.length() < 512) rxBuf += c;
        }
    }
}

// ─── setup() ──────────────────────────────────────────────────────────────────
void setup() {
    Serial.begin(115200);

    // Init display
    if (!amoled.begin()) {
        Serial.println("AMOLED init failed");
        while (1) delay(500);
    }
    amoled.setBrightness(200);

    // Create full-screen sprite in PSRAM
    // 536 × 240 × 2 bytes = 257,280 bytes — fine for 8 MB OPI PSRAM
    spr.setColorDepth(16);
    spr.createSprite(W, H);
    spr.setSwapBytes(true);   // ← KEY: matches RM67162 byte order

    // Splash: black screen immediately so no garbage visible
    spr.fillSprite(C_BLACK);
    amoled.pushColors(0, 0, W, H, (uint16_t *)spr.getPointer());

    // Initial log messages
    pushLog("▸ Team OJAS  NIT Hamirpur", C_GREEN_BR);
    pushLog("  Intelligent Pesticide System v3.0", C_GREEN_DIM);
    pushLog("  TFT_eSPI Sprite Display READY", C_GREEN_BR);
    pushLog("  Waiting for RPi log stream...", C_GREEN_DIM);
    pushLog("  /dev/ttyUSB1 @ 115200", C_GREEN_DIM);

    renderFrame();
}

// ─── loop() ───────────────────────────────────────────────────────────────────
void loop() {
    checkSerial();

    // Update uptime every second
    static uint32_t lastSec = 0;
    if (millis() - lastSec >= 1000) {
        lastSec = millis();
        uptimeSec++;
        needsRedraw = true;
    }

    // Only redraw when something changed — saves power, prevents flicker
    if (needsRedraw) {
        renderFrame();
        needsRedraw = false;
    }

    delay(10);
}