#define SENSOR A0
#define RELAY  D1

int lastUpdated = 0;
bool state = LOW;

const int samples = 500;
float offset = 5;   // Midpoint for ESP32 ADC

void setup() {
    Serial.begin(115200);

    pinMode(RELAY, OUTPUT);
    digitalWrite(RELAY, HIGH); // Relay OFF

    lastUpdated = millis();
}

void loop() {

    // 🔁 Relay toggle every 2 sec
    if (millis() - lastUpdated >= 2000) {
        lastUpdated = millis();

        if (state) {
            digitalWrite(RELAY, HIGH); // OFF
            state = LOW;
        } else {
            digitalWrite(RELAY, LOW);  // ON
            state = HIGH;
        }
    }

    // ⚡ Peak detection (instead of RMS)
    int maxValue = 0;

    for (int i = 0; i < samples; i++) {
        int value = analogRead(SENSOR);
        int centered = abs(value - offset)/2; // remove DC bias

        if (centered > maxValue) {
            maxValue = centered;
        }
    }

    Serial.print("Peak Value: ");
    Serial.println(maxValue);

    delay(500);
}