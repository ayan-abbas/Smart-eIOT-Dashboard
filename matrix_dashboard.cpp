#include <MD_MAX72xx.h>
#include <SPI.h>

#include <WiFi.h>
#include <HTTPClient.h>
#include <WiFiClientSecure.h>

#define HARDWARE_TYPE MD_MAX72XX::FC16_HW
#define MAX_DEVICES 8   // 8 modules total (4 top + 4 bottom)

// ESP32 SPI pins
#define DATA_PIN 23
#define CS_PIN   5
#define CLK_PIN  18

MD_MAX72XX mx = MD_MAX72XX(HARDWARE_TYPE, DATA_PIN, CLK_PIN, CS_PIN, MAX_DEVICES);

// ---- WiFi credentials ----
static const char* WIFI_SSID = "YOUR_WIFI_NAME";
static const char* WIFI_PASSWORD = "YOUR_WIFI_PASSWORD";

// ---- Bulk states endpoint ----
// GET https://itya5y2blk.execute-api.ap-south-1.amazonaws.com/default/device/states?username=...&password=...
static const char* API_BASE = "https://itya5y2blk.execute-api.ap-south-1.amazonaws.com/default";
static const char* USERNAME = "sa3421@srmist.edu.in";
static const char* PASSWORD = "password";

static const uint32_t REFRESH_INTERVAL_MS = 2000;
static const uint32_t WIFI_RETRY_MS = 10000;

static const uint16_t DEVICE_COUNT = 500;   // API returns 1..500
static const uint16_t MATRIX_W = 32;
static const uint16_t MATRIX_H = 16;
static const uint16_t PIXEL_COUNT = MATRIX_W * MATRIX_H; // 512

WiFiClientSecure secureClient;

uint32_t lastRefreshMs = 0;
uint32_t lastWifiRetryMs = 0;

bool deviceStates[DEVICE_COUNT] = {false};

// 🧠 Function to map 2D coordinates (32x16)
void setPixel(int x, int y, bool state) {
  int col, row;

  if (y < 8) {
    // 🔹 Top row (modules 0–3)
    col = x;
    row = y;
  } else {
    // 🔹 Bottom row (modules 4–7)
    col = x + 32;   // shift to next 4 modules
    row = y - 8;
  }

  // 👉 Fix direction (important for correct alignment)
  col = 63 - col;

  mx.setPoint(row, col, state);
}

static bool ensureWifiConnected() {
  if (WiFi.status() == WL_CONNECTED) {
    return true;
  }

  const uint32_t now = millis();
  if (now - lastWifiRetryMs < WIFI_RETRY_MS) {
    return false;
  }
  lastWifiRetryMs = now;

  Serial.println("WiFi disconnected; retrying...");
  WiFi.disconnect();
  WiFi.begin(WIFI_SSID, WIFI_PASSWORD);
  return false;
}

static String buildBulkStatesUrl() {
  String url = String(API_BASE);
  url += "/device/states?username=";
  url += USERNAME;
  url += "&password=";
  url += PASSWORD;
  return url;
}

static bool _waitForStreamData(Stream& stream, uint32_t timeoutMs) {
  const uint32_t start = millis();
  while (stream.available() == 0) {
    if (millis() - start >= timeoutMs) {
      return false;
    }
    delay(1);
  }
  return true;
}

// Extract numeric values from the JSON "states" array into outStates.
// Returns true only if it reads exactly expectedCount values.
static bool parseStatesArrayFromStream(Stream& stream, bool* outStates, size_t expectedCount) {
  const char* key = "\"states\"";
  const size_t keyLen = strlen(key);
  size_t match = 0;

  // Find the "states" key
  {
    const uint32_t start = millis();
    while (true) {
      if (stream.available() == 0) {
        if (millis() - start > 5000) {
          return false;
        }
        delay(1);
        continue;
      }
      const char c = (char)stream.read();
      if (c == key[match]) {
        match++;
        if (match == keyLen) {
          break;
        }
      } else {
        match = (c == key[0]) ? 1 : 0;
      }
    }
  }

  // Find '[' that starts the array
  {
    const uint32_t start = millis();
    while (true) {
      if (stream.available() == 0) {
        if (millis() - start > 5000) {
          return false;
        }
        delay(1);
        continue;
      }
      const char c = (char)stream.read();
      if (c == '[') {
        break;
      }
    }
  }

  size_t count = 0;
  while (count < expectedCount) {
    if (!_waitForStreamData(stream, 5000)) {
      return false;
    }

    // Skip whitespace and commas
    char c = 0;
    do {
      if (!_waitForStreamData(stream, 5000)) {
        return false;
      }
      c = (char)stream.read();
    } while (c == ' ' || c == '\n' || c == '\r' || c == '\t' || c == ',');

    if (c == ']') {
      break;
    }

    if (c == '0' || c == '1') {
      outStates[count] = (c == '1');
      count++;

      // Consume remaining digits if any (defensive)
      while (stream.available() > 0) {
        const char peek = (char)stream.peek();
        if (peek < '0' || peek > '9') {
          break;
        }
        stream.read();
      }
    } else {
      return false;
    }
  }

  return count == expectedCount;
}

static bool fetchAllDeviceStates() {
  const String url = buildBulkStatesUrl();

  HTTPClient http;
  if (!http.begin(secureClient, url)) {
    Serial.println("HTTP begin failed");
    http.end();
    return false;
  }

  const int code = http.GET();
  if (code != 200) {
    Serial.print("Bulk GET failed code=");
    Serial.println(code);
    http.end();
    return false;
  }

  Stream& stream = http.getStream();
  const bool ok = parseStatesArrayFromStream(stream, deviceStates, DEVICE_COUNT);
  http.end();

  if (!ok) {
    Serial.println("Failed to parse states array");
  }
  return ok;
}

static void renderStatesToMatrix() {
  // device 1 -> pixel (0,0), device 2 -> (1,0), ... device 32 -> (31,0), device 33 -> (0,1), ...
  for (uint16_t i = 0; i < PIXEL_COUNT; i++) {
    const uint16_t x = i % MATRIX_W;
    const uint16_t y = i / MATRIX_W;

    bool on = false;
    if (i < DEVICE_COUNT) {
      on = deviceStates[i];
    }
    setPixel((int)x, (int)y, on);
  }
}

void setup() {
  Serial.begin(115200);

  mx.begin();
  mx.control(MD_MAX72XX::INTENSITY, 5);
  mx.clear();

  WiFi.mode(WIFI_STA);
  WiFi.begin(WIFI_SSID, WIFI_PASSWORD);
  Serial.print("Connecting to WiFi");
  while (WiFi.status() != WL_CONNECTED) {
    delay(500);
    Serial.print(".");
  }
  Serial.println("\nWiFi connected");
  Serial.print("IP: ");
  Serial.println(WiFi.localIP());

  secureClient.setInsecure();

  lastRefreshMs = millis() - REFRESH_INTERVAL_MS;
}

void loop() {
  ensureWifiConnected();

  const uint32_t now = millis();
  if (now - lastRefreshMs >= REFRESH_INTERVAL_MS) {
    lastRefreshMs = now;

    if (WiFi.status() == WL_CONNECTED) {
      if (fetchAllDeviceStates()) {
        renderStatesToMatrix();
      }
    }
  }
}