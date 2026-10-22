from datetime import datetime, timedelta
from pathlib import Path
import os
import sqlite3
import uuid

from flask import Flask, flash, jsonify, redirect, render_template, request, session, url_for
from werkzeug.security import check_password_hash, generate_password_hash
from werkzeug.utils import secure_filename

from ai.complaint_classifier import CATEGORY_OPTIONS, classify_complaint
from ai.duplicate_detector import find_similar
from ai.image_detector import analyze_image
from ai.priority import calculate_priority

ROOT = Path(__file__).resolve().parent
DATABASE = ROOT / "database.db"
UPLOAD_FOLDER = ROOT / "static" / "uploads"
ALLOWED_EXTENSIONS = {"png", "jpg", "jpeg", "webp"}
DEPARTMENTS = {"Water": "Water Supply Department", "Garbage": "Sanitation Department", "Road": "Engineering Department", "Drainage": "Engineering/Drainage Department", "Streetlight": "Electrical Department"}
STATUSES = ["Pending", "Assigned", "In Progress", "Resolved"]

app = Flask(__name__)
app.secret_key = os.environ.get("GRAM_PORTAL_SECRET", "dev-only-change-this-secret")
app.config["MAX_CONTENT_LENGTH"] = 5 * 1024 * 1024
UPLOAD_FOLDER.mkdir(parents=True, exist_ok=True)


def get_db():
    connection = sqlite3.connect(DATABASE)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    return connection


def _add_columns(connection, table, columns):
    existing = {row[1] for row in connection.execute(f"PRAGMA table_info({table})")}
    for name, definition in columns.items():
        if name not in existing:
            connection.execute(f"ALTER TABLE {table} ADD COLUMN {name} {definition}")


def init_db():
    connection = get_db()
    connection.executescript("""
        CREATE TABLE IF NOT EXISTS users (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL, email TEXT UNIQUE NOT NULL, password TEXT NOT NULL, role TEXT DEFAULT 'citizen');
        CREATE TABLE IF NOT EXISTS complaints (id INTEGER PRIMARY KEY AUTOINCREMENT, ticket TEXT UNIQUE NOT NULL, user_id INTEGER, title TEXT, description TEXT, category TEXT, priority TEXT, department TEXT, latitude REAL, longitude REAL, image TEXT, status TEXT DEFAULT 'Pending', created_at TEXT, deadline TEXT, officer_note TEXT, citizen_verified INTEGER DEFAULT 0, rating INTEGER);
        CREATE TABLE IF NOT EXISTS notifications (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, message TEXT, created_at TEXT, is_read INTEGER DEFAULT 0);
        CREATE TABLE IF NOT EXISTS complaint_clusters (id INTEGER PRIMARY KEY AUTOINCREMENT, cluster_code TEXT UNIQUE NOT NULL, category TEXT, latitude REAL, longitude REAL, created_at TEXT);
    """)
    _add_columns(connection, "complaints", {"ai_confidence": "REAL DEFAULT 0", "ai_priority_score": "INTEGER DEFAULT 0", "escalation_status": "TEXT DEFAULT 'ON TIME'", "cluster_id": "INTEGER", "resolved_at": "TEXT", "feedback": "TEXT", "duplicate_of": "TEXT", "sla_status": "TEXT DEFAULT 'ON TIME'"})
    _add_columns(connection, "notifications", {"is_read": "INTEGER DEFAULT 0"})
    admin = connection.execute("SELECT * FROM users WHERE email = ?", ("rajeevsamuel",)).fetchone()
    if not admin:
        connection.execute("INSERT INTO users (name,email,password,role) VALUES (?,?,?,?)", ("Administrator", "rajeevsamuel", generate_password_hash("2075"), "admin"))
    elif not admin["password"].startswith("scrypt:") and not admin["password"].startswith("pbkdf2:"):
        connection.execute("UPDATE users SET password = ? WHERE id = ?", (generate_password_hash("2075"), admin["id"]))
    connection.commit()
    connection.close()


def notify(connection, user_id, message):
    if user_id:
        connection.execute("INSERT INTO notifications (user_id,message,created_at) VALUES (?,?,?)", (user_id, message, datetime.now().isoformat(timespec="minutes")))


def refresh_sla(connection):
    now = datetime.now()
    rows = connection.execute("SELECT id,user_id,ticket,deadline,status,escalation_status FROM complaints WHERE status != 'Resolved' AND deadline IS NOT NULL").fetchall()
    for row in rows:
        try:
            deadline = datetime.fromisoformat(row["deadline"])
        except ValueError:
            continue
        remaining = (deadline - now).total_seconds()
        if remaining < 0:
            state = "ESCALATED"
        elif remaining < 86400:
            state = "DUE SOON"
        else:
            state = "ON TIME"
        if state == "ESCALATED" and row["escalation_status"] != "ESCALATED":
            notify(connection, row["user_id"], f"Complaint {row['ticket']} is overdue and escalated.")
        connection.execute("UPDATE complaints SET sla_status=?, escalation_status=? WHERE id=?", (state, state, row["id"]))
    connection.commit()


def login_required(role=None):
    if not session.get("uid") or (role and session.get("role") != role):
        return redirect(url_for("login"))
    return None


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        name, email, password = request.form.get("name", "").strip(), request.form.get("email", "").strip().lower(), request.form.get("password", "")
        if not name or not email or len(password) < 6:
            flash("Name, email, and a password of at least 6 characters are required.")
        else:
            try:
                connection = get_db()
                cursor = connection.execute("INSERT INTO users (name,email,password) VALUES (?,?,?)", (name, email, generate_password_hash(password)))
                connection.commit()
                user_id = cursor.lastrowid
                connection.close()
                session.update(uid=user_id, role="citizen", name=name)
                flash("Registration successful. Welcome to your dashboard!")
                return redirect(url_for("citizen"))
            except sqlite3.IntegrityError:
                flash("Email already registered.")
    return render_template("register.html")


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        email, password = request.form.get("email", "").strip().lower(), request.form.get("password", "")
        connection = get_db(); user = connection.execute("SELECT * FROM users WHERE lower(email)=?", (email,)).fetchone(); connection.close()
        if user and check_password_hash(user["password"], password):
            session.update(uid=user["id"], role=user["role"], name=user["name"])
            return redirect(url_for("admin" if user["role"] == "admin" else "citizen"))
        flash("Invalid email or password.")
    return render_template("login.html")


@app.route("/logout")
def logout():
    session.clear(); return redirect(url_for("index"))


@app.route("/citizen")
def citizen():
    denied = login_required("citizen")
    if denied: return denied
    connection = get_db(); refresh_sla(connection)
    complaints = connection.execute("SELECT * FROM complaints WHERE user_id=? ORDER BY id DESC", (session["uid"],)).fetchall(); connection.close()
    return render_template("citizen_dashboard.html", complaints=complaints)


@app.route("/complaint", methods=["GET", "POST"])
def complaint():
    denied = login_required("citizen")
    if denied: return denied
    if request.method == "POST":
        title, description = request.form.get("title", "").strip(), request.form.get("description", "").strip()
        if not title or not description: flash("Title and description are required."); return render_template("complaint.html")
        text = f"{title} {description}"; category, confidence, department = classify_complaint(text)
        created = datetime.now().isoformat(timespec="minutes")
        connection = get_db(); similar = find_similar(connection, description, category, _number(request.form.get("latitude")), _number(request.form.get("longitude")))
        score, priority = calculate_priority(text, category, len(similar), created)
        image_name = None; uploaded = request.files.get("image")
        if uploaded and uploaded.filename:
            safe_name = secure_filename(uploaded.filename)
            if not safe_name or Path(safe_name).suffix.lower().lstrip(".") not in ALLOWED_EXTENSIONS:
                flash("Only PNG, JPG, JPEG, and WEBP images are allowed."); connection.close(); return render_template("complaint.html")
            image_name = f"{uuid.uuid4().hex}_{safe_name}"; uploaded.save(UPLOAD_FOLDER / image_name); analyze_image(str(UPLOAD_FOLDER / image_name))
        ticket = f"GM-{datetime.now():%Y%m%d}-{uuid.uuid4().hex[:6].upper()}"; hours = {"CRITICAL": 24, "HIGH": 48, "MEDIUM": 120, "LOW": 168}[priority]; deadline = (datetime.now() + timedelta(hours=hours)).isoformat(timespec="minutes")
        connection.execute("INSERT INTO complaints (ticket,user_id,title,description,category,priority,department,latitude,longitude,image,created_at,deadline,ai_confidence,ai_priority_score,sla_status,duplicate_of) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", (ticket, session["uid"], title, description, category, priority, department, _number(request.form.get("latitude")), _number(request.form.get("longitude")), image_name, created, deadline, confidence, score, "ON TIME", similar[0]["ticket"] if similar else None))
        complaint_id = connection.execute("SELECT last_insert_rowid()").fetchone()[0]
        cluster_id = None
        if similar:
            cluster_id = connection.execute("SELECT cluster_id FROM complaints WHERE ticket=?", (similar[0]["ticket"],)).fetchone()[0]
        if cluster_id is None:
            cluster_code = f"GMC-{complaint_id:03d}"
            connection.execute("INSERT INTO complaint_clusters (cluster_code,category,latitude,longitude,created_at) VALUES (?,?,?,?,?)", (cluster_code, category, _number(request.form.get("latitude")), _number(request.form.get("longitude")), created))
            cluster_id = connection.execute("SELECT last_insert_rowid()").fetchone()[0]
        connection.execute("UPDATE complaints SET cluster_id=? WHERE id=?", (cluster_id, complaint_id))
        notify(connection, session["uid"], f"Complaint {ticket} submitted. Department assigned: {department}."); notify_admins(connection, f"New complaint {ticket} received ({priority}).")
        connection.commit(); connection.close()
        flash(f"Complaint submitted: {ticket}. AI confidence: {confidence:.0%}." + (f" Possible duplicate of {similar[0]['ticket']}." if similar else "")); return redirect(url_for("citizen"))
    return render_template("complaint.html")


def _number(value):
    try:
        number = float(value); return number if -90 <= number <= 90 else None
    except (TypeError, ValueError): return None


def notify_admins(connection, message):
    for row in connection.execute("SELECT id FROM users WHERE role='admin'"):
        notify(connection, row["id"], message)


@app.route("/tracking/<ticket>")
def tracking(ticket):
    if not session.get("uid"): return redirect(url_for("login"))
    connection = get_db(); refresh_sla(connection); c = connection.execute("SELECT * FROM complaints WHERE ticket=?", (ticket,)).fetchone(); connection.close()
    if not c or (session.get("role") == "citizen" and c["user_id"] != session["uid"]): return "Not found", 404
    return render_template("tracking.html", c=c)


@app.route("/admin")
def admin():
    denied = login_required("admin")
    if denied: return denied
    connection = get_db(); refresh_sla(connection)
    filters = {key: request.args.get(key, "").strip() for key in ("search", "category", "department", "status", "priority")}
    clauses, params = [], []
    if filters["search"]: clauses.append("(c.ticket LIKE ? OR c.title LIKE ? OR c.description LIKE ? OR c.latitude LIKE ? OR c.longitude LIKE ?)"); params.extend([f"%{filters['search']}%"] * 5)
    for key in ("category", "department", "status", "priority"):
        if filters[key]: clauses.append(f"c.{key}=?"); params.append(filters[key])
    where = " WHERE " + " AND ".join(clauses) if clauses else ""
    complaints = connection.execute(f"SELECT c.*,u.name FROM complaints c LEFT JOIN users u ON c.user_id=u.id{where} ORDER BY c.id DESC", params).fetchall()
    stats = connection.execute("SELECT COUNT(*) total, SUM(status='Pending') pending, SUM(status='In Progress') in_progress, SUM(status='Resolved') resolved, SUM(priority='CRITICAL') critical, SUM(priority='HIGH') high, SUM(sla_status='ESCALATED') overdue, SUM(escalation_status='ESCALATED') escalated FROM complaints").fetchone()
    connection.close()
    return render_template("admin_dashboard.html", complaints=complaints, stats=stats, categories=CATEGORY_OPTIONS, selected_category=filters["category"], filters=filters)


@app.post("/admin/update/<int:cid>")
def update(cid):
    denied = login_required("admin")
    if denied: return jsonify(ok=False), 403
    status = request.form.get("status", "Pending"); status = status if status in STATUSES else "Pending"; note = request.form.get("note", "")[:1000]
    connection = get_db(); row = connection.execute("SELECT user_id,ticket,status FROM complaints WHERE id=?", (cid,)).fetchone()
    if not row: connection.close(); return "Not found", 404
    resolved = datetime.now().isoformat(timespec="minutes") if status == "Resolved" else None
    connection.execute("UPDATE complaints SET status=?,officer_note=?,resolved_at=? WHERE id=?", (status, note, resolved, cid)); notify(connection, row["user_id"], f"Complaint {row['ticket']} status changed to {status}."); connection.commit(); connection.close(); return redirect(url_for("admin"))


@app.post("/admin/delete/<int:cid>")
def delete_complaint(cid):
    denied = login_required("admin")
    if denied: return jsonify(ok=False), 403
    connection = get_db(); connection.execute("DELETE FROM complaints WHERE id=?", (cid,)); connection.commit(); connection.close(); flash("Complaint deleted successfully."); return redirect(url_for("admin"))


@app.post("/verify/<ticket>")
def verify(ticket):
    denied = login_required("citizen")
    if denied: return denied
    rating = max(1, min(5, int(request.form.get("rating", 5)))); feedback = request.form.get("feedback", "")[:1000]; connection = get_db(); connection.execute("UPDATE complaints SET citizen_verified=1,rating=?,feedback=? WHERE ticket=? AND user_id=? AND status='Resolved'", (rating, feedback, ticket, session["uid"])); connection.commit(); connection.close(); flash("Thank you for verifying the resolution."); return redirect(url_for("tracking", ticket=ticket))


@app.route("/api/notifications")
def notifications():
    if not session.get("uid"): return jsonify([])
    connection = get_db(); rows = connection.execute("SELECT message,created_at FROM notifications WHERE user_id=? ORDER BY id DESC LIMIT 10", (session["uid"],)).fetchall(); connection.close(); return jsonify([dict(row) for row in rows])


@app.route("/map")
def map_page():
    denied = login_required("admin")
    if denied: return denied
    connection = get_db(); rows = connection.execute("SELECT ticket,category,priority,status,latitude,longitude FROM complaints WHERE latitude IS NOT NULL AND longitude IS NOT NULL").fetchall(); connection.close(); return render_template("map.html", complaints=[dict(row) for row in rows])


init_db()

if __name__ == "__main__":
    app.run(debug=False, host="0.0.0.0", port=5000)
