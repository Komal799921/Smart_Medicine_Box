"""
Alerts Management Module for Smart Medicine Box IoT Project.
Coordinates audio-visual alerts (Buzzer, Red/Yellow/Green LEDs, 16x2 LCD display,
and Web Dashboard notifications) when medicine is missed or when box is moved/tampered.
"""

from datetime import datetime

class AlertManager:
    def __init__(self):
        self.is_buzzer_on = False
        self.active_alert = None
        self.alert_history = []
        self.max_history_entries = 50

    def trigger_missed_alert(self, dose_name="Scheduled Dose"):
        """
        Triggers emergency alert when medicine dosage is missed.
        Actions:
          - Turn ON Buzzer
          - Turn ON Red LED
          - Prepare LCD message
          - Return hardware command payload
        """
        timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        self.is_buzzer_on = True
        self.active_alert = {
            "type": "MEDICINE_MISSED",
            "message": f"CRITICAL: {dose_name} was not taken!",
            "severity": "HIGH",
            "time": timestamp,
            "led": "RED",
            "buzzer": True,
            "lcd_line1": "MEDICINE MISSED!",
            "lcd_line2": "PLEASE TAKE NOW"
        }
        self._record_alert(self.active_alert)
        return self.active_alert

    def trigger_reminder_alert(self, dose_name="Morning Dose"):
        """
        Triggers gentle reminder alert when it is time to take medicine.
        Actions:
          - Turn ON Buzzer (intermittent)
          - Turn ON Yellow LED
          - Prepare LCD reminder
        """
        timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        self.is_buzzer_on = True
        self.active_alert = {
            "type": "REMINDER_ACTIVE",
            "message": f"Time for {dose_name}. Please open box.",
            "severity": "MEDIUM",
            "time": timestamp,
            "led": "YELLOW",
            "buzzer": True,
            "lcd_line1": "TIME TO TAKE MED",
            "lcd_line2": dose_name[:16]
        }
        self._record_alert(self.active_alert)
        return self.active_alert

    def trigger_tamper_alert(self):
        """Triggers security alert if box is tilted, dropped, or moved unexpectedly."""
        timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        self.is_buzzer_on = True
        self.active_alert = {
            "type": "BOX_MOVED",
            "message": "WARNING: Smart Medicine Box was moved or tilted!",
            "severity": "MEDIUM",
            "time": timestamp,
            "led": "RED",
            "buzzer": True,
            "lcd_line1": "ALERT: BOX MOVED",
            "lcd_line2": "CHECK POSITION"
        }
        self._record_alert(self.active_alert)
        return self.active_alert

    def dismiss_alert(self):
        """Mutes buzzer and resets active alarm state."""
        self.is_buzzer_on = False
        self.active_alert = None
        return {
            "status": "DISMISSED",
            "buzzer": False,
            "led": "GREEN",
            "lcd_line1": "SmartMed Box",
            "lcd_line2": "Status: NORMAL"
        }

    def set_buzzer(self, state: bool):
        """Explicitly switch buzzer state ON/OFF."""
        self.is_buzzer_on = state
        if not state and self.active_alert:
            self.active_alert["buzzer"] = False

    def get_status(self):
        """Return current alert system state for API/Dashboard."""
        return {
            "buzzer_active": self.is_buzzer_on,
            "has_active_alert": self.active_alert is not None,
            "active_alert": self.active_alert,
            "recent_alerts": self.alert_history[-5:]
        }

    def format_bluetooth_response(self, command_name):
        """Generates standard responses for Bluetooth serial commands."""
        cmd = command_name.strip().upper()
        if cmd == "STATUS":
            if self.active_alert:
                return f"STATUS: {self.active_alert['type']} | BUZZER: {'ON' if self.is_buzzer_on else 'OFF'}"
            return f"STATUS: OK | BUZZER: {'ON' if self.is_buzzer_on else 'OFF'} | BOX: NORMAL"
        elif cmd == "BUZZER ON":
            self.set_buzzer(True)
            return "ACK: BUZZER TURNED ON"
        elif cmd == "BUZZER OFF":
            self.set_buzzer(False)
            return "ACK: BUZZER TURNED OFF"
        elif cmd == "RESET":
            self.dismiss_alert()
            return "ACK: SYSTEM ALERTS RESET"
        elif cmd == "TAKEN":
            self.dismiss_alert()
            return "ACK: MEDICINE RECORDED AS TAKEN"
        else:
            return f"UNKNOWN COMMAND: {command_name}. Valid: STATUS, BUZZER ON, BUZZER OFF, RESET, TAKEN"

    def _record_alert(self, alert_dict):
        """Keeps in-memory circular log of recent alerts."""
        self.alert_history.append(dict(alert_dict))
        if len(self.alert_history) > self.max_history_entries:
            self.alert_history.pop(0)


# Global alert manager instance
alert_manager = AlertManager()
