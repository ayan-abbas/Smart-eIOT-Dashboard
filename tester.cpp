#include <Arduino.h>

#include <ESP8266WiFi.h>
#include <ESP8266HTTPClient.h>

#include <WiFiClientSecure.h>

#define SENSOR A0
#define RELAY  D1

// ---- WiFi credentials ----
const char* WIFI_SSID = "YOUR_WIFI_NAME";
const char* WIFI_PASSWORD = "YOUR_WIFI_PASSWORD";

// ---- API endpoints (from get_test1.http / put_test1.http) ----
static const char* GET_URL = "https://itya5y2blk.execute-api.ap-south-1.amazonaws.com/default/device/state/1?username=sa3421@srmist.edu.in&password=password";
static const char* DATA_URL = "https://itya5y2blk.execute-api.ap-south-1.amazonaws.com/default/device/data";

static const char* USERNAME = "sa3421@srmist.edu.in";
static const char* PASSWORD = "password";
static const int DEVICE_ID = 1;

// Timers
static const uint32_t GET_INTERVAL_MS = 2000;
static const uint32_t POST_INTERVAL_MS = 2000;
static const uint32_t WIFI_RETRY_MS = 10000;

WiFiClientSecure secureClient;

uint32_t lastGetMs = 0;
uint32_t lastPostMs = 0;
uint32_t lastWifiRetryMs = 0;

int lastAppliedState = -1; // unknown

static void applyRelayState(int state) {
    // Keep existing relay polarity: HIGH = OFF, LOW = ON
    if (state == 1) {
        digitalWrite(RELAY, LOW);
    } else {
        digitalWrite(RELAY, HIGH);
    }
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

static int parseStateFromJson(const String& payload, bool& ok) {
    ok = false;

    int keyPos = payload.indexOf("\"state\"");
    if (keyPos < 0) {
        keyPos = payload.indexOf("state");
    }
    if (keyPos < 0) {
        return 0;
    }

    const int colonPos = payload.indexOf(':', keyPos);
    if (colonPos < 0) {
        return 0;
    }

    int i = colonPos + 1;
    while (i < (int)payload.length() && (payload[i] == ' ' || payload[i] == '\n' || payload[i] == '\r' || payload[i] == '\t')) {
        i++;
    }
    if (i >= (int)payload.length()) {
        return 0;
    }

    if (payload[i] == '0' || payload[i] == '1') {
        ok = true;
        return payload[i] - '0';
    }

    return 0;
}

static int readWattageFromSensor() {
    // Using the existing “peak detection” approach. Returned value is used as the wattage field.
    // If you have a specific sensor scaling (ACS712/PZEM/etc), we can replace this with a real W calculation.
    const int samples = 500;

    const int offset = 5;

    int maxValue = 0;
    for (int i = 0; i < samples; i++) {
        const int value = analogRead(SENSOR);
        const int centered = abs(value - offset);
        if (centered > maxValue) {
            maxValue = centered;
        }
        delayMicroseconds(200);
    }

    // Minimal guard: treat maxValue as “wattage” for now.
    return maxValue;
}

void setup() {
    Serial.begin(115200);
    delay(200);

    pinMode(RELAY, OUTPUT);
    digitalWrite(RELAY, HIGH); // Relay OFF by default

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

    // HTTPS: skip SSL certificate verification (matches your existing approach)
    secureClient.setInsecure();
}

void loop() {
    const uint32_t now = millis();

    // Keep trying to reconnect if WiFi drops.
    ensureWifiConnected();

    // -------- GET STATE EVERY 5s --------
    if (now - lastGetMs >= GET_INTERVAL_MS) {
        lastGetMs = now;

        if (WiFi.status() == WL_CONNECTED) {
            HTTPClient http;
            http.begin(secureClient, GET_URL);

            const int code = http.GET();
            if (code > 0) {
                const String body = http.getString();
                bool ok = false;
                const int serverState = parseStateFromJson(body, ok);

                Serial.print("GET state code=");
                Serial.print(code);
                Serial.print(" body=");
                Serial.println(body);

                if (ok && serverState != lastAppliedState) {
                    lastAppliedState = serverState;
                    applyRelayState(serverState);
                    Serial.print("Relay updated from server state: ");
                    Serial.println(serverState);
                }
            } else {
                Serial.print("GET Error: ");
                Serial.println(code);
            }

            http.end();
        }
    }

    // -------- POST POWER USAGE EVERY 10s --------
    if (now - lastPostMs >= POST_INTERVAL_MS) {
        lastPostMs = now;

        if (WiFi.status() == WL_CONNECTED) {
            const int wattage = readWattageFromSensor();

            HTTPClient http;
            http.begin(secureClient, DATA_URL);
            http.addHeader("Content-Type", "application/json");

            String json = "{";
            json += "\"username\":\"" + String(USERNAME) + "\",";
            json += "\"password\":\"" + String(PASSWORD) + "\",";
            json += "\"device_id\":" + String(DEVICE_ID) + ",";
            json += "\"wattage\":" + String(wattage);
            json += "}";

            const int code = http.POST(json);
            Serial.print("POST wattage: ");
            Serial.print(wattage);
            Serial.print(" code=");
            Serial.println(code);

            if (code > 0) {
                Serial.println(http.getString());
            } else {
                Serial.print("POST Error: ");
                Serial.println(code);
            }

            http.end();
        }
    }
}