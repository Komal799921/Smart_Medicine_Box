"""
Flask Web Application for Smart Medicine Box IoT Project.
Provides REST APIs, real-time web dashboard, history log viewer, CSV export,
Bluetooth command terminal, and optional serial background listener for ESP32.
"""

import os
import io
import csv
import json
import time
import threading
from datetime import datetime
from flask import Flask, render_template, request, jsonify, Response, send_file

import database
from detection import detection_engine
from alerts import alert_manager

# Initialize Flask App
app = Flask(__name__)
app.config['SECRET_KEY'] = 'smart-medicine-box-iot-secret-2026'

# Ensure database table is ready
database.create_table()
database.seed_demo_data()

# Global Serial Connection State
SERIAL_PORT = os.environ.get('ESP32_PORT', 'COM3')
SERIAL_BAUD = 115200
serial_thread = None
serial_connected = False


def background_serial_reader():
    """
    Background thread to read real-time telemetry from connected ESP32 via USB Serial.
    If no device is connected, safely sleeps and retries.
    """
    global serial_connected
    try:
        import serial
    except ImportError:
        print("[Serial Worker] PySerial not installed or available. Running in API/Simulator mode.")
        return

    while True:
        try:
            with serial.Serial(SERIAL_PORT, SERIAL_BAUD, timeout=2) as ser:
                serial_connected = True
                print(f"[Serial Worker] Connected to ESP32 on {SERIAL_PORT} @ {SERIAL_BAUD}")
                while True:
                    line = ser.readline().decode('utf-8', errors='ignore').strip()
                    if line:
                        # Check if line is JSON telemetry from ESP32
                        if line.startswith('{') and line.endswith('}'):
                            try:
                                data = json.loads(line)
                                ir = int(data.get('ir', 1))
                                ldr = int(data.get('ldr', 0))
                                tilt = int(data.get('tilt', 0))
                                
                                result = detection_engine.process_reading(ir=ir, ldr=ldr, tilt=tilt)
                                database.save_data(
                                    time_str=datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                                    ir=result['ir'],
                                    ldr=result['ldr'],
                                    tilt=result['tilt'],
                                    status=result['status'],
                                    alert_active=result['alert_active'],
                                    notes=result['notes']
                                )
                            except Exception as parse_err:
                                print(f"[Serial Worker] JSON parse error: {parse_err}")
                        else:
                            print(f"[ESP32 Serial Log]: {line}")
        except Exception:
            serial_connected = False
            time.sleep(5)  # Retry connection every 5 seconds


# Start background serial worker daemon
try:
    import serial
    serial_thread = threading.Thread(target=background_serial_reader, daemon=True)
    serial_thread.start()
except ImportError:
    pass


# -------------------------------------------------------------
# Web Page Routes
# -------------------------------------------------------------

@app.route('/')
def dashboard():
    """Main dashboard page."""
    latest = database.get_latest()
    stats = database.get_stats()
    schedules = database.get_schedules()
    return render_template('dashboard.html', latest=latest, stats=stats, schedules=schedules, serial_connected=serial_connected)


@app.route('/history')
def history():
    """Historical logs view page."""
    filter_status = request.args.get('filter', 'All')
    search_term = request.args.get('search', '')
    records = database.get_history(limit=200, filter_status=filter_status, search_term=search_term)
    stats = database.get_stats()
    return render_template('history.html', records=records, stats=stats, current_filter=filter_status, search_term=search_term)


# -------------------------------------------------------------
# REST API Endpoints
# -------------------------------------------------------------

@app.route('/api/live-status', methods=['GET'])
def api_live_status():
    """Returns current live sensor and system state for real-time dashboard polling."""
    # Process current states through detection engine
    now = datetime.now()
    scheduled_match = detection_engine.check_schedule_match(now)
    if scheduled_match and not detection_engine.active_reminder:
        detection_engine.set_reminder(scheduled_match)

    latest_db = database.get_latest()
    stats = database.get_stats()
    alert_info = alert_manager.get_status()

    # Determine live sensor values (from engine or database)
    ir_val = detection_engine.last_ir_state if hasattr(detection_engine, 'last_ir_state') else (latest_db['ir'] if latest_db else 1)
    ldr_val = detection_engine.last_ldr_state if hasattr(detection_engine, 'last_ldr_state') else (latest_db['ldr'] if latest_db else 0)
    tilt_val = detection_engine.last_tilt_state if hasattr(detection_engine, 'last_tilt_state') else (latest_db['tilt'] if latest_db else 0)

    return jsonify({
        "time": now.strftime('%Y-%m-%d %H:%M:%S'),
        "time_display": now.strftime('%I:%M:%S %p'),
        "date_display": now.strftime('%A, %d %B %Y'),
        "ir": ir_val,
        "ldr": ldr_val,
        "tilt": tilt_val,
        "status": detection_engine.current_status,
        "alert_active": 1 if (detection_engine.alert_active or alert_info['buzzer_active']) else 0,
        "buzzer_state": 1 if (detection_engine.buzzer_state or alert_info['buzzer_active']) else 0,
        "led_state": detection_engine.led_state,
        "relay_state": 1 if detection_engine.relay_state else 0,
        "lcd_line1": detection_engine.lcd_line1,
        "lcd_line2": detection_engine.lcd_line2,
        "active_reminder": detection_engine.active_reminder,
        "stats": stats,
        "serial_connected": serial_connected
    })


@app.route('/api/sensor-data', methods=['POST'])
def api_sensor_data():
    """
    Receives sensor readings from ESP32 or simulator.
    Payload: { "ir": 0|1, "ldr": 0|1, "tilt": 0|1, "time": "...", "manual_event": "..." }
    """
    data = request.get_json(force=True, silent=True) or {}
    
    ir = int(data.get('ir', 1))
    ldr = int(data.get('ldr', 0))
    tilt = int(data.get('tilt', 0))
    manual_event = data.get('manual_event', None)
    time_str = data.get('time', datetime.now().strftime('%Y-%m-%d %H:%M:%S'))

    # Update detection engine state
    result = detection_engine.process_reading(ir=ir, ldr=ldr, tilt=tilt, timestamp=time_str, manual_event=manual_event)
    
    # Sync with alert manager
    if result['status'] == 'Medicine Missed':
        alert_manager.trigger_missed_alert("Scheduled Dose")
    elif result['status'] == 'Box Moved':
        alert_manager.trigger_tamper_alert()
    elif result['status'] == 'Medicine Taken':
        alert_manager.dismiss_alert()

    # Save to SQLite database
    inserted_id = database.save_data(
        time_str=time_str,
        ir=result['ir'],
        ldr=result['ldr'],
        tilt=result['tilt'],
        status=result['status'],
        alert_active=result['alert_active'],
        notes=result['notes']
    )

    result['id'] = inserted_id
    return jsonify(result)


@app.route('/api/action', methods=['POST'])
def api_action():
    """
    Trigger manual dashboard actions:
    take_medicine, open_box, tilt_box, trigger_missed, trigger_reminder, buzzer_on, buzzer_off, reset
    """
    data = request.get_json(force=True, silent=True) or {}
    action_type = data.get('action', '').strip().lower()

    if action_type == 'take_medicine':
        result = detection_engine.process_reading(ir=0, ldr=1, tilt=0, manual_event="take_medicine")
        alert_manager.dismiss_alert()
    elif action_type == 'open_box':
        result = detection_engine.process_reading(ir=1, ldr=1, tilt=0, manual_event="open_box")
    elif action_type == 'tilt_box':
        result = detection_engine.process_reading(ir=1, ldr=0, tilt=1, manual_event="tilt_box")
        alert_manager.trigger_tamper_alert()
    elif action_type == 'trigger_missed':
        result = detection_engine.process_reading(manual_event="trigger_missed")
        alert_manager.trigger_missed_alert("Manual Missed Simulation")
    elif action_type == 'trigger_reminder':
        detection_engine.set_reminder("Manual Scheduled Dose")
        alert_manager.trigger_reminder_alert("Manual Dose")
        result = detection_engine.process_reading(ir=1, ldr=0, tilt=0)
    elif action_type == 'buzzer_on':
        alert_manager.set_buzzer(True)
        detection_engine.buzzer_state = True
        result = detection_engine.process_reading(ir=1, ldr=0, tilt=0)
    elif action_type == 'buzzer_off':
        alert_manager.set_buzzer(False)
        detection_engine.buzzer_state = False
        result = detection_engine.process_reading(ir=1, ldr=0, tilt=0)
    elif action_type == 'reset':
        result = detection_engine.reset()
        alert_manager.dismiss_alert()
    else:
        return jsonify({"error": f"Unknown action: {action_type}"}), 400

    # Save state transition to DB
    database.save_data(
        time_str=datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        ir=result['ir'],
        ldr=result['ldr'],
        tilt=result['tilt'],
        status=result['status'],
        alert_active=result['alert_active'],
        notes=result['notes']
    )

    return jsonify({"success": True, "result": result})


@app.route('/api/bluetooth-command', methods=['POST'])
def api_bluetooth_command():
    """
    Simulates or sends Bluetooth command to ESP32:
    STATUS, BUZZER ON, BUZZER OFF, RESET, TAKEN
    """
    data = request.get_json(force=True, silent=True) or {}
    command = data.get('command', '').strip().upper()

    if not command:
        return jsonify({"error": "No command provided"}), 400

    # Process command through alert and detection managers
    if command == "BUZZER ON":
        alert_manager.set_buzzer(True)
        detection_engine.buzzer_state = True
    elif command == "BUZZER OFF":
        alert_manager.set_buzzer(False)
        detection_engine.buzzer_state = False
    elif command == "RESET":
        detection_engine.reset()
        alert_manager.dismiss_alert()
    elif command == "TAKEN":
        detection_engine.process_reading(ir=0, ldr=1, tilt=0, manual_event="take_medicine")
        alert_manager.dismiss_alert()

    response_text = alert_manager.format_bluetooth_response(command)

    # Log command event
    database.save_data(
        time_str=datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        ir=detection_engine.last_ir_state if hasattr(detection_engine, 'last_ir_state') else 1,
        ldr=detection_engine.last_ldr_state if hasattr(detection_engine, 'last_ldr_state') else 0,
        tilt=detection_engine.last_tilt_state if hasattr(detection_engine, 'last_tilt_state') else 0,
        status=detection_engine.current_status,
        alert_active=1 if alert_manager.is_buzzer_on else 0,
        notes=f"Bluetooth Command executed: '{command}'"
    )

    return jsonify({
        "command": command,
        "response": response_text,
        "timestamp": datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    })


@app.route('/api/history', methods=['GET'])
def api_history():
    """Returns JSON list of historical records with filtering."""
    filter_status = request.args.get('filter', 'All')
    search_term = request.args.get('search', '')
    limit = int(request.args.get('limit', 100))
    records = database.get_history(limit=limit, filter_status=filter_status, search_term=search_term)
    return jsonify(records)


@app.route('/api/export-csv', methods=['GET'])
def api_export_csv():
    """Generates a downloadable CSV file containing all logged records."""
    records = database.get_history(limit=1000)
    
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(['ID', 'Timestamp', 'IR Sensor', 'LDR Sensor', 'Tilt Sensor', 'Status', 'Alert Active', 'Diagnostic Notes'])

    for r in records:
        writer.writerow([
            r['id'],
            r['time'],
            'Clear (1)' if r['ir'] == 1 else 'Hand Present (0)',
            'Light/Open (1)' if r['ldr'] == 1 else 'Dark/Closed (0)',
            'Tilted/Moved (1)' if r['tilt'] == 1 else 'Normal/Level (0)',
            r['status'],
            'Active' if r['alert_active'] == 1 else 'Normal',
            r['notes']
        ])

    output.seek(0)
    filename = f"Smart_Medicine_Box_Logs_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
    return Response(
        output.getvalue(),
        mimetype="text/csv",
        headers={"Content-Disposition": f"attachment;filename={filename}"}
    )


@app.route('/api/clear-history', methods=['POST'])
def api_clear_history():
    """Clears all records in the SQLite database."""
    database.clear_history()
    return jsonify({"success": True, "message": "History logs successfully cleared."})


if __name__ == '__main__':
    print("=" * 60)
    print("   Starting Smart Medicine Box IoT Server...")
    print("   Dashboard: http://127.0.0.1:5000")
    print("   History:   http://127.0.0.1:5000/history")
    print("=" * 60)
    app.run(host='0.0.0.0', port=5000, debug=True)
