"""
Detection Logic Module for Smart Medicine Box IoT Project.
Analyzes sensor inputs (IR, LDR, Tilt) and RTC timing against schedules
to classify states: Medicine Taken, Medicine Missed, Box Open, Box Moved, and Normal Monitoring.
"""

from datetime import datetime, timedelta

class MedicineDetectionEngine:
    def __init__(self):
        # Current system state
        self.current_status = "Monitoring"
        self.alert_active = False
        self.active_reminder = None
        self.reminder_start_time = None
        self.grace_period_seconds = 600  # 10-minute window for demo (configurable)
        self.last_taken_time = None
        self.last_ir_state = 1
        self.last_ldr_state = 0
        self.last_tilt_state = 0

        # Output states for actuators
        self.led_state = {"red": False, "yellow": False, "green": True}
        self.buzzer_state = False
        self.relay_state = False
        self.lcd_line1 = "Smart Med Box"
        self.lcd_line2 = "Status: OK"

    def set_reminder(self, dose_name="Morning Dose"):
        """Activates a scheduled medication reminder."""
        self.active_reminder = dose_name
        self.reminder_start_time = datetime.now()
        self.current_status = "Reminder Active"
        self.alert_active = True
        self.led_state = {"red": False, "yellow": True, "green": False}
        self.buzzer_state = True
        self.relay_state = True
        self.lcd_line1 = f"TIME: {datetime.now().strftime('%H:%M:%S')}"
        self.lcd_line2 = "PLEASE TAKE MED!"

    def check_schedule_match(self, current_dt=None):
        """
        Checks if current time matches standard reminder schedules:
        Morning: 08:00, Afternoon: 13:00, Night: 20:00
        """
        if current_dt is None:
            current_dt = datetime.now()

        current_time_str = current_dt.strftime("%H:%M")
        
        # Prevent re-triggering if already taken recently within 1 hour
        if self.last_taken_time:
            diff = (current_dt - self.last_taken_time).total_seconds()
            if diff < 3600:
                return None

        if current_time_str == "08:00" and self.active_reminder != "Morning Dose":
            return "Morning Dose"
        elif current_time_str == "13:00" and self.active_reminder != "Afternoon Dose":
            return "Afternoon Dose"
        elif current_time_str == "20:00" and self.active_reminder != "Night Dose":
            return "Night Dose"

        return None

    def process_reading(self, ir=1, ldr=0, tilt=0, timestamp=None, manual_event=None):
        """
        Core detection rule engine.
        
        Sensor Definitions:
          - IR = 0: Object/Hand detected inside medicine slot (Active Low)
          - IR = 1: Clear / No hand
          - LDR = 1 (or raw high): Box lid is OPEN (Light detected)
          - LDR = 0: Box lid is CLOSED (Dark inside)
          - Tilt = 1: Box is shaken, moved, or tilted
          - Tilt = 0: Box is stable and level
        """
        now = datetime.now()
        time_display = now.strftime('%H:%M:%S')

        # Convert to standard integer flags
        ir_flag = int(ir)
        ldr_flag = int(ldr)
        tilt_flag = int(tilt)

        notes = ""

        # 1. Handle Manual or External Event Overrides
        if manual_event == "take_medicine":
            ir_flag = 0
            ldr_flag = 1
        elif manual_event == "open_box":
            ldr_flag = 1
        elif manual_event == "tilt_box":
            tilt_flag = 1
        elif manual_event == "trigger_missed":
            self.current_status = "Medicine Missed"
            self.alert_active = True
            self.led_state = {"red": True, "yellow": False, "green": False}
            self.buzzer_state = True
            self.relay_state = False
            self.lcd_line1 = f"TIME: {time_display}"
            self.lcd_line2 = "ALERT: MED MISSED"
            return self._build_result("Medicine Missed", "User/System triggered missed dose alert", ir_flag, ldr_flag, tilt_flag)
        elif manual_event == "reset":
            return self.reset()

        # 2. Check Automatic Scheduled Reminders
        scheduled_slot = self.check_schedule_match(now)
        if scheduled_slot and not self.active_reminder:
            self.set_reminder(scheduled_slot)

        # 3. Check for Timeout -> Medicine Missed
        if self.active_reminder and self.reminder_start_time:
            elapsed_sec = (now - self.reminder_start_time).total_seconds()
            if elapsed_sec > self.grace_period_seconds:
                # Patient missed the dosage window
                self.current_status = "Medicine Missed"
                self.alert_active = True
                self.led_state = {"red": True, "yellow": False, "green": False}
                self.buzzer_state = True
                self.relay_state = False
                self.lcd_line1 = f"TIME: {time_display}"
                self.lcd_line2 = "ALERT: MED MISSED"
                notes = f"{self.active_reminder} missed (Exceeded {int(self.grace_period_seconds / 60)} min window)"
                self.active_reminder = None
                return self._build_result("Medicine Missed", notes, ir_flag, ldr_flag, tilt_flag)

        # 4. Condition A: Box Moved / Shaken / Tampered (Tilt Sensor Triggered)
        if tilt_flag == 1:
            self.current_status = "Box Moved"
            self.alert_active = True
            self.led_state = {"red": True, "yellow": False, "green": False}
            self.buzzer_state = True
            self.lcd_line1 = f"TIME: {time_display}"
            self.lcd_line2 = "ALERT: BOX MOVED!"
            notes = "Tilt sensor detected movement or displacement"
            return self._build_result("Box Moved", notes, ir_flag, ldr_flag, tilt_flag)

        # 5. Condition B: Medicine Taken (IR Triggered with Lid Open or active reminder)
        # When IR = 0, hand is reaching into pill compartment
        if ir_flag == 0:
            self.current_status = "Medicine Taken"
            self.alert_active = False
            self.active_reminder = None
            self.reminder_start_time = None
            self.last_taken_time = now
            self.led_state = {"red": False, "yellow": False, "green": True}
            self.buzzer_state = False
            self.relay_state = False
            self.lcd_line1 = f"TIME: {time_display}"
            self.lcd_line2 = "MEDICINE TAKEN :)"
            notes = "IR proximity detected hand pill retrieval"
            return self._build_result("Medicine Taken", notes, ir_flag, ldr_flag, tilt_flag)

        # 6. Condition C: Box Open (LDR Sensor Triggered)
        if ldr_flag == 1:
            self.current_status = "Box Open"
            # Keep alert false unless missed
            self.led_state = {"red": False, "yellow": True, "green": False}
            self.buzzer_state = False
            self.lcd_line1 = f"TIME: {time_display}"
            self.lcd_line2 = "LID OPEN: TAKE PILL"
            notes = "LDR detected light inside box"
            return self._build_result("Box Open", notes, ir_flag, ldr_flag, tilt_flag)

        # 7. Condition D: Active Reminder in progress (Waiting for patient)
        if self.active_reminder:
            self.current_status = "Reminder Active"
            self.alert_active = True
            self.led_state = {"red": False, "yellow": True, "green": False}
            self.buzzer_state = True
            self.lcd_line1 = f"TIME: {time_display}"
            self.lcd_line2 = f"TAKE: {self.active_reminder[:10]}"
            notes = f"Reminder active for {self.active_reminder}"
            return self._build_result("Reminder Active", notes, ir_flag, ldr_flag, tilt_flag)

        # 8. Normal Standby Monitoring State
        self.current_status = "Monitoring"
        self.alert_active = False
        self.led_state = {"red": False, "yellow": False, "green": True}
        self.buzzer_state = False
        self.relay_state = False
        self.lcd_line1 = f"SmartMed {time_display}"
        self.lcd_line2 = "System Ready - OK"
        notes = "All sensors nominal, box closed and secure"

        return self._build_result("Monitoring", notes, ir_flag, ldr_flag, tilt_flag)

    def reset(self):
        """Resets alarms and sets the system back to normal monitoring."""
        now = datetime.now()
        time_display = now.strftime('%H:%M:%S')
        self.current_status = "Monitoring"
        self.alert_active = False
        self.active_reminder = None
        self.reminder_start_time = None
        self.led_state = {"red": False, "yellow": False, "green": True}
        self.buzzer_state = False
        self.relay_state = False
        self.lcd_line1 = f"SmartMed {time_display}"
        self.lcd_line2 = "System Reset - OK"
        return self._build_result("Monitoring", "System manually or remotely reset", 1, 0, 0)

    def _build_result(self, status, notes, ir, ldr, tilt):
        """Constructs a structured state object."""
        return {
            "status": status,
            "alert_active": 1 if self.alert_active else 0,
            "ir": ir,
            "ldr": ldr,
            "tilt": tilt,
            "led_state": self.led_state,
            "buzzer_state": 1 if self.buzzer_state else 0,
            "relay_state": 1 if self.relay_state else 0,
            "lcd_line1": self.lcd_line1.ljust(16)[:16],
            "lcd_line2": self.lcd_line2.ljust(16)[:16],
            "notes": notes,
            "timestamp": datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        }


# Global singleton instance
detection_engine = MedicineDetectionEngine()
