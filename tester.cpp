#define SENSOR A0
#define RELAY D1
int lastUpdated = millis();
bool state = FALSE;

void setup() {
Serial.begin(115200);

pinMode(RELAY, OUTPUT);
digitalWrite(RELAY, HIGH); // Relay OFF (important)


}
void loop() {

    if (millis() - lastUpdated >= 2000) {
        lastUpdated = millis();
        state = !state; // Toggle state
    }

    int value = analogRead(SENSOR);
    Serial.println(value);
    delay(5);


}