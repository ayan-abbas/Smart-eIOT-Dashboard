#include <ESP8266WiFi.h>
#include <ESP8266HTTPClient.h>
#include <WiFiClientSecure.h>

const char* ssid = "YOUR_WIFI_NAME";
const char* password = "YOUR_WIFI_PASSWORD";

String postUrl = "https://82ekr32yn2.execute-api.us-east-1.amazonaws.com/device/data";
String getUrl = "https://82ekr32yn2.execute-api.us-east-1.amazonaws.com/device/state/1?username=sa3421@srmist.edu.in&password=password";

unsigned long lastPost = 0;
unsigned long lastGet = 0;

WiFiClientSecure client;

void setup() {
  Serial.begin(115200);

  WiFi.begin(ssid, password);
  Serial.print("Connecting");

  while (WiFi.status() != WL_CONNECTED) {
    delay(500);
    Serial.print(".");
  }

  Serial.println("\nWiFi Connected");

  client.setInsecure();  // skip SSL certificate verification
}

void loop() {

  unsigned long now = millis();

  // -------- GET STATE EVERY 5s --------
  if (now - lastGet >= 5000) {

    if (WiFi.status() == WL_CONNECTED) {

      HTTPClient http;
      http.begin(client, getUrl);

      int code = http.GET();

      if (code > 0) {
        Serial.println(http.getString());
      } else {
        Serial.print("GET Error: ");
        Serial.println(code);
      }

      http.end();
    }

    lastGet = now;
  }


  // -------- POST DATA EVERY 10s --------
  if (now - lastPost >= 10000) {

    if (WiFi.status() == WL_CONNECTED) {

      HTTPClient http;
      http.begin(client, postUrl);
      http.addHeader("Content-Type", "application/json");

      int wattage = random(0, 101);

      String json = "{";
      json += "\"username\":\"sa3421@srmist.edu.in\",";
      json += "\"password\":\"password\",";
      json += "\"device_id\":1,";
      json += "\"wattage\":" + String(wattage);
      json += "}";

      int code = http.POST(json);

      Serial.print("POST wattage: ");
      Serial.println(wattage);

      if (code > 0) {
        Serial.println(http.getString());
      } else {
        Serial.print("POST Error: ");
        Serial.println(code);
      }

      http.end();
    }

    lastPost = now;
  }
}