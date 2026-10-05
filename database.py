"""
Database Management Module for Smart Medicine Box IoT Project.
Handles SQLite database operations: table creation, logging sensor events,
retrieving historical logs, statistics calculation, and demo data initialization.
"""

import os
import sqlite3
from datetime import datetime

# Resolve database directory and file path
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_DIR = os.path.join(BASE_DIR, 'database')
DB_PATH = os.path.join(DB_DIR, 'medicine.db')


def ensure_db_dir():
    """Ensure that the database directory exists."""
    if not os.path.exists(DB_DIR):
        os.makedirs(DB_DIR, exist_ok=True)


def get_db_connection():
    """Create and return a SQLite database connection with row factory."""
    ensure_db_dir()
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def create_table():
    """
    Creates the 'medicine_logs' table if it does not exist.
    Schema matches the project requirements:
      - id: INTEGER PRIMARY KEY AUTOINCREMENT
      - time: TEXT (Formatted ISO/readable timestamp)
      - ir: INTEGER (0: Object Detected / Hand Present, 1: Clear)
      - ldr: INTEGER (Light level / 0: Dark / 1: Light Detected)
      - tilt: INTEGER (0: Normal / Level, 1: Tilted / Moved)
      - status: TEXT ('Medicine Taken', 'Medicine Missed', 'Box Open', 'Box Moved', 'Monitoring', 'Reminder Active')
      - alert_active: INTEGER (0: Normal, 1: Alarm/Buzzer Active)
      - notes: TEXT (Optional diagnostic details)
    """
    ensure_db_dir()
    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS medicine_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            time TEXT NOT NULL,
            ir INTEGER NOT NULL DEFAULT 1,
            ldr INTEGER NOT NULL DEFAULT 0,
            tilt INTEGER NOT NULL DEFAULT 0,
            status TEXT NOT NULL DEFAULT 'Monitoring',
            alert_active INTEGER NOT NULL DEFAULT 0,
            notes TEXT DEFAULT ''
        )
    """)

    # Create index on timestamp for fast query performance
    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_medicine_time ON medicine_logs(time DESC)
    """)

    # Table for customizable medicine reminder schedules
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS medicine_schedules (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            time_str TEXT NOT NULL,
            dosage TEXT NOT NULL,
            is_active INTEGER NOT NULL DEFAULT 1
        )
    """)

    conn.commit()

    # Seed initial schedules if empty
    cursor.execute("SELECT COUNT(*) as count FROM medicine_schedules")
    if cursor.fetchone()['count'] == 0:
        default_schedules = [
            ('Morning Dose (Breakfast)', '08:00', '1x Multivitamin + 1x BP Tablet', 1),
            ('Afternoon Dose (Lunch)', '13:00', '1x Calcium Supplement', 1),
            ('Night Dose (Dinner)', '20:00', '1x Diabetic Medication', 1)
        ]
        cursor.executemany(
            "INSERT INTO medicine_schedules (name, time_str, dosage, is_active) VALUES (?, ?, ?, ?)",
            default_schedules
        )
        conn.commit()

    conn.close()


def save_data(time_str=None, ir=1, ldr=0, tilt=0, status='Monitoring', alert_active=0, notes=''):
    """
    Insert a sensor telemetry/event record into SQLite database.
    Returns the inserted record's ID.
    """
    if time_str is None:
        time_str = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("""
        INSERT INTO medicine_logs (time, ir, ldr, tilt, status, alert_active, notes)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    """, (time_str, int(ir), int(ldr), int(tilt), str(status), int(alert_active), str(notes)))

    inserted_id = cursor.lastrowid
    conn.commit()
    conn.close()
    return inserted_id


def get_history(limit=100, filter_status=None, search_term=None):
    """
    Retrieve historical logs with optional status filtering and search.
    """
    create_table()
    conn = get_db_connection()
    cursor = conn.cursor()

    query = "SELECT * FROM medicine_logs WHERE 1=1"
    params = []

    if filter_status and filter_status != 'All':
        query += " AND status = ?"
        params.append(filter_status)

    if search_term:
        query += " AND (time LIKE ? OR status LIKE ? OR notes LIKE ?)"
        term = f"%{search_term}%"
        params.extend([term, term, term])

    query += " ORDER BY id DESC LIMIT ?"
    params.append(limit)

    cursor.execute(query, params)
    rows = cursor.fetchall()
    history = [dict(row) for row in rows]
    conn.close()
    return history


def get_latest():
    """Retrieve the most recent log entry."""
    create_table()
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM medicine_logs ORDER BY id DESC LIMIT 1")
    row = cursor.fetchone()
    conn.close()
    return dict(row) if row else None


def get_schedules():
    """Retrieve all active medicine dosage schedules."""
    create_table()
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM medicine_schedules ORDER BY time_str ASC")
    rows = cursor.fetchall()
    conn.close()
    return [dict(row) for row in rows]


def get_stats():
    """
    Calculates summary metrics:
      - Total records
      - Total Medicine Taken
      - Total Medicine Missed
      - Total Box Open events
      - Total Box Moved events
      - Adherence / Compliance rate (%)
    """
    create_table()
    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("SELECT COUNT(*) as total FROM medicine_logs")
    total = cursor.fetchone()['total']

    cursor.execute("SELECT COUNT(*) as taken FROM medicine_logs WHERE status = 'Medicine Taken'")
    taken = cursor.fetchone()['taken']

    cursor.execute("SELECT COUNT(*) as missed FROM medicine_logs WHERE status = 'Medicine Missed'")
    missed = cursor.fetchone()['missed']

    cursor.execute("SELECT COUNT(*) as box_open FROM medicine_logs WHERE status = 'Box Open'")
    box_open = cursor.fetchone()['box_open']

    cursor.execute("SELECT COUNT(*) as box_moved FROM medicine_logs WHERE status = 'Box Moved'")
    box_moved = cursor.fetchone()['box_moved']

    total_doses = taken + missed
    compliance_rate = round((taken / total_doses * 100), 1) if total_doses > 0 else 100.0

    conn.close()

    return {
        'total_logs': total,
        'taken_count': taken,
        'missed_count': missed,
        'box_open_count': box_open,
        'box_moved_count': box_moved,
        'compliance_rate': compliance_rate
    }


def clear_history():
    """Clear all records from the log table for fresh demonstration."""
    ensure_db_dir()
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM medicine_logs")
    conn.commit()
    conn.close()


def seed_demo_data():
    """Populates the database with sample historical events for instant presentation."""
    create_table()
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) as count FROM medicine_logs")
    if cursor.fetchone()['count'] == 0:
        samples = [
            ("2026-09-27 08:00:00", 1, 0, 0, "Reminder Active", 1, "Scheduled Morning Dose"),
            ("2026-09-27 08:02:15", 1, 1, 0, "Box Open", 0, "Patient opened lid"),
            ("2026-09-27 08:02:22", 0, 1, 0, "Medicine Taken", 0, "IR proximity detected hand pill retrieval"),
            ("2026-09-27 08:02:40", 1, 0, 0, "Monitoring", 0, "Lid closed, normal state restored"),
            ("2026-09-27 13:00:00", 1, 0, 0, "Reminder Active", 1, "Scheduled Afternoon Dose"),
            ("2026-09-27 13:20:00", 1, 0, 0, "Medicine Missed", 1, "Afternoon dose window expired without intake"),
            ("2026-09-27 15:45:10", 1, 0, 1, "Box Moved", 1, "Tilt sensor triggered box motion / vibration"),
            ("2026-09-27 20:00:00", 1, 0, 0, "Reminder Active", 1, "Scheduled Night Dose"),
            ("2026-09-27 20:04:10", 0, 1, 0, "Medicine Taken", 0, "Night dose taken successfully")
        ]
        cursor.executemany(
            "INSERT INTO medicine_logs (time, ir, ldr, tilt, status, alert_active, notes) VALUES (?, ?, ?, ?, ?, ?, ?)",
            samples
        )
        conn.commit()
    conn.close()


# Automatically initialize table when module is loaded
create_table()

if __name__ == '__main__':
    seed_demo_data()
    print("Database initialized successfully at:", DB_PATH)
    print("Sample stats:", get_stats())
