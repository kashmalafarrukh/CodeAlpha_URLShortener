import io
import re
import secrets
import sqlite3
import string
from datetime import datetime, timedelta, timezone
from urllib.parse import urlparse

import qrcode
from flask import (Flask, g, jsonify, redirect, render_template,
                   request, send_file)

app = Flask(__name__)
DATABASE = "urls.db"
ALPHABET = string.ascii_letters + string.digits
CUSTOM_CODE_PATTERN = re.compile(r"[A-Za-z0-9_-]{3,30}")
RESERVED_CODES = {"api", "static", "health"}
TIME_FORMAT = "%Y-%m-%d %H:%M:%S"


# ---------- Time helpers (all times are stored in UTC) ----------
def utc_now():
    return datetime.now(timezone.utc).replace(tzinfo=None)


def to_text(moment):
    return moment.strftime(TIME_FORMAT)


def is_expired(expires_at):
    return bool(expires_at) and expires_at <= to_text(utc_now())


# ---------- Database helpers ----------
def get_db():
    if "db" not in g:
        g.db = sqlite3.connect(DATABASE)
        g.db.row_factory = sqlite3.Row
    return g.db


@app.teardown_appcontext
def close_db(exception):
    db = g.pop("db", None)
    if db is not None:
        db.close()


def init_db():
    with sqlite3.connect(DATABASE) as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS urls (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                short_code TEXT UNIQUE NOT NULL,
                original_url TEXT NOT NULL,
                clicks INTEGER DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                expires_at TIMESTAMP,
                last_visited TIMESTAMP
            )
        """)
        # Upgrade older databases that don't have the new columns yet
        columns = [row[1] for row in conn.execute("PRAGMA table_info(urls)")]
        if "expires_at" not in columns:
            conn.execute("ALTER TABLE urls ADD COLUMN expires_at TIMESTAMP")
        if "last_visited" not in columns:
            conn.execute("ALTER TABLE urls ADD COLUMN last_visited TIMESTAMP")


def insert_url(db, code, original_url, expires_at):
    try:
        db.execute(
            "INSERT INTO urls (short_code, original_url, expires_at) VALUES (?, ?, ?)",
            (code, original_url, expires_at),
        )
        db.commit()
        return True
    except sqlite3.IntegrityError:
        return False


# ---------- Utility functions ----------
def is_valid_url(url):
    parsed = urlparse(url)
    return parsed.scheme in ("http", "https") and bool(parsed.netloc)


def generate_code(length=6):
    return "".join(secrets.choice(ALPHABET) for _ in range(length))


def parse_expiry(value):
    """Return (expires_at_text, error_message)."""
    if value in (None, "", "0", 0):
        return None, None
    try:
        days = int(value)
    except (TypeError, ValueError):
        return None, "Expiry must be a whole number of days."
    if not 1 <= days <= 365:
        return None, "Expiry must be between 1 and 365 days."
    return to_text(utc_now() + timedelta(days=days)), None


# ---------- Routes ----------
@app.route("/")
def home():
    return render_template("index.html")


@app.route("/api/shorten", methods=["POST"])
def shorten():
    data = request.get_json(silent=True) or {}
    original_url = (data.get("url") or "").strip()
    custom_code = (data.get("custom_code") or "").strip()

    if not is_valid_url(original_url):
        return jsonify({"error": "Enter a valid URL starting with http:// or https://"}), 400

    expires_at, expiry_error = parse_expiry(data.get("expires_in_days"))
    if expiry_error:
        return jsonify({"error": expiry_error}), 400

    db = get_db()

    if custom_code:
        if not CUSTOM_CODE_PATTERN.fullmatch(custom_code):
            return jsonify({"error": "Custom name must be 3-30 characters: letters, numbers, - or _"}), 400
        if custom_code.lower() in RESERVED_CODES:
            return jsonify({"error": "That name is reserved. Please choose another."}), 400
        if not insert_url(db, custom_code, original_url, expires_at):
            return jsonify({"error": "That custom name is already taken."}), 409
        code = custom_code
    else:
        code = None
        for _ in range(5):
            candidate = generate_code()
            if insert_url(db, candidate, original_url, expires_at):
                code = candidate
                break
        if code is None:
            return jsonify({"error": "Could not generate a unique code. Try again."}), 500

    return jsonify({
        "short_code": code,
        "short_url": request.host_url + code,
        "original_url": original_url,
        "expires_at": expires_at,
    }), 201


@app.route("/<short_code>")
def redirect_to_original(short_code):
    db = get_db()
    row = db.execute(
        "SELECT original_url, expires_at FROM urls WHERE short_code = ?",
        (short_code,),
    ).fetchone()

    if row is None:
        return jsonify({"error": "Short URL not found"}), 404

    if is_expired(row["expires_at"]):
        return jsonify({"error": "This short URL has expired"}), 410

    db.execute(
        "UPDATE urls SET clicks = clicks + 1, last_visited = ? WHERE short_code = ?",
        (to_text(utc_now()), short_code),
    )
    db.commit()
    return redirect(row["original_url"])


@app.route("/api/stats/<short_code>")
def stats(short_code):
    db = get_db()
    row = db.execute(
        """SELECT short_code, original_url, clicks, created_at,
                  last_visited, expires_at
           FROM urls WHERE short_code = ?""",
        (short_code,),
    ).fetchone()

    if row is None:
        return jsonify({"error": "Short URL not found"}), 404

    result = dict(row)
    result["expired"] = is_expired(row["expires_at"])
    return jsonify(result)


@app.route("/api/links")
def recent_links():
    db = get_db()
    rows = db.execute(
        """SELECT short_code, original_url, clicks, created_at, expires_at
           FROM urls ORDER BY id DESC LIMIT 10"""
    ).fetchall()

    links = []
    for row in rows:
        item = dict(row)
        item["short_url"] = request.host_url + row["short_code"]
        item["expired"] = is_expired(row["expires_at"])
        links.append(item)
    return jsonify(links)


@app.route("/api/qr/<short_code>")
def qr_code(short_code):
    db = get_db()
    row = db.execute(
        "SELECT 1 FROM urls WHERE short_code = ?", (short_code,)
    ).fetchone()
    if row is None:
        return jsonify({"error": "Short URL not found"}), 404

    image = qrcode.make(request.host_url + short_code)
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    buffer.seek(0)
    return send_file(buffer, mimetype="image/png")

@app.route("/health")
def health():
    return jsonify({"status": "ok"})

init_db()

if __name__ == "__main__":
    app.run(debug=True)