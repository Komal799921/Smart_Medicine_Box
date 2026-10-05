/*
 * ==============================================================================
 * Project: Smart Medicine Box IoT System
 * Target Board: ESP32 Wi-Fi & Bluetooth Development Board
 * Academic Level: Third-Year B.Tech Information Technology Mini Project
 * 
 * Hardware Pin Mapping:
 * ------------------------------------------------------------------------------
 * Component           ESP32 Pin       Interface / Logic
 * ------------------------------------------------------------------------------
 * DS3231 RTC SDA      GPIO 21         I2C Data
 * DS3231 RTC SCL      GPIO 22         I2C Clock
 * 16x2 I2C LCD SDA    GPIO 21         I2C Data (Address 0x27 / 0x3F)
 * 16x2 I2C LCD SCL    GPIO 22         I2C Clock
 * IR Sensor (DO)      GPIO 19         Digital In (LOW = Hand/Object Detected)
 * LDR Sensor (DO)     GPIO 18         Digital In (HIGH = Light / Lid Open)
 * Tilt Sensor (DO)    GPIO 5          Digital In (HIGH = Tilted / Shaken)
 * Active Buzzer       GPIO 25         Digital Out (HIGH = Buzzer ON)
 * Relay Module        GPIO 26         Digital Out (HIGH = Relay Active)
 * Green LED (OK)      GPIO 27         Digital Out (HIGH = ON)
 * Yellow LED (Dose)   GPIO 14         Digital Out (HIGH = ON)
 * Red LED (Alert)     GPIO 12         Digital Out (HIGH = ON)
 * ------------------------------------------------------------------------------
 * Libraries Required (Install via Arduino Library Manager):
 *   1. RTClib by Adafruit
 *   2. LiquidCrystal_I2C by Frank de Brabander / Marco Schwartz
 *   3. BluetoothSerial (Built-in with ESP32 Arduino Core)
 * ==============================================================================
 */

#include <Wire.h>
#include <RTClib.h>
#include <LiquidCrystal_I2C.h>
#include <BluetoothSerial.h>

// ------------------- PIN DEFINITIONS -------------------
#define PIN_IR_SENSOR    19
#define PIN_LDR_SENSOR   18
#define PIN_TILT_SENSOR  5
#define PIN_BUZZER       25
#define PIN_RELAY        26
#define PIN_LED_GREEN    27
#define PIN_LED_YELLOW   14
#define PIN_LED_RED      12

// ------------------- HARDWARE OBJECTS ------------------
RTC_DS3231 rtc;
LiquidCrystal_I2C lcd(0x27, 16, 2); // Default I2C address 0x27 (use 0x3F if blank)
BluetoothSerial SerialBT;

// ------------------- SYSTEM STATES ---------------------
enum SystemState {
  STATE_IDLE,
  STATE_REMINDER,
  STATE_TAKEN,
  STATE_MISSED,
  STATE_LID_OPEN,
  STATE_BOX_MOVED
};

SystemState currentState = STATE_IDLE;

// ------------------- SCHEDULE CONFIGURATION ------------
// Dose schedules in 24-hour format (Hour, Minute)
const int SCHEDULE_MORNING_H   = 8;
const int SCHEDULE_MORNING_M   = 0;
const int SCHEDULE_AFTERNOON_H = 13;
const int SCHEDULE_AFTERNOON_M = 0;
const int SCHEDULE_NIGHT_H     = 20;
const int SCHEDULE_NIGHT_M     = 0;

// Grace period in seconds before marking dosage as missed (e.g., 600s = 10 mins)
const unsigned long GRACE_PERIOD_SEC = 600;

// Timing variables
unsigned long reminderStartTime = 0;
unsigned long lastTelemetryTime  = 0;
unsigned long lastBuzzerToggle   = 0;
bool buzzerBeepState = false;
bool isBuzzerMuted   = false;
int lastTakenDay     = -1;
int lastTakenHour    = -1;

// ------------------- FUNCTION DECLARATIONS -------------
void updateSensorsAndState(DateTime now);
void handleOutputs(DateTime now);
void handleBluetoothCommands();
void sendSerialTelemetry(DateTime now, String statusStr, int alertFlag);
void setLeds(bool red, bool yellow, bool green);
void updateLcd(String line1, String line2);
bool checkSchedule(DateTime now);

// =======================================================
// ARDUINO SETUP
// =======================================================
void setup() {
  // 1. Initialize Hardware Serial for USB Telemetry
  Serial.begin(115200);
  delay(500);
  Serial.println("\n[INIT] Starting Smart Medicine Box...");

  // 2. Initialize GPIO Pins
  pinMode(PIN_IR_SENSOR, INPUT_PULLUP);
  pinMode(PIN_LDR_SENSOR, INPUT);
  pinMode(PIN_TILT_SENSOR, INPUT_PULLUP);

  pinMode(PIN_BUZZER, OUTPUT);
  pinMode(PIN_RELAY, OUTPUT);
  pinMode(PIN_LED_GREEN, OUTPUT);
  pinMode(PIN_LED_YELLOW, OUTPUT);
  pinMode(PIN_LED_RED, OUTPUT);

  // Default Pin States
  digitalWrite(PIN_BUZZER, LOW);
  digitalWrite(PIN_RELAY, LOW);
  setLeds(false, false, true); // Green ON

  // 3. Initialize I2C Bus & LCD
  Wire.begin(21, 22); // SDA = 21, SCL = 22
  lcd.init();
  lcd.backlight();
  lcd.clear();
  lcd.setCursor(0, 0);
  lcd.print("Smart Med Box");
  lcd.setCursor(0, 1);
  lcd.print("Initializing...");

  // 4. Initialize DS3231 RTC
  if (!rtc.begin()) {
    Serial.println("[ERROR] RTC DS3231 not found! Check I2C wiring.");
    lcd.clear();
    lcd.setCursor(0, 0);
    lcd.print("RTC ERROR!");
    delay(2000);
  } else {
    Serial.println("[OK] RTC DS3231 Ready.");
    if (rtc.lostPower()) {
      Serial.println("[RTC] Lost power, setting compilation time...");
      rtc.adjust(DateTime(F(__DATE__), F(__TIME__)));
    }
  }

  // 5. Initialize Bluetooth Serial
  if (!SerialBT.begin("SmartMedicineBox_BT")) {
    Serial.println("[ERROR] Bluetooth initialization failed!");
  } else {
    Serial.println("[OK] Bluetooth Serial Ready: 'SmartMedicineBox_BT'");
  }

  delay(1500);
  lcd.clear();
  Serial.println("[READY] Smart Medicine Box System Ready.");
}

// =======================================================
// MAIN LOOP
// =======================================================
void loop() {
  // Get current RTC time
  DateTime now = rtc.now();

  // Handle incoming Bluetooth commands
  handleBluetoothCommands();

  // Read sensors and evaluate state transitions
  updateSensorsAndState(now);

  // Control LEDs, Buzzer, Relay, and LCD based on state
  handleOutputs(now);

  // Periodic Telemetry Transmission (Every 2 seconds)
  if (millis() - lastTelemetryTime >= 2000) {
    lastTelemetryTime = millis();
    String statusStr = "Monitoring";
    int alertFlag = 0;

    switch (currentState) {
      case STATE_REMINDER:
        statusStr = "Reminder Active";
        alertFlag = 1;
        break;
      case STATE_TAKEN:
        statusStr = "Medicine Taken";
        alertFlag = 0;
        break;
      case STATE_MISSED:
        statusStr = "Medicine Missed";
        alertFlag = 1;
        break;
      case STATE_LID_OPEN:
        statusStr = "Box Open";
        alertFlag = 0;
        break;
      case STATE_BOX_MOVED:
        statusStr = "Box Moved";
        alertFlag = 1;
        break;
      default:
        statusStr = "Monitoring";
        alertFlag = 0;
        break;
    }

    sendSerialTelemetry(now, statusStr, alertFlag);
  }

  delay(50); // Small processing loop delay
}

// =======================================================
// SENSOR PROCESSING & DETECTION LOGIC
// =======================================================
void updateSensorsAndState(DateTime now) {
  // Read Digital Sensor States
  // IR Sensor: Active LOW (0 = Hand present / pill removed)
  int irState = digitalRead(PIN_IR_SENSOR);
  // LDR Sensor: 1 = Light detected (Box lid is open)
  int ldrState = digitalRead(PIN_LDR_SENSOR);
  // Tilt Sensor: 1 = Shaken or tilted
  int tiltState = digitalRead(PIN_TILT_SENSOR);

  // 1. Check if Box is Moved / Shaken (Tamper Priority)
  if (tiltState == HIGH) {
    currentState = STATE_BOX_MOVED;
    return;
  }

  // 2. Check if Scheduled Dose Window has started
  if (checkSchedule(now) && currentState == STATE_IDLE) {
    currentState = STATE_REMINDER;
    reminderStartTime = now.unixtime();
    isBuzzerMuted = false;
  }

  // 3. In Reminder State: Check for Medicine Taken or Timeout (Missed)
  if (currentState == STATE_REMINDER) {
    // If IR detects hand inside (irState == LOW) or Lid is open + IR triggered
    if (irState == LOW) {
      currentState = STATE_TAKEN;
      lastTakenDay = now.day();
      lastTakenHour = now.hour();
      return;
    }

    // Check if grace period expired
    if ((now.unixtime() - reminderStartTime) >= GRACE_PERIOD_SEC) {
      currentState = STATE_MISSED;
      return;
    }
  }

  // 4. In Lid Open State
  if (ldrState == HIGH && currentState == STATE_IDLE) {
    // If lid is opened and hand reaches for pill
    if (irState == LOW) {
      currentState = STATE_TAKEN;
      lastTakenDay = now.day();
      lastTakenHour = now.hour();
    } else {
      currentState = STATE_LID_OPEN;
    }
    return;
  }

  // 5. In Taken State: Return to Idle once lid is closed and IR cleared
  if (currentState == STATE_TAKEN) {
    if (ldrState == LOW && irState == HIGH) {
      // Small debounce delay before reverting to normal monitoring
      delay(2000);
      currentState = STATE_IDLE;
    }
    return;
  }

  // 6. Normal Idle Condition
  if (currentState == STATE_LID_OPEN && ldrState == LOW) {
    currentState = STATE_IDLE;
  }
}

// =======================================================
// OUTPUTS: LEDS, BUZZER, RELAY, LCD DISPLAY
// =======================================================
void handleOutputs(DateTime now) {
  char timeBuffer[17];
  snprintf(timeBuffer, sizeof(timeBuffer), "%02d:%02d:%02d  %02d/%02d",
           now.hour(), now.minute(), now.second(), now.day(), now.month());

  switch (currentState) {
    case STATE_IDLE:
      setLeds(false, false, true); // Green ON
      digitalWrite(PIN_BUZZER, LOW);
      digitalWrite(PIN_RELAY, LOW);
      updateLcd(String(timeBuffer), "Status: READY OK");
      break;

    case STATE_REMINDER:
      setLeds(false, true, false); // Yellow ON
      digitalWrite(PIN_RELAY, HIGH);
      // Intermittent gentle beep pattern (500ms ON / 500ms OFF)
      if (!isBuzzerMuted) {
        if (millis() - lastBuzzerToggle >= 500) {
          lastBuzzerToggle = millis();
          buzzerBeepState = !buzzerBeepState;
          digitalWrite(PIN_BUZZER, buzzerBeepState ? HIGH : LOW);
        }
      } else {
        digitalWrite(PIN_BUZZER, LOW);
      }
      updateLcd(String(timeBuffer), "TAKE MEDICINE!  ");
      break;

    case STATE_TAKEN:
      setLeds(false, false, true); // Green ON
      digitalWrite(PIN_BUZZER, LOW);
      digitalWrite(PIN_RELAY, LOW);
      updateLcd("MEDICINE TAKEN! ", "THANK YOU :)    ");
      break;

    case STATE_MISSED:
      setLeds(true, false, false); // Red ON
      digitalWrite(PIN_RELAY, LOW);
      // Fast urgent alarm beep (200ms ON / 200ms OFF)
      if (!isBuzzerMuted) {
        if (millis() - lastBuzzerToggle >= 200) {
          lastBuzzerToggle = millis();
          buzzerBeepState = !buzzerBeepState;
          digitalWrite(PIN_BUZZER, buzzerBeepState ? HIGH : LOW);
        }
      } else {
        digitalWrite(PIN_BUZZER, LOW);
      }
      updateLcd("ALERT: MISSED!  ", "TAKE DOSE NOW!  ");
      break;

    case STATE_LID_OPEN:
      setLeds(false, true, false); // Yellow ON
      digitalWrite(PIN_BUZZER, LOW);
      digitalWrite(PIN_RELAY, LOW);
      updateLcd(String(timeBuffer), "BOX LID OPEN    ");
      break;

    case STATE_BOX_MOVED:
      setLeds(true, false, false); // Red ON
      if (!isBuzzerMuted) {
        digitalWrite(PIN_BUZZER, HIGH);
      }
      digitalWrite(PIN_RELAY, LOW);
      updateLcd("ALERT: BOX MOVED", "TAMPER DETECTED!");
      break;
  }
}

// =======================================================
// BLUETOOTH SERIAL COMMAND HANDLER
// =======================================================
void handleBluetoothCommands() {
  if (SerialBT.available()) {
    String cmd = SerialBT.readStringUntil('\n');
    cmd.trim();
    cmd.toUpperCase();

    Serial.print("[BT Command Received]: ");
    Serial.println(cmd);

    if (cmd == "STATUS") {
      String statusStr = "NORMAL";
      if (currentState == STATE_REMINDER)  statusStr = "REMINDER_ACTIVE";
      if (currentState == STATE_MISSED)    statusStr = "MEDICINE_MISSED";
      if (currentState == STATE_TAKEN)     statusStr = "MEDICINE_TAKEN";
      if (currentState == STATE_BOX_MOVED) statusStr = "BOX_MOVED";

      SerialBT.print("STATUS: ");
      SerialBT.print(statusStr);
      SerialBT.print(" | BUZZER: ");
      SerialBT.println(isBuzzerMuted ? "MUTED" : "ACTIVE");
    }
    else if (cmd == "BUZZER ON") {
      isBuzzerMuted = false;
      digitalWrite(PIN_BUZZER, HIGH);
      SerialBT.println("ACK: BUZZER TURNED ON");
    }
    else if (cmd == "BUZZER OFF") {
      isBuzzerMuted = true;
      digitalWrite(PIN_BUZZER, LOW);
      SerialBT.println("ACK: BUZZER TURNED OFF");
    }
    else if (cmd == "RESET") {
      currentState = STATE_IDLE;
      isBuzzerMuted = false;
      digitalWrite(PIN_BUZZER, LOW);
      digitalWrite(PIN_RELAY, LOW);
      setLeds(false, false, true);
      SerialBT.println("ACK: SYSTEM ALERTS RESET TO IDLE");
    }
    else if (cmd == "TAKEN") {
      currentState = STATE_TAKEN;
      isBuzzerMuted = true;
      digitalWrite(PIN_BUZZER, LOW);
      SerialBT.println("ACK: RECORDED AS MEDICINE TAKEN");
    }
    else if (cmd == "TIME") {
      DateTime now = rtc.now();
      SerialBT.printf("RTC TIME: %04d-%02d-%02d %02d:%02d:%02d\n",
                      now.year(), now.month(), now.day(), now.hour(), now.minute(), now.second());
    }
    else {
      SerialBT.println("ERR: UNKNOWN COMMAND. Valid: STATUS, BUZZER ON, BUZZER OFF, RESET, TAKEN, TIME");
    }
  }
}

// =======================================================
// HELPER FUNCTIONS
// =======================================================

// Schedule Match Checker
bool checkSchedule(DateTime now) {
  // Prevent multiple triggers in same hour
  if (lastTakenDay == now.day() && lastTakenHour == now.hour()) {
    return false;
  }

  int h = now.hour();
  int m = now.minute();

  if (h == SCHEDULE_MORNING_H && m == SCHEDULE_MORNING_M)   return true;
  if (h == SCHEDULE_AFTERNOON_H && m == SCHEDULE_AFTERNOON_M) return true;
  if (h == SCHEDULE_NIGHT_H && m == SCHEDULE_NIGHT_M)     return true;

  return false;
}

// Control 3 Indicator LEDs
void setLeds(bool red, bool yellow, bool green) {
  digitalWrite(PIN_LED_RED, red ? HIGH : LOW);
  digitalWrite(PIN_LED_YELLOW, yellow ? HIGH : LOW);
  digitalWrite(PIN_LED_GREEN, green ? HIGH : LOW);
}

// Update 16x2 LCD Text Buffer
void updateLcd(String line1, String line2) {
  static String prevLine1 = "";
  static String prevLine2 = "";

  if (line1 != prevLine1 || line2 != prevLine2) {
    lcd.clear();
    lcd.setCursor(0, 0);
    lcd.print(line1);
    lcd.setCursor(0, 1);
    lcd.print(line2);
    prevLine1 = line1;
    prevLine2 = line2;
  }
}

// Send Formatted JSON Telemetry Over USB Serial to Flask
void sendSerialTelemetry(DateTime now, String statusStr, int alertFlag) {
  int irVal = digitalRead(PIN_IR_SENSOR);
  int ldrVal = digitalRead(PIN_LDR_SENSOR);
  int tiltVal = digitalRead(PIN_TILT_SENSOR);

  char timeStr[25];
  snprintf(timeStr, sizeof(timeStr), "%04d-%02d-%02d %02d:%02d:%02d",
           now.year(), now.month(), now.day(), now.hour(), now.minute(), now.second());

  // Output standard JSON string for Flask app
  Serial.print("{\"time\":\"");
  Serial.print(timeStr);
  Serial.print("\",\"ir\":");
  Serial.print(irVal);
  Serial.print(",\"ldr\":");
  Serial.print(ldrVal);
  Serial.print(",\"tilt\":");
  Serial.print(tiltVal);
  Serial.print(",\"status\":\"");
  Serial.print(statusStr);
  Serial.print("\",\"alert\":");
  Serial.print(alertFlag);
  Serial.println("}");
}
