from flask import Flask, render_template, request, jsonify, session
import sqlite3, hashlib, re
from datetime import datetime

app = Flask(__name__)
import os
app.secret_key = os.environ.get("SECRET_KEY", "redsorm-secret-key-2024-xK9mP")
DB = "redsorm.db"

COUPONS = [
    ("EARLYBIRD90", 90), ("SUPER80", 80), ("LAUNCH70", 70), ("PRIME60", 60),
    ("VIP50", 50), ("SAVE29", 29), ("HEALTH28", 28), ("FEAST27", 27),
    ("BOOST26", 26), ("SPRING25", 25), ("FAST24", 24), ("GROW23", 23),
    ("TASTY22", 22), ("START21", 21), ("BONUS20", 20), ("FLAVOR19", 19),
    ("HAPPY18", 18), ("RUCHI17", 17), ("SPICE16", 16), ("SMILE15", 15),
    ("FRIEND14", 14), ("SMART13", 13), ("SUNNY12", 12), ("JOY11", 11),
    ("WELCOME10", 10),
]

ADMIN_CONTACTS = {"adminredsorm251392@redsorm.in", "9999999999"}  # admin email + phone


def get_db():
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    with get_db() as db:
        db.execute("""
            CREATE TABLE IF NOT EXISTS coupons (
                id INTEGER PRIMARY KEY,
                code TEXT UNIQUE NOT NULL,
                discount INTEGER NOT NULL,
                claimed INTEGER DEFAULT 0,
                claimed_by TEXT,
                claimed_at TEXT
            )
        """)
        db.execute("""
            CREATE TABLE IF NOT EXISTS whitelist (
                id INTEGER PRIMARY KEY,
                contact TEXT UNIQUE NOT NULL,
                label TEXT,
                added_at TEXT
            )
        """)
        for i, (code, disc) in enumerate(COUPONS):
            db.execute(
                "INSERT OR IGNORE INTO coupons (id, code, discount) VALUES (?, ?, ?)",
                (i + 1, code, disc)
            )
        db.commit()


def normalize(contact: str) -> str:
    return contact.strip().lower()


# ── Auth ───────────────────────────────────────────────────────────────────────

@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/login", methods=["POST"])
def login():
    data = request.get_json()
    contact = normalize(data.get("contact", ""))
    if not contact:
        return jsonify({"error": "Please enter your email or phone number."}), 400

    # Check admin
    if contact in {c.lower() for c in ADMIN_CONTACTS}:
        session["role"] = "admin"
        session["contact"] = contact
        return jsonify({"role": "admin"})

    # Check whitelist
    with get_db() as db:
        row = db.execute(
            "SELECT * FROM whitelist WHERE LOWER(contact)=?", (contact,)
        ).fetchone()

    if row:
        # Check if already claimed
        claimed = db.execute(
            "SELECT id, code, discount FROM coupons WHERE LOWER(claimed_by)=? AND claimed=1",
            (contact,)
        ).fetchone()
        session["role"] = "user"
        session["contact"] = contact
        already = None
        if claimed:
            already = {"id": claimed["id"], "code": claimed["code"], "discount": claimed["discount"]}
        return jsonify({"role": "user", "already_claimed": already})

    return jsonify({"error": "Access denied. Your email or phone is not whitelisted. Contact RedSorm to get access."}), 403


@app.route("/api/logout", methods=["POST"])
def logout():
    session.clear()
    return jsonify({"ok": True})


# ── Cards ──────────────────────────────────────────────────────────────────────

@app.route("/api/cards")
def api_cards():
    if not session.get("role"):
        return jsonify({"error": "Unauthorized"}), 401
    with get_db() as db:
        rows = db.execute("SELECT id, discount, claimed, claimed_by FROM coupons ORDER BY id").fetchall()

    contact = session.get("contact", "")
    is_admin = session.get("role") == "admin"
    cards = []
    for r in rows:
        is_mine = r["claimed"] and r["claimed_by"] and normalize(r["claimed_by"]) == normalize(contact)
        cards.append({
            "id": r["id"],
            # Only reveal discount to admin or card owner; users see null until they claim
            "discount": r["discount"] if (is_admin or is_mine) else None,
            "claimed": bool(r["claimed"]),
            "mine": is_mine,
        })

    # Shuffle so order doesn't reveal discount ranking — use stable seed per session
    import random, hashlib as _h
    seed = int(_h.md5(session.get("contact", "x").encode()).hexdigest(), 16) % (2**32)
    rng = random.Random(seed)
    rng.shuffle(cards)
    return jsonify(cards)


@app.route("/api/claim/<int:card_id>", methods=["POST"])
def claim(card_id):
    if session.get("role") != "user":
        return jsonify({"error": "Unauthorized"}), 401

    contact = session["contact"]
    with get_db() as db:
        # Already claimed by this user?
        already = db.execute(
            "SELECT id, code, discount FROM coupons WHERE LOWER(claimed_by)=? AND claimed=1",
            (normalize(contact),)
        ).fetchone()
        if already:
            return jsonify({"error": "already_claimed", "id": already["id"],
                            "code": already["code"], "discount": already["discount"]}), 409

        row = db.execute(
            "SELECT id, code, discount, claimed FROM coupons WHERE id=?", (card_id,)
        ).fetchone()
        if not row:
            return jsonify({"error": "Invalid card."}), 404
        if row["claimed"]:
            return jsonify({"error": "This coupon was just claimed by someone else. Pick another!"}), 409

        db.execute(
            "UPDATE coupons SET claimed=1, claimed_by=?, claimed_at=? WHERE id=?",
            (contact, datetime.utcnow().isoformat(), card_id)
        )
        db.commit()
        return jsonify({"code": row["code"], "discount": row["discount"], "id": card_id})


# ── Admin whitelist API ────────────────────────────────────────────────────────

@app.route("/api/admin/whitelist", methods=["GET"])
def get_whitelist():
    if session.get("role") != "admin":
        return jsonify({"error": "Unauthorized"}), 401
    with get_db() as db:
        rows = db.execute("SELECT * FROM whitelist ORDER BY added_at DESC").fetchall()
    return jsonify([{"id": r["id"], "contact": r["contact"], "label": r["label"], "added_at": r["added_at"]} for r in rows])


@app.route("/api/admin/whitelist/add", methods=["POST"])
def whitelist_add():
    if session.get("role") != "admin":
        return jsonify({"error": "Unauthorized"}), 401
    data = request.get_json()
    contact = data.get("contact", "").strip()
    label = data.get("label", "").strip()
    if not contact:
        return jsonify({"error": "Contact required"}), 400
    with get_db() as db:
        try:
            db.execute(
                "INSERT INTO whitelist (contact, label, added_at) VALUES (?, ?, ?)",
                (contact, label, datetime.utcnow().isoformat())
            )
            db.commit()
        except sqlite3.IntegrityError:
            return jsonify({"error": "Already whitelisted"}), 409
    return jsonify({"ok": True})


@app.route("/api/admin/whitelist/remove/<int:wid>", methods=["DELETE"])
def whitelist_remove(wid):
    if session.get("role") != "admin":
        return jsonify({"error": "Unauthorized"}), 401
    with get_db() as db:
        db.execute("DELETE FROM whitelist WHERE id=?", (wid,))
        db.commit()
    return jsonify({"ok": True})


@app.route("/api/admin/coupons")
def admin_coupons():
    if session.get("role") != "admin":
        return jsonify({"error": "Unauthorized"}), 401
    with get_db() as db:
        rows = db.execute("SELECT * FROM coupons ORDER BY id").fetchall()
    return jsonify([dict(r) for r in rows])


# Run init on every startup (gunicorn and direct)
init_db()

if __name__ == "__main__":
    app.run(debug=True, port=5000)
