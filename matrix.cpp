
#include <Arduino.h>
#include <WiFi.h>
#include <HTTPClient.h>
#include <WiFiClientSecure.h>

// ---- WiFi credentials ----
static const char* WIFI_SSID = "YOUR_WIFI_NAME";
static const char* WIFI_PASSWORD = "YOUR_WIFI_PASSWORD";

// ---- Auth (query params) ----
static const char* USERNAME = "sa3421@srmist.edu.in";
static const char* PASSWORD = "password";

// ---- API base ----
// New backend endpoint: GET /device/states?username=...&password=...
static const char* API_BASE = "https://itya5y2blk.execute-api.ap-south-1.amazonaws.com/default";

// ---- Device range to store locally ----
static const uint16_t DEVICE_ID_START = 1;
static const uint16_t DEVICE_ID_END = 500;

// ---- Scheduling ----
static const uint32_t REFRESH_INTERVAL_MS = 5000;
static const uint32_t WIFI_RETRY_MS = 10000;

static_assert(DEVICE_ID_END >= DEVICE_ID_START, "Invalid device id range");
static const uint16_t DEVICE_COUNT = (DEVICE_ID_END - DEVICE_ID_START + 1);

WiFiClientSecure secureClient;
bool deviceStates[DEVICE_COUNT] = {false};

uint32_t lastWifiRetryMs = 0;
uint32_t lastRefreshMs = 0;

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
	url += "/device/states";
	url += "?username=";
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

// Parses JSON and extracts the numeric values from the "states" array.
// Expected: "states": [0,1,0,...]
// Fills outStates[0..expectedCount-1]. Returns true only if it read expectedCount values.
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

	// Find the '[' that starts the array
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

	// Read array values
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

			// Consume any remaining digits (defensive, though we expect only 0/1)
			while (stream.available() > 0) {
				const char peek = (char)stream.peek();
				if (peek < '0' || peek > '9') {
					break;
				}
				stream.read();
			}
		} else {
			// Unexpected token
			return false;
		}
	}

	return count == expectedCount;
}

static bool fetchAllStatesOnce() {
	const String url = buildBulkStatesUrl();

	HTTPClient http;
	if (!http.begin(secureClient, url)) {
		Serial.println("HTTP begin failed");
		http.end();
		return false;
	}

	const int code = http.GET();
	if (code <= 0) {
		Serial.print("Bulk GET failed code=");
		Serial.println(code);
		http.end();
		return false;
	}

	// Clear before parsing (if parse fails, we'll keep them off)
	for (uint16_t i = 0; i < DEVICE_COUNT; i++) {
		deviceStates[i] = false;
	}

	Stream& stream = http.getStream();
	const bool ok = parseStatesArrayFromStream(stream, deviceStates, DEVICE_COUNT);
	http.end();

	if (!ok) {
		Serial.println("Failed to parse states array");
		return false;
	}

	return true;
}

static void printSummary() {
	uint16_t onCount = 0;
	for (uint16_t i = 0; i < DEVICE_COUNT; i++) {
		if (deviceStates[i]) {
			onCount++;
		}
	}
	Serial.print("Devices ON: ");
	Serial.print(onCount);
	Serial.print(" / ");
	Serial.println(DEVICE_COUNT);
}

void setup() {
	Serial.begin(115200);
	delay(200);

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

	// HTTPS: skip SSL certificate verification
	secureClient.setInsecure();

	// Start immediately
	lastRefreshMs = millis() - REFRESH_INTERVAL_MS;
}

void loop() {
	const uint32_t now = millis();

	ensureWifiConnected();
	if (WiFi.status() != WL_CONNECTED) {
		return;
	}

	if (now - lastRefreshMs >= REFRESH_INTERVAL_MS) {
		lastRefreshMs = now;
		Serial.println("--- Refreshing all device states (bulk) ---");
		if (fetchAllStatesOnce()) {
			printSummary();
		}
	}
}

