import os
import re
import sqlite3
import uuid
from datetime import date, datetime
from functools import wraps
from pathlib import Path

from flask import Flask, abort, current_app, flash, g, redirect, render_template, request, send_from_directory, session, url_for
from werkzeug.security import check_password_hash, generate_password_hash
from werkzeug.utils import secure_filename


CATEGORIES = ["Electronics", "ID cards", "Books", "Bags", "Keys", "Clothing", "Accessories", "Other"]
LOCATIONS = ["Library", "Canteen", "Computer labs", "Auditorium", "Parking area", "Sports complex", "Student center", "Other"]
ALLOWED_EXTENSIONS = {"jpg", "jpeg", "png", "webp"}

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    email TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    role TEXT NOT NULL DEFAULT 'student'
);
CREATE TABLE IF NOT EXISTS items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES users(id),
    kind TEXT NOT NULL CHECK(kind IN ('lost', 'found')),
    title TEXT NOT NULL,
    category TEXT NOT NULL,
    description TEXT NOT NULL,
    location TEXT NOT NULL,
    event_date TEXT NOT NULL,
    photo TEXT,
    verification_details TEXT,
    status TEXT NOT NULL DEFAULT 'open',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS claims (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    item_id INTEGER NOT NULL REFERENCES items(id),
    user_id INTEGER NOT NULL REFERENCES users(id),
    details TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(item_id, user_id)
);
CREATE TABLE IF NOT EXISTS notifications (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES users(id),
    message TEXT NOT NULL,
    item_id INTEGER REFERENCES items(id),
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    read_at TEXT
);
"""


def create_app(test_config=None):
    app = Flask(__name__)
    app.config.from_mapping(
        SECRET_KEY=os.environ.get("SECRET_KEY", "local-development-key-change-before-deploy"),
        DATABASE=os.environ.get("DATABASE_PATH", str(Path(app.instance_path) / "lostfound.db")),
        UPLOAD_FOLDER=os.environ.get("UPLOAD_FOLDER", str(Path(app.instance_path) / "uploads")),
        MAX_CONTENT_LENGTH=5 * 1024 * 1024,
        ADMIN_EMAIL=os.environ.get("ADMIN_EMAIL", "admin@campus.edu").lower(),
        ADMIN_PASSWORD=os.environ.get("ADMIN_PASSWORD", "CampusAdmin123!"),
    )
    if test_config:
        app.config.update(test_config)

    Path(app.config["DATABASE"]).parent.mkdir(parents=True, exist_ok=True)
    Path(app.config["UPLOAD_FOLDER"]).mkdir(parents=True, exist_ok=True)
    app.config["CATEGORIES"] = CATEGORIES
    app.config["LOCATIONS"] = LOCATIONS

    with app.app_context():
        init_db()

    @app.context_processor
    def inject_shell_data():
        unread_count = 0
        if g.get("user"):
            unread_count = get_db().execute(
                "SELECT COUNT(*) FROM notifications WHERE user_id = ? AND read_at IS NULL",
                (g.user["id"],),
            ).fetchone()[0]
        return {"unread_count": unread_count}

    @app.before_request
    def load_user():
        user_id = session.get("user_id")
        g.user = get_db().execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone() if user_id else None

    @app.teardown_appcontext
    def close_db(_error=None):
        connection = g.pop("db", None)
        if connection is not None:
            connection.close()

    @app.route("/")
    def index():
        query = request.args.get("q", "").strip()
        kind = request.args.get("kind", "")
        category = request.args.get("category", "")
        location = request.args.get("location", "")
        status = request.args.get("status", "open")
        clauses = []
        values = []
        if query:
            clauses.append("(i.title LIKE ? OR i.description LIKE ?)")
            values.extend([f"%{query}%", f"%{query}%"])
        if kind in ("lost", "found"):
            clauses.append("i.kind = ?")
            values.append(kind)
        if category in CATEGORIES:
            clauses.append("i.category = ?")
            values.append(category)
        if location in LOCATIONS:
            clauses.append("i.location = ?")
            values.append(location)
        if status in ("open", "returned"):
            clauses.append("i.status = ?")
            values.append(status)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        items = get_db().execute(
            f"SELECT i.*, u.name AS reporter FROM items i JOIN users u ON u.id = i.user_id {where} ORDER BY i.created_at DESC",
            values,
        ).fetchall()
        return render_template("index.html", items=items, filters={"q": query, "kind": kind, "category": category, "location": location, "status": status})

    @app.route("/register", methods=["GET", "POST"])
    def register():
        if request.method == "POST":
            name = request.form.get("name", "").strip()
            email = request.form.get("email", "").strip().lower()
            password = request.form.get("password", "")
            if not name or len(name) > 80 or not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", email):
                flash("Enter your name and a valid email address.", "error")
            elif len(password) < 8:
                flash("Use a password with at least 8 characters.", "error")
            else:
                try:
                    cursor = get_db().execute(
                        "INSERT INTO users (name, email, password_hash) VALUES (?, ?, ?)",
                        (name, email, generate_password_hash(password)),
                    )
                    get_db().commit()
                    session.clear()
                    session["user_id"] = cursor.lastrowid
                    flash("Your student account is ready.", "success")
                    return redirect(url_for("index"))
                except sqlite3.IntegrityError:
                    flash("An account with that email already exists.", "error")
        return render_template("auth.html", mode="register")

    @app.route("/login", methods=["GET", "POST"])
    def login():
        if request.method == "POST":
            email = request.form.get("email", "").strip().lower()
            user = get_db().execute("SELECT * FROM users WHERE email = ?", (email,)).fetchone()
            if user and check_password_hash(user["password_hash"], request.form.get("password", "")):
                session.clear()
                session["user_id"] = user["id"]
                return redirect(url_for("admin" if user["role"] == "admin" else "index"))
            flash("Email or password is incorrect.", "error")
        return render_template("login.html")

    @app.post("/logout")
    def logout():
        session.clear()
        return redirect(url_for("index"))

    @app.route("/report", methods=["GET", "POST"])
    @login_required
    def report():
        if request.method == "POST":
            kind = request.form.get("kind", "")
            title = request.form.get("title", "").strip()
            category = request.form.get("category", "")
            description = request.form.get("description", "").strip()
            location = request.form.get("location", "")
            event_date = request.form.get("event_date", "")
            verification = request.form.get("verification_details", "").strip()
            try:
                date.fromisoformat(event_date)
                valid_date = True
            except ValueError:
                valid_date = False
            if kind not in ("lost", "found") or category not in CATEGORIES or location not in LOCATIONS:
                flash("Choose a valid report type, category, and campus location.", "error")
            elif not title or len(title) > 100 or len(description) < 10 or len(description) > 1500 or not valid_date:
                flash("Add a short title, a description of 10–1,500 characters, and a valid date.", "error")
            else:
                photo_name = None
                photo = request.files.get("photo")
                if photo and photo.filename:
                    extension = photo.filename.rsplit(".", 1)[-1].lower() if "." in photo.filename else ""
                    if extension not in ALLOWED_EXTENSIONS:
                        flash("Photos must be JPG, PNG, or WEBP files.", "error")
                        return render_template("report.html")
                    photo_name = f"{uuid.uuid4().hex}.{extension}"
                    photo.save(Path(app.config["UPLOAD_FOLDER"]) / secure_filename(photo_name))
                cursor = get_db().execute(
                    "INSERT INTO items (user_id, kind, title, category, description, location, event_date, photo, verification_details) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (g.user["id"], kind, title, category, description, location, event_date, photo_name, verification if kind == "found" else None),
                )
                get_db().commit()
                flash("Your report is now on the campus board.", "success")
                return redirect(url_for("item_detail", item_id=cursor.lastrowid))
        return render_template("report.html")

    @app.route("/items/<int:item_id>", methods=["GET", "POST"])
    def item_detail(item_id):
        item = get_db().execute(
            "SELECT i.*, u.name AS reporter FROM items i JOIN users u ON u.id = i.user_id WHERE i.id = ?",
            (item_id,),
        ).fetchone()
        if item is None:
            abort(404)
        if request.method == "POST":
            if not g.user:
                return redirect(url_for("login"))
            if item["kind"] != "found" or item["status"] != "open" or item["user_id"] == g.user["id"]:
                abort(403)
            details = request.form.get("details", "").strip()
            if len(details) < 10 or len(details) > 1000:
                flash("Add at least 10 characters describing how you can identify this item.", "error")
            else:
                try:
                    get_db().execute("INSERT INTO claims (item_id, user_id, details) VALUES (?, ?, ?)", (item_id, g.user["id"], details))
                    get_db().commit()
                    flash("Claim submitted privately for admin review.", "success")
                    return redirect(url_for("dashboard"))
                except sqlite3.IntegrityError:
                    flash("You have already submitted a claim for this item.", "error")
        matches = []
        if item["kind"] == "lost":
            candidates = get_db().execute(
                "SELECT i.*, u.name AS reporter FROM items i JOIN users u ON u.id = i.user_id WHERE i.kind = 'found' AND i.status = 'open' AND i.id != ?",
                (item_id,),
            ).fetchall()
            matches = sorted(
                ((match_score(item, candidate), candidate) for candidate in candidates),
                key=lambda result: result[0], reverse=True,
            )
            matches = [result for result in matches if result[0] >= 20][:4]
        existing_claim = None
        if g.user:
            existing_claim = get_db().execute("SELECT id FROM claims WHERE item_id = ? AND user_id = ?", (item_id, g.user["id"])).fetchone()
        return render_template("item.html", item=item, matches=matches, existing_claim=existing_claim)

    @app.route("/my-activity")
    @login_required
    def dashboard():
        db = get_db()
        items = db.execute("SELECT * FROM items WHERE user_id = ? ORDER BY created_at DESC", (g.user["id"],)).fetchall()
        claims = db.execute(
            "SELECT c.*, i.title, i.id AS item_id, i.status AS item_status FROM claims c JOIN items i ON i.id = c.item_id WHERE c.user_id = ? ORDER BY c.created_at DESC",
            (g.user["id"],),
        ).fetchall()
        notifications = db.execute("SELECT * FROM notifications WHERE user_id = ? ORDER BY created_at DESC LIMIT 8", (g.user["id"],)).fetchall()
        return render_template("dashboard.html", items=items, claims=claims, notifications=notifications)

    @app.post("/notifications/<int:notification_id>/read")
    @login_required
    def mark_notification_read(notification_id):
        get_db().execute(
            "UPDATE notifications SET read_at = ? WHERE id = ? AND user_id = ?",
            (datetime.utcnow().isoformat(timespec="seconds"), notification_id, g.user["id"]),
        )
        get_db().commit()
        return redirect(url_for("dashboard"))

    @app.route("/admin")
    @admin_required
    def admin():
        db = get_db()
        lost_reports = db.execute("SELECT * FROM items WHERE kind = 'lost' AND status = 'open'").fetchall()
        found_reports = db.execute("SELECT * FROM items WHERE kind = 'found' AND status = 'open'").fetchall()
        potential_matches = sum(
            match_score(lost_report, found_report) >= 20
            for lost_report in lost_reports
            for found_report in found_reports
        )
        stats = {
            "reports": db.execute("SELECT COUNT(*) FROM items").fetchone()[0],
            "matches": potential_matches,
            "claims": db.execute("SELECT COUNT(*) FROM claims WHERE status = 'pending'").fetchone()[0],
            "returned": db.execute("SELECT COUNT(*) FROM items WHERE status = 'returned'").fetchone()[0],
        }
        pending = db.execute(
            "SELECT c.*, i.title, i.id AS item_id, i.verification_details, u.name AS claimant FROM claims c JOIN items i ON i.id = c.item_id JOIN users u ON u.id = c.user_id WHERE c.status = 'pending' ORDER BY c.created_at ASC"
        ).fetchall()
        categories = db.execute("SELECT category, COUNT(*) AS count FROM items GROUP BY category ORDER BY count DESC LIMIT 5").fetchall()
        locations = db.execute("SELECT location, COUNT(*) AS count FROM items GROUP BY location ORDER BY count DESC LIMIT 5").fetchall()
        recent_items = db.execute("SELECT * FROM items ORDER BY created_at DESC LIMIT 8").fetchall()
        return render_template("admin.html", stats=stats, pending=pending, categories=categories, locations=locations, recent_items=recent_items)

    @app.post("/admin/claims/<int:claim_id>")
    @admin_required
    def review_claim(claim_id):
        decision = request.form.get("decision")
        if decision not in ("approved", "rejected"):
            abort(400)
        db = get_db()
        claim = db.execute("SELECT * FROM claims WHERE id = ? AND status = 'pending'", (claim_id,)).fetchone()
        if claim is None:
            abort(404)
        db.execute("UPDATE claims SET status = ? WHERE id = ?", (decision, claim_id))
        if decision == "approved":
            db.execute("UPDATE items SET status = 'returned' WHERE id = ?", (claim["item_id"],))
            db.execute("UPDATE claims SET status = 'rejected' WHERE item_id = ? AND id != ? AND status = 'pending'", (claim["item_id"], claim_id))
        message = "Your claim was approved. Arrange collection with the campus desk." if decision == "approved" else "Your claim was not approved. Contact the campus desk if you need help."
        db.execute("INSERT INTO notifications (user_id, message, item_id) VALUES (?, ?, ?)", (claim["user_id"], message, claim["item_id"]))
        db.commit()
        flash(f"Claim {decision}.", "success")
        return redirect(url_for("admin"))

    @app.post("/admin/items/<int:item_id>/status")
    @admin_required
    def update_item_status(item_id):
        status = request.form.get("status")
        if status not in ("open", "returned", "archived"):
            abort(400)
        cursor = get_db().execute("UPDATE items SET status = ? WHERE id = ?", (status, item_id))
        if cursor.rowcount == 0:
            abort(404)
        get_db().commit()
        flash("Report status updated.", "success")
        return redirect(url_for("admin"))

    @app.route("/uploads/<path:filename>")
    def uploaded_file(filename):
        return send_from_directory(app.config["UPLOAD_FOLDER"], filename)

    @app.errorhandler(413)
    def file_too_large(_error):
        flash("Photo must be smaller than 5 MB.", "error")
        return redirect(url_for("report"))

    return app


def get_db():
    if "db" not in g:
        connection = sqlite3.connect(current_app.config["DATABASE"])
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        g.db = connection
    return g.db


def init_db():
    db = get_db()
    db.executescript(SCHEMA)
    admin_email = current_app.config["ADMIN_EMAIL"].lower()
    admin_password = current_app.config["ADMIN_PASSWORD"]
    existing = db.execute("SELECT id FROM users WHERE email = ?", (admin_email,)).fetchone()
    if not existing:
        db.execute(
            "INSERT INTO users (name, email, password_hash, role) VALUES (?, ?, ?, 'admin')",
            ("Campus administrator", admin_email, generate_password_hash(admin_password)),
        )
    db.commit()


def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not g.get("user"):
            flash("Sign in to continue.", "error")
            return redirect(url_for("login"))
        return view(*args, **kwargs)
    return wrapped


def admin_required(view):
    @wraps(view)
    @login_required
    def wrapped(*args, **kwargs):
        if g.user["role"] != "admin":
            abort(403)
        return view(*args, **kwargs)
    return wrapped


def match_score(lost_item, found_item):
    score = 35 if lost_item["category"] == found_item["category"] else 0
    lost_words = set(re.findall(r"[a-z0-9]+", f"{lost_item['title']} {lost_item['description']}".lower()))
    found_words = set(re.findall(r"[a-z0-9]+", f"{found_item['title']} {found_item['description']}".lower()))
    useful_words = {word for word in lost_words | found_words if len(word) > 2}
    overlap = len(lost_words & found_words) / max(1, len(useful_words))
    score += round(overlap * 40)
    if lost_item["location"] == found_item["location"]:
        score += 15
    try:
        days_apart = abs((date.fromisoformat(lost_item["event_date"]) - date.fromisoformat(found_item["event_date"])).days)
        if days_apart <= 2:
            score += 10
        elif days_apart <= 7:
            score += 5
    except ValueError:
        pass
    return min(score, 100)


app = create_app()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "5000")), debug=os.environ.get("FLASK_DEBUG") == "1")
