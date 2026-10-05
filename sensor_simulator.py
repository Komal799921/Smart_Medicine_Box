"""
Sensor Simulator for Smart Medicine Box IoT Project.
Simulates ESP32 hardware telemetry (RTC, IR Proximity, LDR Light, Tilt Sensor)
and sends events to the Flask application or directly into SQLite database.
Enables full demonstration and testing without physical hardware connected.
"""

import time
import json
import random
import argparse
from datetime import datetime

try:
    import requests
except ImportError:
    requests = None

# Import internal modules for direct fallback
import database
from detection import detection_engine
from alerts import alert_manager

API_URL = "http://127.0.0.1:5000/api/sensor-data"
ACTION_URL = "http://127.0.0.1:5000/api/action"
BT_URL = "http://127.0.0.1:5000/api/bluetooth-command"


def send_telemetry(ir=1, ldr=0, tilt=0, manual_event=None, server_url=API_URL):
    """
    Sends sensor readings to the Flask server or falls back to direct database insertion.
    """
    payload = {
        "time": datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        "ir": ir,
        "ldr": ldr,
        "tilt": tilt,
        "manual_event": manual_event
    }

    server_reached = False
    if requests:
        try:
            res = requests.post(server_url, json=payload, timeout=1.5)
            if res.status_code == 200:
                server_reached = True
                data = res.json()
                print(f"[HTTP 200 OK] Server Response -> Status: {data.get('status')} | Alert: {data.get('alert_active')}")
        except Exception:
            server_reached = False

    if not server_reached:
        # Fallback: Process locally and write directly to SQLite database
        result = detection_engine.process_reading(ir=ir, ldr=ldr, tilt=tilt, manual_event=manual_event)
        database.save_data(
            time_str=payload["time"],
            ir=result["ir"],
            ldr=result["ldr"],
            tilt=result["tilt"],
            status=result["status"],
            alert_active=result["alert_active"],
            notes=result["notes"]
        )
        print(f"[Direct SQLite] Logged locally -> Status: {result['status']} | Buzzer: {result['buzzer_state']}")


def send_bluetooth_cmd(command, bt_url=BT_URL):
    """Sends a simulated Bluetooth serial command."""
    if requests:
        try:
            res = requests.post(bt_url, json={"command": command}, timeout=1.5)
            if res.status_code == 200:
                print(f"[Bluetooth Response]: {res.json().get('response')}")
                return
        except Exception:
            pass

    # Local fallback
    resp = alert_manager.format_bluetooth_response(command)
    print(f"[Local Bluetooth Simulator]: {resp}")


def run_interactive_mode():
    """Interactive command-line simulation interface."""
    print("=" * 60)
    print("   SMART MEDICINE BOX - HARDWARE SENSOR SIMULATOR")
    print("=" * 60)
    print("Select a simulated hardware event:")
    print("  [1] Normal Idle State (Box closed, no hand, stable)")
    print("  [2] Trigger Medicine Reminder (Alarm beeps, LCD prompts)")
    print("  [3] Open Box Lid (LDR Sensor = 1 / Light detected)")
    print("  [4] Patient Takes Medicine (IR Sensor = 0 / Hand detected)")
    print("  [5] Medicine Missed Timeout (Alarm sounds, Red LED ON)")
    print("  [6] Shake / Tilt Box (Tilt Sensor = 1 / Tamper alert)")
    print("  [7] Send Bluetooth Command: STATUS")
    print("  [8] Send Bluetooth Command: BUZZER ON")
    print("  [9] Send Bluetooth Command: BUZZER OFF")
    print("  [0] Send Bluetooth Command: RESET")
    print("  [A] Run Continuous Autopilot Demo Routine")
    print("  [Q] Exit Simulator")
    print("=" * 60)

    while True:
        try:
            choice = input("\nEnter choice (1-0, A, Q): ").strip().upper()
            if choice == '1':
                print(">> Simulating: Normal Standby (IR=1, LDR=0, Tilt=0)")
                send_telemetry(ir=1, ldr=0, tilt=0)
            elif choice == '2':
                print(">> Simulating: Medicine Reminder Active")
                send_telemetry(ir=1, ldr=0, tilt=0, manual_event="reminder")
            elif choice == '3':
                print(">> Simulating: Box Lid Opened (LDR=1)")
                send_telemetry(ir=1, ldr=1, tilt=0, manual_event="open_box")
            elif choice == '4':
                print(">> Simulating: Medicine Taken (IR=0, LDR=1)")
                send_telemetry(ir=0, ldr=1, tilt=0, manual_event="take_medicine")
            elif choice == '5':
                print(">> Simulating: Medicine Missed (Timeout -> Red LED + Buzzer)")
                send_telemetry(ir=1, ldr=0, tilt=0, manual_event="trigger_missed")
            elif choice == '6':
                print(">> Simulating: Box Moved / Shaken (Tilt=1)")
                send_telemetry(ir=1, ldr=0, tilt=1, manual_event="tilt_box")
            elif choice == '7':
                send_bluetooth_cmd("STATUS")
            elif choice == '8':
                send_bluetooth_cmd("BUZZER ON")
            elif choice == '9':
                send_bluetooth_cmd("BUZZER OFF")
            elif choice == '0':
                send_bluetooth_cmd("RESET")
            elif choice == 'A':
                run_autopilot_routine()
            elif choice in ('Q', 'EXIT'):
                print("Exiting simulator.")
                break
            else:
                print("Invalid selection. Choose 0-9, A, or Q.")
        except KeyboardInterrupt:
            print("\nExiting simulator.")
            break


def run_autopilot_routine():
    """Runs a complete realistic demonstration sequence."""
    print("\nStarting Autopilot Routine... Press Ctrl+C to return to menu.\n")
    try:
        # Step 1: Idle
        print("\n--- STEP 1: Morning Standby (07:59 AM) ---")
        send_telemetry(ir=1, ldr=0, tilt=0)
        time.sleep(2)

        # Step 2: Reminder fires
        print("\n--- STEP 2: Morning Medicine Scheduled Reminder (08:00 AM) ---")
        detection_engine.set_reminder("Morning Dose (Breakfast)")
        send_telemetry(ir=1, ldr=0, tilt=0)
        time.sleep(3)

        # Step 3: Patient opens lid
        print("\n--- STEP 3: Patient Opens Box Lid (LDR Sensor Detects Light) ---")
        send_telemetry(ir=1, ldr=1, tilt=0, manual_event="open_box")
        time.sleep(2)

        # Step 4: Hand reaches inside to pick pill
        print("\n--- STEP 4: IR Proximity Sensor Detects Hand Taking Pill ---")
        send_telemetry(ir=0, ldr=1, tilt=0, manual_event="take_medicine")
        time.sleep(3)

        # Step 5: Patient closes box
        print("\n--- STEP 5: Box Lid Closed, System Returns to Normal OK ---")
        send_telemetry(ir=1, ldr=0, tilt=0)
        time.sleep(2)

        # Step 6: Afternoon Missed scenario
        print("\n--- STEP 6: Afternoon Dose (13:00 PM) - Dose Missed Timeout ---")
        send_telemetry(ir=1, ldr=0, tilt=0, manual_event="trigger_missed")
        time.sleep(3)

        # Step 7: Doctor/Caretaker resets alert via Bluetooth
        print("\n--- STEP 7: Caretaker Sends Bluetooth Command: RESET ---")
        send_bluetooth_cmd("RESET")
        time.sleep(2)

        # Step 8: Box moved / bumped
        print("\n--- STEP 8: Accidental Bump / Tilt Sensor Triggered ---")
        send_telemetry(ir=1, ldr=0, tilt=1, manual_event="tilt_box")
        time.sleep(2)

        # Step 9: Reset back to idle
        print("\n--- STEP 9: System Reset Back to Normal ---")
        send_telemetry(ir=1, ldr=0, tilt=0, manual_event="reset")

        print("\nAutopilot Routine Completed Successfully!")
    except KeyboardInterrupt:
        print("\nAutopilot routine stopped by user.")


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description="Smart Medicine Box Sensor Simulator")
    parser.add_argument("--auto", action="store_true", help="Run automated continuous simulation loop")
    parser.add_argument("--server", type=str, default=API_URL, help="Target Flask API URL")
    args = parser.parse_args()

    if args.auto:
        run_autopilot_routine()
    else:
        run_interactive_mode()
