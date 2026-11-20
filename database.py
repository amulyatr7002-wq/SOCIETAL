import sqlite3
import os
from pathlib import Path

from werkzeug.security import generate_password_hash

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = Path(os.environ.get("CIVIC_DATA_DIR", BASE_DIR))
DATA_DIR.mkdir(parents=True, exist_ok=True)
DATABASE = DATA_DIR / "civic_connect.db"


def get_db():
    connection = sqlite3.connect(DATABASE)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    return connection


def init_db():
    with get_db() as db:
        db.executescript(
            """
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                email TEXT NOT NULL UNIQUE,
                password_hash TEXT NOT NULL,
                role TEXT NOT NULL CHECK(role IN ('citizen', 'admin', 'responder')),
                team_id INTEGER,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY(team_id) REFERENCES response_teams(id)
            );
            CREATE TABLE IF NOT EXISTS departments (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL UNIQUE
            );
            CREATE TABLE IF NOT EXISTS response_teams (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL UNIQUE,
                department_id INTEGER NOT NULL,
                FOREIGN KEY(department_id) REFERENCES departments(id)
            );
            CREATE TABLE IF NOT EXISTS complaints (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                public_id TEXT NOT NULL UNIQUE,
                user_id INTEGER NOT NULL,
                title TEXT NOT NULL,
                description TEXT NOT NULL,
                category TEXT NOT NULL,
                severity INTEGER NOT NULL DEFAULT 3,
                latitude REAL NOT NULL,
                longitude REAL NOT NULL,
                location_name TEXT NOT NULL DEFAULT '',
                status TEXT NOT NULL DEFAULT 'Submitted',
                priority_score INTEGER NOT NULL DEFAULT 0,
                priority_override TEXT,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                resolved_at TEXT,
                FOREIGN KEY(user_id) REFERENCES users(id)
            );
            CREATE TABLE IF NOT EXISTS complaint_images (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                complaint_id INTEGER NOT NULL,
                filename TEXT NOT NULL,
                kind TEXT NOT NULL DEFAULT 'report',
                uploaded_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY(complaint_id) REFERENCES complaints(id) ON DELETE CASCADE
            );
            CREATE TABLE IF NOT EXISTS complaint_assignments (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                complaint_id INTEGER NOT NULL,
                team_id INTEGER NOT NULL,
                assigned_by INTEGER NOT NULL,
                assigned_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                active INTEGER NOT NULL DEFAULT 1,
                FOREIGN KEY(complaint_id) REFERENCES complaints(id) ON DELETE CASCADE,
                FOREIGN KEY(team_id) REFERENCES response_teams(id),
                FOREIGN KEY(assigned_by) REFERENCES users(id)
            );
            CREATE TABLE IF NOT EXISTS status_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                complaint_id INTEGER NOT NULL,
                status TEXT NOT NULL,
                note TEXT NOT NULL DEFAULT '',
                changed_by INTEGER NOT NULL,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY(complaint_id) REFERENCES complaints(id) ON DELETE CASCADE,
                FOREIGN KEY(changed_by) REFERENCES users(id)
            );
            CREATE TABLE IF NOT EXISTS notifications (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                complaint_id INTEGER NOT NULL,
                message TEXT NOT NULL,
                is_read INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY(user_id) REFERENCES users(id),
                FOREIGN KEY(complaint_id) REFERENCES complaints(id) ON DELETE CASCADE
            );
            CREATE INDEX IF NOT EXISTS idx_complaints_user ON complaints(user_id);
            CREATE INDEX IF NOT EXISTS idx_complaints_status ON complaints(status);
            CREATE INDEX IF NOT EXISTS idx_history_complaint ON status_history(complaint_id);
            """
        )
        db.executemany(
            "INSERT OR IGNORE INTO departments(name) VALUES (?)",
            [
                ("Public Works",),
                ("Water & Sanitation",),
                ("Electrical Services",),
                ("Community Response",),
            ],
        )
        db.executemany(
            """INSERT OR IGNORE INTO response_teams(name, department_id)
               VALUES (?, (SELECT id FROM departments WHERE name = ?))""",
            [
                ("Roads & Infrastructure", "Public Works"),
                ("Water Services Unit", "Water & Sanitation"),
                ("Streetlight Crew", "Electrical Services"),
                ("Green Neighbourhood Volunteers", "Community Response"),
            ],
        )

        demo_users = [
            ("Aarav Sharma", "admin@civicconnect.local", "CivicAdmin24!", "admin", None),
            ("Maya Patel", "maya@civicconnect.local", "Citizen24!", "citizen", None),
            ("Kabir Rao", "kabir@civicconnect.local", "Citizen24!", "citizen", None),
            (
                "Dev Kumar",
                "team@civicconnect.local",
                "TeamLead24!",
                "responder",
                "Roads & Infrastructure",
            ),
            (
                "Nisha Das",
                "water@civicconnect.local",
                "TeamLead24!",
                "responder",
                "Water Services Unit",
            ),
        ]
        for name, email, password, role, team_name in demo_users:
            db.execute(
                """INSERT OR IGNORE INTO users(name, email, password_hash, role, team_id)
                   VALUES (?, ?, ?, ?, (SELECT id FROM response_teams WHERE name = ?))""",
                (name, email, generate_password_hash(password), role, team_name),
            )

        if db.execute("SELECT COUNT(*) FROM complaints").fetchone()[0] == 0:
            samples = [
                ("CC-2026-10421", "maya@civicconnect.local", "Deep pothole near school crossing", "A large pothole is forcing two-wheelers into traffic. Please add a temporary barricade.", "Roads", 5, 12.9716, 77.5946, "MG Road, Bengaluru", "In Progress", "Roads & Infrastructure", "2026-10-28 09:20:00"),
                ("CC-2026-10422", "kabir@civicconnect.local", "Water supply interrupted on 3rd Cross", "No water has reached the lane since yesterday morning. Several homes are affected.", "Water", 4, 12.9730, 77.5960, "3rd Cross, Bengaluru", "Assigned", "Water Services Unit", "2026-10-30 12:10:00"),
                ("CC-2026-10423", "maya@civicconnect.local", "Streetlight out beside the bus stop", "The light has been out for a week and the stop is very dark after 7pm.", "Streetlights", 3, 12.9688, 77.5923, "Brigade Road bus stop", "Under Review", None, "2026-11-02 18:30:00"),
                ("CC-2026-10424", "kabir@civicconnect.local", "Overflowing community waste bin", "Waste has been piling up for three collection days. There is a strong smell.", "Waste", 3, 12.9760, 77.5900, "Cubbon Park neighbourhood", "Resolved", "Green Neighbourhood Volunteers", "2026-10-18 07:45:00"),
                ("CC-2026-10425", "maya@civicconnect.local", "Blocked storm drain after rainfall", "Water is pooling across the footpath and entering the ground-floor homes.", "Drainage", 5, 12.9705, 77.5973, "Residency Road, Bengaluru", "Submitted", None, "2026-11-05 15:05:00"),
                ("CC-2026-10426", "kabir@civicconnect.local", "Broken pavement tiles near clinic", "Loose tiles create a trip hazard at the clinic entrance.", "Roads", 2, 12.9741, 77.5886, "Church Street, Bengaluru", "Closed", "Roads & Infrastructure", "2026-10-12 10:00:00"),
                ("CC-2026-10427", "maya@civicconnect.local", "Low water pressure in apartment block", "Pressure is very low in the mornings for more than 20 households.", "Water", 4, 12.9721, 77.5952, "Ashok Nagar, Bengaluru", "Submitted", None, "2026-11-07 08:15:00"),
                ("CC-2026-10428", "kabir@civicconnect.local", "Illegal dumping beside playground", "Construction debris is blocking the pedestrian path and play area.", "Waste", 4, 12.9678, 77.5898, "St Marks Road playground", "Under Review", None, "2026-11-08 16:40:00"),
            ]
            for item in samples:
                (
                    public_id, email, title, description, category, severity, lat, lng,
                    location, status, team_name, created_at,
                ) = item
                cursor = db.execute(
                    """INSERT INTO complaints
                       (public_id, user_id, title, description, category, severity,
                        latitude, longitude, location_name, status, created_at, updated_at)
                       VALUES (?, (SELECT id FROM users WHERE email = ?), ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        public_id, email, title, description, category, severity, lat, lng,
                        location, status, created_at, created_at,
                    ),
                )
                complaint_id = cursor.lastrowid
                if team_name:
                    db.execute(
                        """INSERT INTO complaint_assignments(complaint_id, team_id, assigned_by)
                           VALUES (?, (SELECT id FROM response_teams WHERE name = ?),
                                   (SELECT id FROM users WHERE email = 'admin@civicconnect.local'))""",
                        (complaint_id, team_name),
                    )
                db.execute(
                    """INSERT INTO status_history(complaint_id, status, note, changed_by, created_at)
                       VALUES (?, 'Submitted', 'Report received by Civic Connect', 
                               (SELECT id FROM users WHERE email = ?), ?)""",
                    (complaint_id, email, created_at),
                )
                if status != "Submitted":
                    db.execute(
                        """INSERT INTO status_history(complaint_id, status, note, changed_by, created_at)
                           VALUES (?, ?, 'Demonstration status update', 
                                   (SELECT id FROM users WHERE email = 'admin@civicconnect.local'),
                                   datetime(?, '+1 hour'))""",
                        (complaint_id, status, created_at),
                    )
                if status == "Resolved" or status == "Closed":
                    db.execute(
                        "UPDATE complaints SET resolved_at = datetime(?, '+2 days') WHERE id = ?",
                        (created_at, complaint_id),
                    )
