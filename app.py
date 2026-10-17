import sqlite3
import secrets
import string
from urllib.parse import urlparse

from flask import Flask, request, jsonify, redirect, render_template, g

app = Flask(__name__)
DATABASE = "urls.db"
ALPHABET = string.ascii_letters + string.digits


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
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)


# ---------- Utility functions ----------
def is_valid_url(url):
    parsed = urlparse(url)
    return parsed.scheme in ("http", "https") and bool(parsed.netloc)


def generate_code(length=6):
    return "".join(secrets.choice(ALPHABET) for _ in range(length))


# ---------- Routes ----------
@app.route("/")
def home():
    return render_template("index.html")


@app.route("/api/shorten", methods=["POST"])
def shorten():
    data = request.get_json(silent=True) or {}
    original_url = (data.get("url") or "").strip()

    if not is_valid_url(original_url):
        return jsonify({"error": "Enter a valid URL starting with http:// or https://"}), 400

    db = get_db()
    for _ in range(5):
        code = generate_code()
        try:
            db.execute(
                "INSERT INTO urls (short_code, original_url) VALUES (?, ?)",
                (code, original_url),
            )
            db.commit()
            break
        except sqlite3.IntegrityError:
            continue
    else:
        return jsonify({"error": "Could not generate a unique code. Try again."}), 500

    return jsonify({
        "short_code": code,
        "short_url": request.host_url + code,
        "original_url": original_url,
    }), 201


@app.route("/<short_code>")
def redirect_to_original(short_code):
    db = get_db()
    row = db.execute(
        "SELECT original_url FROM urls WHERE short_code = ?", (short_code,)
    ).fetchone()

    if row is None:
        return jsonify({"error": "Short URL not found"}), 404

    db.execute("UPDATE urls SET clicks = clicks + 1 WHERE short_code = ?", (short_code,))
    db.commit()
    return redirect(row["original_url"])


@app.route("/api/stats/<short_code>")
def stats(short_code):
    db = get_db()
    row = db.execute(
        "SELECT short_code, original_url, clicks, created_at FROM urls WHERE short_code = ?",
        (short_code,),
    ).fetchone()

    if row is None:
        return jsonify({"error": "Short URL not found"}), 404
    return jsonify(dict(row))


init_db()

if __name__ == "__main__":
    app.run(debug=True)