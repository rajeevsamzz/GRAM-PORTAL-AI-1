from flask import (
    Flask,
    render_template,
    request,
    redirect,
    url_for,
    session,
    jsonify,
    flash
)

import sqlite3
import os
import uuid

from datetime import datetime, timedelta

from ai.complaint_classifier import (
    CATEGORY_OPTIONS,
    classify_complaint
)
from ai.duplicate_detector import find_duplicate
from ai.image_detector import analyze_image


app = Flask(__name__)

app.secret_key = "change-this-secret-key"

DATABASE = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "database.db"
)

UPLOAD_FOLDER = os.path.join(
    "static",
    "uploads"
)

os.makedirs(
    UPLOAD_FOLDER,
    exist_ok=True
)


# --------------------------------------------------
# DATABASE CONNECTION
# --------------------------------------------------

def get_db():

    connection = sqlite3.connect(
        DATABASE
    )

    connection.row_factory = sqlite3.Row

    return connection


# --------------------------------------------------
# INITIALIZE DATABASE
# --------------------------------------------------

def init_db():

    connection = get_db()

    connection.executescript("""

    CREATE TABLE IF NOT EXISTS users (

        id INTEGER PRIMARY KEY AUTOINCREMENT,

        name TEXT NOT NULL,

        email TEXT UNIQUE NOT NULL,

        password TEXT NOT NULL,

        role TEXT DEFAULT 'citizen'

    );


    CREATE TABLE IF NOT EXISTS complaints (

        id INTEGER PRIMARY KEY AUTOINCREMENT,

        ticket TEXT UNIQUE NOT NULL,

        user_id INTEGER,

        title TEXT,

        description TEXT,

        category TEXT,

        priority TEXT,

        department TEXT,

        latitude REAL,

        longitude REAL,

        image TEXT,

        status TEXT DEFAULT 'Pending',

        created_at TEXT,

        deadline TEXT,

        officer_note TEXT,

        citizen_verified INTEGER DEFAULT 0,

        rating INTEGER

    );


    CREATE TABLE IF NOT EXISTS notifications (

        id INTEGER PRIMARY KEY AUTOINCREMENT,

        user_id INTEGER,

        message TEXT,

        created_at TEXT

    );

    """)

    # Create or update the default admin account.
    admin = connection.execute(
        "SELECT id FROM users WHERE email = ? LIMIT 1",
        ("rajeevsamuel",)
    ).fetchone()

    if admin:
        connection.execute(
            "DELETE FROM users WHERE role = 'admin' AND id != ?",
            (admin["id"],)
        )
        admin_id = admin["id"]
    else:
        connection.execute(
            "DELETE FROM users WHERE role = 'admin'"
        )
        cursor = connection.execute(
            """
            INSERT INTO users (name, email, password, role)
            VALUES (?, ?, ?, ?)
            """,
            ("Administrator", "rajeevsamuel", "2075", "admin")
        )
        admin_id = cursor.lastrowid

    connection.execute(
        """
        UPDATE users
        SET name = ?, email = ?, password = ?, role = ?
        WHERE id = ?
        """,
        ("Administrator", "rajeevsamuel", "2075", "admin", admin_id)
    )

    connection.commit()

    connection.close()


# --------------------------------------------------
# HOME
# --------------------------------------------------

@app.route("/")
def index():

    return render_template(
        "index.html"
    )


# --------------------------------------------------
# REGISTER
# --------------------------------------------------

@app.route(
    "/register",
    methods=["GET", "POST"]
)
def register():

    if request.method == "POST":

        name = request.form["name"]

        email = request.form["email"]

        password = request.form["password"]

        try:

            connection = get_db()

            connection.execute(
                """
                INSERT INTO users
                (name, email, password)
                VALUES (?, ?, ?)
                """,
                (
                    name,
                    email,
                    password
                )
            )

            connection.commit()

            connection.close()

            flash(
                "Registration successful. Please login."
            )

            return redirect(
                url_for("login")
            )

        except sqlite3.IntegrityError:

            flash(
                "Email already registered."
            )

    return render_template(
        "register.html"
    )


# --------------------------------------------------
# LOGIN
# --------------------------------------------------

@app.route(
    "/login",
    methods=["GET", "POST"]
)
def login():

    if request.method == "POST":

        email = request.form["email"]

        password = request.form["password"]

        connection = get_db()

        user = connection.execute(
            """
            SELECT *
            FROM users
            WHERE email = ?
            AND password = ?
            """,
            (
                email,
                password
            )
        ).fetchone()

        connection.close()

        if user:

            session["uid"] = user["id"]

            session["role"] = user["role"]

            session["name"] = user["name"]

            if user["role"] == "admin":

                return redirect(
                    url_for("admin")
                )

            return redirect(
                url_for("citizen")
            )

        flash(
            "Invalid email or password."
        )

    return render_template(
        "login.html"
    )


# --------------------------------------------------
# LOGOUT
# --------------------------------------------------

@app.route("/logout")
def logout():

    session.clear()

    return redirect(
        url_for("index")
    )


# --------------------------------------------------
# CITIZEN DASHBOARD
# --------------------------------------------------

@app.route("/citizen")
def citizen():

    if "uid" not in session:

        return redirect(
            url_for("login")
        )

    if session["role"] != "citizen":

        return redirect(
            url_for("admin")
        )

    connection = get_db()

    complaints = connection.execute(
        """
        SELECT *
        FROM complaints
        WHERE user_id = ?
        ORDER BY id DESC
        """,
        (
            session["uid"],
        )
    ).fetchall()

    connection.close()

    return render_template(
        "citizen_dashboard.html",
        complaints=complaints
    )


# --------------------------------------------------
# NEW COMPLAINT
# --------------------------------------------------

@app.route(
    "/complaint",
    methods=["GET", "POST"]
)
def complaint():

    if "uid" not in session:

        return redirect(
            url_for("login")
        )

    if request.method == "POST":

        title = request.form["title"]

        description = request.form["description"]

        complete_text = (
            title + " " + description
        )

        # AI TEXT CLASSIFICATION

        category, priority, department = (
            classify_complaint(
                complete_text
            )
        )

        # GPS

        latitude = (
            request.form.get("latitude")
            or None
        )

        longitude = (
            request.form.get("longitude")
            or None
        )

        # IMAGE

        image_name = None

        uploaded_file = request.files.get(
            "image"
        )

        if uploaded_file and uploaded_file.filename:

            image_name = (
                f"{uuid.uuid4().hex}_"
                f"{uploaded_file.filename}"
            )

            uploaded_file.save(
                os.path.join(
                    UPLOAD_FOLDER,
                    image_name
                )
            )

        # IMAGE AI

        image_result = None

        if image_name:

            image_result = analyze_image(
                os.path.join(
                    UPLOAD_FOLDER,
                    image_name
                )
            )

        # Use image classification if available

        if (
            image_result
            and image_result.get("category")
            and image_result.get("confidence", 0) >= 0.65
        ):

            category = image_result["category"]

            department_map = {

                "Road": "Engineering",

                "Garbage": "Sanitation",

                "Social Problem": "Sanitation",

                "Streetlight": "Electrical",

                "Water": "Water Supply",

                "Water Problem": "Water Supply",

                "Drainage": "Sanitation",

                "Drainage Problem": "Sanitation",

                "PWD": "PWD Department",

                "Transportation Problem": "Transportation",

                "Milk Dairy Problem": "Dairy Department",

                "Electricity Problem": "Electrical",

                "Other Problems": "Panchayat Office"

            }

            department = department_map.get(
                category,
                department
            )

        connection = get_db()

        # DUPLICATE DETECTION

        duplicate = find_duplicate(
            connection,
            description,
            latitude,
            longitude,
            session["uid"]
        )

        # TICKET

        ticket = (
            "GM-"
            + datetime.now().strftime("%Y%m%d")
            + "-"
            + uuid.uuid4().hex[:6].upper()
        )

        # SLA

        days = {

            "High": 2,

            "Medium": 5,

            "Low": 7

        }

        deadline = (
            datetime.now()
            + timedelta(
                days=days.get(
                    priority,
                    7
                )
            )
        ).isoformat(
            timespec="minutes"
        )

        connection.execute(
            """
            INSERT INTO complaints
            (
                ticket,
                user_id,
                title,
                description,
                category,
                priority,
                department,
                latitude,
                longitude,
                image,
                created_at,
                deadline
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                ticket,
                session["uid"],
                title,
                description,
                category,
                priority,
                department,
                latitude,
                longitude,
                image_name,
                datetime.now().isoformat(
                    timespec="minutes"
                ),
                deadline
            )
        )

        connection.commit()

        connection.close()

        message = (
            f"Complaint submitted: {ticket}"
        )

        if duplicate:

            message += (
                f" Possible duplicate of {duplicate}"
            )

        flash(message)

        return redirect(
            url_for("citizen")
        )

    return render_template(
        "complaint.html"
    )


# --------------------------------------------------
# TRACK COMPLAINT
# --------------------------------------------------

@app.route(
    "/tracking/<ticket>"
)
def tracking(ticket):

    connection = get_db()

    complaint_data = connection.execute(
        """
        SELECT *
        FROM complaints
        WHERE ticket = ?
        """,
        (
            ticket,
        )
    ).fetchone()

    connection.close()

    return render_template(
        "tracking.html",
        c=complaint_data
    )


# --------------------------------------------------
# ADMIN DASHBOARD
# --------------------------------------------------

@app.route("/admin")
def admin():

    if session.get("role") != "admin":

        return redirect(
            url_for("login")
        )

    selected_category = request.args.get(
        "category",
        ""
    ).strip()

    connection = get_db()

    complaint_query = """
        SELECT
            c.*,
            u.name
        FROM complaints c

        JOIN users u
        ON c.user_id = u.id
    """
    complaint_params = []

    if selected_category:
        complaint_query += " WHERE c.category = ?"
        complaint_params.append(selected_category)

    complaint_query += " ORDER BY c.id DESC"

    complaints = connection.execute(
        complaint_query,
        complaint_params
    ).fetchall()

    stats = connection.execute(
        """
        SELECT

            COUNT(*) AS total,

            SUM(
                CASE
                    WHEN status = 'Resolved'
                    THEN 1
                    ELSE 0
                END
            ) AS resolved,

            SUM(
                CASE
                    WHEN status != 'Resolved'
                    THEN 1
                    ELSE 0
                END
            ) AS pending

        FROM complaints
        """
    ).fetchone()

    connection.close()

    return render_template(
        "admin_dashboard.html",
        complaints=complaints,
        stats=stats,
        categories=CATEGORY_OPTIONS,
        selected_category=selected_category
    )


# --------------------------------------------------
# ADMIN UPDATE
# --------------------------------------------------

@app.post(
    "/admin/update/<int:cid>"
)
def update(cid):

    if session.get("role") != "admin":

        return jsonify(
            ok=False
        ), 403

    status = request.form["status"]

    note = request.form.get(
        "note",
        ""
    )

    connection = get_db()

    connection.execute(
        """
        UPDATE complaints

        SET
            status = ?,
            officer_note = ?

        WHERE id = ?
        """,
        (
            status,
            note,
            cid
        )
    )

    complaint_data = connection.execute(
        """
        SELECT user_id, ticket
        FROM complaints
        WHERE id = ?
        """,
        (
            cid,
        )
    ).fetchone()

    connection.execute(
        """
        INSERT INTO notifications
        (
            user_id,
            message,
            created_at
        )
        VALUES (?, ?, ?)
        """,
        (
            complaint_data["user_id"],

            (
                f"Complaint "
                f"{complaint_data['ticket']} "
                f"status updated to {status}."
            ),

            datetime.now().isoformat(
                timespec="minutes"
            )
        )
    )

    connection.commit()

    connection.close()

    return redirect(
        url_for("admin")
    )


# --------------------------------------------------
# ADMIN DELETE
# --------------------------------------------------

@app.post(
    "/admin/delete/<int:cid>"
)
def delete_complaint(cid):

    if session.get("role") != "admin":

        return jsonify(
            ok=False
        ), 403

    connection = get_db()

    connection.execute(
        "DELETE FROM complaints WHERE id = ?",
        (cid,)
    )

    connection.commit()

    connection.close()

    flash(
        "Complaint deleted successfully."
    )

    return redirect(
        url_for("admin")
    )


# --------------------------------------------------
# CITIZEN VERIFICATION
# --------------------------------------------------

@app.post(
    "/verify/<ticket>"
)
def verify(ticket):

    if "uid" not in session:

        return redirect(
            url_for("login")
        )

    rating = int(
        request.form["rating"]
    )

    connection = get_db()

    connection.execute(
        """
        UPDATE complaints

        SET
            citizen_verified = 1,
            rating = ?

        WHERE
            ticket = ?
            AND user_id = ?
        """,
        (
            rating,
            ticket,
            session["uid"]
        )
    )

    connection.commit()

    connection.close()

    flash(
        "Thank you for verifying the resolution."
    )

    return redirect(
        url_for(
            "tracking",
            ticket=ticket
        )
    )


# --------------------------------------------------
# NOTIFICATIONS API
# --------------------------------------------------

@app.route(
    "/api/notifications"
)
def notifications():

    if "uid" not in session:

        return jsonify([])

    connection = get_db()

    rows = connection.execute(
        """
        SELECT
            message,
            created_at

        FROM notifications

        WHERE user_id = ?

        ORDER BY id DESC

        LIMIT 10
        """,
        (
            session["uid"],
        )
    ).fetchall()

    connection.close()

    return jsonify(
        [
            dict(row)
            for row in rows
        ]
    )


# --------------------------------------------------
# MAP
# --------------------------------------------------

@app.route("/map")
def map_page():

    connection = get_db()

    complaints = connection.execute(
        """
        SELECT
            ticket,
            category,
            priority,
            latitude,
            longitude,
            status

        FROM complaints

        WHERE
            latitude IS NOT NULL
            AND longitude IS NOT NULL
        """
    ).fetchall()

    connection.close()

    return render_template(
        "map.html",
        complaints=complaints
    )


# --------------------------------------------------
# START
# --------------------------------------------------

if __name__ == "__main__":

    init_db()

    app.run(
        debug=True,
        host="0.0.0.0",
        port=5000
    )