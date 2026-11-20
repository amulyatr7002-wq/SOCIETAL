import math
import os
import secrets
import sqlite3
import uuid
from datetime import datetime, timezone
from functools import wraps
from pathlib import Path

from flask import Flask, jsonify, request, send_from_directory, session
from PIL import Image, UnidentifiedImageError
from werkzeug.security import check_password_hash, generate_password_hash

from database import BASE_DIR, get_db, init_db

app = Flask(__name__, static_folder="static", static_url_path="/static")
app.config.update(
    SECRET_KEY=os.environ.get("CIVIC_SECRET_KEY", "replace-this-demo-secret-before-deploying"),
    MAX_CONTENT_LENGTH=6 * 1024 * 1024,
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    SESSION_COOKIE_SECURE=os.environ.get("CIVIC_HTTPS", "").lower() == "true",
)
UPLOAD_DIR = Path(os.environ.get("CIVIC_DATA_DIR", BASE_DIR)) / "uploads"
UPLOAD_DIR.mkdir(exist_ok=True)
CATEGORIES = {"Roads", "Water", "Streetlights", "Waste", "Drainage", "Other"}
STATUSES = ["Submitted", "Under Review", "Assigned", "In Progress", "Resolved", "Closed"]
PRIORITIES = {"Critical", "High", "Medium", "Low"}
IMAGE_FORMATS = {"JPEG": ".jpg", "PNG": ".png", "WEBP": ".webp"}


def error(message, status=400):
    return jsonify({"error": message}), status


def csrf_required(fn):
    @wraps(fn)
    def wrapped(*args, **kwargs):
        token = session.get("csrf_token")
        if not token or not secrets.compare_digest(
            token, request.headers.get("X-CSRF-Token", "")
        ):
            return error("Your session token expired. Refresh and try again.", 403)
        return fn(*args, **kwargs)

    return wrapped


def login_required(fn):
    @wraps(fn)
    def wrapped(*args, **kwargs):
        if not session.get("user_id"):
            return error("Please sign in to continue.", 401)
        return fn(*args, **kwargs)

    return wrapped


def role_required(*roles):
    def decorator(fn):
        @wraps(fn)
        @login_required
        def wrapped(*args, **kwargs):
            if session.get("role") not in roles:
                return error("You do not have permission to perform this action.", 403)
            return fn(*args, **kwargs)

        return wrapped

    return decorator


def priority_for(db, category, severity, lat, lng, created_at=None):
    nearby = db.execute(
        """SELECT latitude, longitude FROM complaints
           WHERE category = ? AND latitude BETWEEN ? AND ? AND longitude BETWEEN ? AND ?""",
        (category, lat - 0.02, lat + 0.02, lng - 0.02, lng + 0.02),
    ).fetchall()
    similar = 0
    for row in nearby:
        distance = haversine_km(lat, lng, row["latitude"], row["longitude"])
        if distance <= 1:
            similar += 1
    age_hours = 0
    if created_at:
        try:
            created = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
            if created.tzinfo is None:
                created = created.replace(tzinfo=timezone.utc)
            else:
                created = created.astimezone(timezone.utc)
            age_hours = max(
                0, (datetime.now(timezone.utc) - created).total_seconds() / 3600
            )
        except ValueError:
            age_hours = 0
    severity_points = (max(1, min(5, int(severity))) / 5) * 50
    cluster_points = min(similar / 5, 1) * 30
    age_points = min(age_hours / (24 * 7), 1) * 20
    score = round(min(100, severity_points + cluster_points + age_points))
    label = "Critical" if score >= 80 else "High" if score >= 60 else "Medium" if score >= 35 else "Low"
    return {
        "score": score,
        "label": label,
        "breakdown": {
            "severity": round(severity_points),
            "nearby_reports": round(cluster_points),
            "time_elapsed": round(age_points),
            "similar_reports_within_1km": similar,
        },
    }


def haversine_km(lat1, lng1, lat2, lng2):
    radius = 6371
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lng2 - lng1)
    value = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return radius * 2 * math.atan2(math.sqrt(value), math.sqrt(1 - value))


def complaint_record(db, row):
    effective_priority = row["priority_override"] or (
        "Critical" if row["priority_score"] >= 80 else
        "High" if row["priority_score"] >= 60 else
        "Medium" if row["priority_score"] >= 35 else "Low"
    )
    info = priority_for(
        db, row["category"], row["severity"], row["latitude"], row["longitude"],
        row["created_at"],
    )
    info["label"] = effective_priority
    history = db.execute(
        """SELECT h.status, h.note, h.created_at, u.name AS changed_by
           FROM status_history h JOIN users u ON u.id = h.changed_by
           WHERE h.complaint_id = ? ORDER BY h.id""",
        (row["id"],),
    ).fetchall()
    images = db.execute(
        "SELECT filename, kind FROM complaint_images WHERE complaint_id = ?",
        (row["id"],),
    ).fetchall()
    result = dict(row)
    result.update(
        priority=info,
        history=[dict(item) for item in history],
        images=[{"url": f"/uploads/{item['filename']}", "kind": item["kind"]} for item in images],
    )
    return result


def get_complaint_query():
    return """SELECT c.*, u.name AS citizen_name, u.email AS citizen_email,
                     t.id AS team_id, t.name AS team_name, d.name AS department_name
              FROM complaints c
              JOIN users u ON u.id = c.user_id
              LEFT JOIN complaint_assignments a ON a.complaint_id = c.id AND a.active = 1
              LEFT JOIN response_teams t ON t.id = a.team_id
              LEFT JOIN departments d ON d.id = t.department_id"""


def add_notification(db, user_id, complaint_id, message):
    db.execute(
        "INSERT INTO notifications(user_id, complaint_id, message) VALUES (?, ?, ?)",
        (user_id, complaint_id, message),
    )


def save_image(file_storage, complaint_id, kind):
    if not file_storage or not file_storage.filename:
        return None
    try:
        image = Image.open(file_storage.stream)
        image.verify()
        image_format = image.format
    except (UnidentifiedImageError, OSError):
        raise ValueError("Upload a valid JPEG, PNG, or WebP image.")
    if image_format not in IMAGE_FORMATS:
        raise ValueError("Only JPEG, PNG, and WebP images are supported.")
    filename = f"{uuid.uuid4().hex}{IMAGE_FORMATS[image_format]}"
    file_storage.stream.seek(0)
    image = Image.open(file_storage.stream)
    image.thumbnail((2200, 2200))
    image.save(UPLOAD_DIR / filename, format=image_format)
    return filename


def public_id(db):
    while True:
        candidate = f"CC-{datetime.now():%y%m}-{secrets.randbelow(90000) + 10000}"
        if not db.execute("SELECT 1 FROM complaints WHERE public_id = ?", (candidate,)).fetchone():
            return candidate


@app.errorhandler(413)
def file_too_large(_error):
    return jsonify({"error": "The upload is too large. Maximum request size is 6 MB."}), 413


@app.route("/")
def home():
    return send_from_directory(app.static_folder, "index.html")


@app.get("/uploads/<path:filename>")
def uploaded_file(filename):
    return send_from_directory(UPLOAD_DIR, filename)


@app.get("/api/config")
def config():
    session.setdefault("csrf_token", secrets.token_urlsafe(32))
    return jsonify({"csrf_token": session["csrf_token"]})


@app.post("/api/register")
@csrf_required
def register():
    payload = request.get_json(silent=True) or {}
    name = str(payload.get("name", "")).strip()
    email = str(payload.get("email", "")).strip().lower()
    password = str(payload.get("password", ""))
    if len(name) < 2 or len(name) > 80:
        return error("Name must be between 2 and 80 characters.")
    if "@" not in email or len(email) > 160:
        return error("Enter a valid email address.")
    if len(password) < 8:
        return error("Password must contain at least 8 characters.")
    try:
        with get_db() as db:
            db.execute(
                "INSERT INTO users(name, email, password_hash, role) VALUES (?, ?, ?, 'citizen')",
                (name, email, generate_password_hash(password)),
            )
    except sqlite3.IntegrityError:
        return error("An account with that email already exists.", 409)
    return jsonify({"message": "Account created. You can now sign in."}), 201


@app.post("/api/login")
@csrf_required
def login():
    payload = request.get_json(silent=True) or {}
    email = str(payload.get("email", "")).strip().lower()
    password = str(payload.get("password", ""))
    with get_db() as db:
        user = db.execute("SELECT * FROM users WHERE email = ?", (email,)).fetchone()
    if not user or not check_password_hash(user["password_hash"], password):
        return error("Email or password is incorrect.", 401)
    session.clear()
    session["user_id"] = user["id"]
    session["role"] = user["role"]
    session["csrf_token"] = secrets.token_urlsafe(32)
    return jsonify({"user": {"id": user["id"], "name": user["name"], "email": user["email"], "role": user["role"]}})


@app.post("/api/logout")
@csrf_required
@login_required
def logout():
    session.clear()
    return jsonify({"message": "Signed out."})


@app.get("/api/me")
def me():
    user_id = session.get("user_id")
    if not user_id:
        return jsonify({"user": None})
    with get_db() as db:
        user = db.execute(
            """SELECT u.id, u.name, u.email, u.role, t.id AS team_id, t.name AS team_name
               FROM users u LEFT JOIN response_teams t ON t.id = u.team_id WHERE u.id = ?""",
            (user_id,),
        ).fetchone()
    return jsonify({"user": dict(user) if user else None})


@app.get("/api/complaints")
@login_required
def complaints():
    role = session["role"]
    where, params = [], []
    if role == "citizen":
        where.append("c.user_id = ?")
        params.append(session["user_id"])
    elif role == "responder":
        where.append("""EXISTS (SELECT 1 FROM complaint_assignments ca
                               JOIN users me ON me.team_id = ca.team_id
                               WHERE ca.complaint_id = c.id AND ca.active = 1
                                 AND me.id = ? AND ca.team_id = me.team_id)""")
        params.append(session["user_id"])
    query = get_complaint_query()
    if where:
        query += " WHERE " + " AND ".join(where)
    query += """ GROUP BY c.id ORDER BY
                 CASE WHEN c.priority_override IS NOT NULL THEN
                    CASE c.priority_override WHEN 'Critical' THEN 4 WHEN 'High' THEN 3
                         WHEN 'Medium' THEN 2 ELSE 1 END
                    ELSE c.priority_score END DESC, c.created_at DESC"""
    with get_db() as db:
        rows = db.execute(query, params).fetchall()
        data = [complaint_record(db, row) for row in rows]
        teams = [
            dict(team) for team in db.execute(
                """SELECT t.id, t.name, d.name AS department_name
                   FROM response_teams t JOIN departments d ON d.id = t.department_id ORDER BY t.id"""
            ).fetchall()
        ] if role == "admin" else []
    return jsonify({"complaints": data, "teams": teams})


@app.post("/api/complaints")
@csrf_required
@role_required("citizen")
def create_complaint():
    title = request.form.get("title", "").strip()
    description = request.form.get("description", "").strip()
    category = request.form.get("category", "")
    location_name = request.form.get("location_name", "").strip()[:160]
    if not 5 <= len(title) <= 120:
        return error("Title must be between 5 and 120 characters.")
    if not 15 <= len(description) <= 2000:
        return error("Description must be between 15 and 2,000 characters.")
    if category not in CATEGORIES:
        return error("Choose a valid issue category.")
    try:
        lat, lng = float(request.form.get("latitude", "")), float(request.form.get("longitude", ""))
        severity = int(request.form.get("severity", "3"))
    except (TypeError, ValueError):
        return error("Select a location and severity.")
    if not -90 <= lat <= 90 or not -180 <= lng <= 180 or severity not in range(1, 6):
        return error("Location or severity is outside the valid range.")
    image = request.files.get("image")
    try:
        with get_db() as db:
            stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
            score = priority_for(db, category, severity, lat, lng, stamp)["score"]
            ref = public_id(db)
            cursor = db.execute(
                """INSERT INTO complaints
                   (public_id, user_id, title, description, category, severity,
                    latitude, longitude, location_name, priority_score, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    ref, session["user_id"], title, description, category, severity,
                    lat, lng, location_name, score, stamp, stamp,
                ),
            )
            complaint_id = cursor.lastrowid
            db.execute(
                """INSERT INTO status_history(complaint_id, status, note, changed_by)
                   VALUES (?, 'Submitted', 'Report received by Civic Connect', ?)""",
                (complaint_id, session["user_id"]),
            )
            if image and image.filename:
                filename = save_image(image, complaint_id, "report")
                db.execute(
                    "INSERT INTO complaint_images(complaint_id, filename, kind) VALUES (?, ?, 'report')",
                    (complaint_id, filename),
                )
    except ValueError as exc:
        return error(str(exc))
    return jsonify({"message": "Your report has been submitted.", "complaint_id": ref}), 201


@app.get("/api/complaints/<public_ref>")
@login_required
def complaint_detail(public_ref):
    with get_db() as db:
        row = db.execute(
            get_complaint_query() + " WHERE c.public_id = ? GROUP BY c.id", (public_ref,)
        ).fetchone()
        if not row:
            return error("Complaint not found.", 404)
        if session["role"] == "citizen" and row["user_id"] != session["user_id"]:
            return error("You can only view your own reports.", 403)
        if session["role"] == "responder" and row["team_id"] != db.execute(
            "SELECT team_id FROM users WHERE id = ?", (session["user_id"],)
        ).fetchone()["team_id"]:
            return error("This report is not assigned to your response team.", 403)
        return jsonify({"complaint": complaint_record(db, row)})


@app.post("/api/complaints/<int:complaint_id>/assign")
@csrf_required
@role_required("admin")
def assign_complaint(complaint_id):
    payload = request.get_json(silent=True) or {}
    try:
        team_id = int(payload.get("team_id", ""))
    except (TypeError, ValueError):
        return error("Choose a response team.")
    with get_db() as db:
        row = db.execute(
            "SELECT id, public_id, user_id, status FROM complaints WHERE id = ?", (complaint_id,)
        ).fetchone()
        team = db.execute("SELECT id, name FROM response_teams WHERE id = ?", (team_id,)).fetchone()
        if not row or not team:
            return error("Complaint or response team not found.", 404)
        db.execute(
            "UPDATE complaint_assignments SET active = 0 WHERE complaint_id = ? AND active = 1",
            (complaint_id,),
        )
        db.execute(
            """INSERT INTO complaint_assignments(complaint_id, team_id, assigned_by)
               VALUES (?, ?, ?)""",
            (complaint_id, team_id, session["user_id"]),
        )
        if row["status"] in ("Submitted", "Under Review"):
            db.execute(
                "UPDATE complaints SET status = 'Assigned', updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                (complaint_id,),
            )
            db.execute(
                """INSERT INTO status_history(complaint_id, status, note, changed_by)
                   VALUES (?, 'Assigned', ?, ?)""",
                (complaint_id, f"Assigned to {team['name']}", session["user_id"]),
            )
            add_notification(db, row["user_id"], complaint_id, f"Your report was assigned to {team['name']}.")
        responder_ids = db.execute("SELECT id FROM users WHERE team_id = ?", (team_id,)).fetchall()
        for responder in responder_ids:
            add_notification(db, responder["id"], complaint_id, f"{row['public_id']} was assigned to your team.")
    return jsonify({"message": f"Assigned to {team['name']}."})


@app.post("/api/complaints/<int:complaint_id>/status")
@csrf_required
@role_required("admin", "responder")
def update_status(complaint_id):
    payload = request.get_json(silent=True) or {}
    status = payload.get("status")
    note = str(payload.get("note", "")).strip()[:240]
    if status not in STATUSES:
        return error("Choose a valid workflow status.")
    with get_db() as db:
        row = db.execute(
            get_complaint_query() + " WHERE c.id = ? GROUP BY c.id", (complaint_id,)
        ).fetchone()
        if not row:
            return error("Complaint not found.", 404)
        if session["role"] == "responder":
            team_id = db.execute("SELECT team_id FROM users WHERE id = ?", (session["user_id"],)).fetchone()["team_id"]
            if not team_id or row["team_id"] != team_id:
                return error("This report is not assigned to your response team.", 403)
            if status not in ("In Progress", "Resolved"):
                return error("Response teams can mark work In Progress or Resolved.")
        if status != row["status"]:
            resolved_at = "CURRENT_TIMESTAMP" if status == "Resolved" else "NULL"
            db.execute(
                f"UPDATE complaints SET status = ?, updated_at = CURRENT_TIMESTAMP, resolved_at = {resolved_at} WHERE id = ?",
                (status, complaint_id),
            )
            db.execute(
                "INSERT INTO status_history(complaint_id, status, note, changed_by) VALUES (?, ?, ?, ?)",
                (complaint_id, status, note or f"Status changed to {status}", session["user_id"]),
            )
            add_notification(
                db, row["user_id"], complaint_id,
                f"{row['public_id']} status updated: {status}.",
            )
    return jsonify({"message": "Complaint status updated."})


@app.post("/api/complaints/<int:complaint_id>/priority")
@csrf_required
@role_required("admin")
def override_priority(complaint_id):
    payload = request.get_json(silent=True) or {}
    priority = payload.get("priority")
    if priority not in PRIORITIES:
        return error("Choose Critical, High, Medium, or Low.")
    with get_db() as db:
        cursor = db.execute(
            "UPDATE complaints SET priority_override = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
            (priority, complaint_id),
        )
        if cursor.rowcount == 0:
            return error("Complaint not found.", 404)
    return jsonify({"message": f"Priority overridden to {priority}."})


@app.post("/api/complaints/<int:complaint_id>/resolution-image")
@csrf_required
@role_required("admin", "responder")
def resolution_image(complaint_id):
    with get_db() as db:
        row = db.execute(
            "SELECT c.id, a.team_id FROM complaints c LEFT JOIN complaint_assignments a ON a.complaint_id = c.id AND a.active = 1 WHERE c.id = ?",
            (complaint_id,),
        ).fetchone()
        if not row:
            return error("Complaint not found.", 404)
        if session["role"] == "responder":
            team_id = db.execute("SELECT team_id FROM users WHERE id = ?", (session["user_id"],)).fetchone()["team_id"]
            if team_id != row["team_id"]:
                return error("This report is not assigned to your response team.", 403)
        try:
            filename = save_image(request.files.get("image"), complaint_id, "resolution")
        except ValueError as exc:
            return error(str(exc))
        if not filename:
            return error("Choose a resolution photo to upload.")
        db.execute(
            "INSERT INTO complaint_images(complaint_id, filename, kind) VALUES (?, ?, 'resolution')",
            (complaint_id, filename),
        )
    return jsonify({"message": "Resolution photo uploaded.", "url": f"/uploads/{filename}"})


@app.get("/api/notifications")
@login_required
def notifications():
    with get_db() as db:
        rows = db.execute(
            """SELECT n.id, n.message, n.is_read, n.created_at, c.public_id
               FROM notifications n JOIN complaints c ON c.id = n.complaint_id
               WHERE n.user_id = ? ORDER BY n.id DESC LIMIT 20""",
            (session["user_id"],),
        ).fetchall()
    return jsonify({"notifications": [dict(row) for row in rows]})


@app.post("/api/notifications/read")
@csrf_required
@login_required
def mark_notifications_read():
    with get_db() as db:
        db.execute("UPDATE notifications SET is_read = 1 WHERE user_id = ?", (session["user_id"],))
    return jsonify({"message": "Notifications marked as read."})


@app.get("/api/analytics")
@role_required("admin")
def analytics():
    with get_db() as db:
        total = db.execute("SELECT COUNT(*) FROM complaints").fetchone()[0]
        pending = db.execute(
            "SELECT COUNT(*) FROM complaints WHERE status NOT IN ('Resolved', 'Closed')"
        ).fetchone()[0]
        resolved = db.execute(
            "SELECT COUNT(*) FROM complaints WHERE status IN ('Resolved', 'Closed')"
        ).fetchone()[0]
        critical = db.execute(
            "SELECT COUNT(*) FROM complaints WHERE priority_override = 'Critical' OR (priority_override IS NULL AND priority_score >= 80)"
        ).fetchone()[0]
        categories = db.execute(
            "SELECT category AS label, COUNT(*) AS value FROM complaints GROUP BY category ORDER BY value DESC"
        ).fetchall()
        areas = db.execute(
            """SELECT COALESCE(NULLIF(location_name, ''), 'Neighbourhood') AS label, COUNT(*) AS value
               FROM complaints GROUP BY label ORDER BY value DESC LIMIT 6"""
        ).fetchall()
        monthly = db.execute(
            """SELECT strftime('%Y-%m', created_at) AS label, COUNT(*) AS value
               FROM complaints GROUP BY label ORDER BY label"""
        ).fetchall()
        departments = db.execute(
            """SELECT d.name AS label,
                      SUM(CASE WHEN c.status IN ('Resolved', 'Closed') THEN 1 ELSE 0 END) AS resolved,
                      COUNT(c.id) AS total
               FROM departments d
               LEFT JOIN response_teams t ON t.department_id = d.id
               LEFT JOIN complaint_assignments a ON a.team_id = t.id AND a.active = 1
               LEFT JOIN complaints c ON c.id = a.complaint_id
               GROUP BY d.id ORDER BY total DESC"""
        ).fetchall()
        average = db.execute(
            """SELECT AVG((julianday(resolved_at) - julianday(created_at)) * 24)
               FROM complaints WHERE resolved_at IS NOT NULL"""
        ).fetchone()[0]
    return jsonify({
        "totals": {
            "total": total, "pending": pending, "critical": critical, "resolved": resolved,
            "average_resolution_hours": round(average, 1) if average is not None else None,
        },
        "categories": [dict(row) for row in categories],
        "areas": [dict(row) for row in areas],
        "monthly": [dict(row) for row in monthly],
        "departments": [dict(row) for row in departments],
    })


@app.cli.command("init-db")
def init_db_command():
    init_db()
    print("Civic Connect database initialized with demonstration data.")


init_db()
with get_db() as _db:
    for _row in _db.execute(
        "SELECT id, category, severity, latitude, longitude, created_at FROM complaints"
    ).fetchall():
        _score = priority_for(
            _db, _row["category"], _row["severity"], _row["latitude"],
            _row["longitude"], _row["created_at"],
        )["score"]
        _db.execute("UPDATE complaints SET priority_score = ? WHERE id = ?", (_score, _row["id"]))

if __name__ == "__main__":
    app.run(debug=os.environ.get("FLASK_DEBUG", "true").lower() == "true")
