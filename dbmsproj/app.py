import json
import math
import os
from datetime import datetime, date

import mysql.connector
from flask import Flask, jsonify, request, send_from_directory, session
from flask_cors import CORS

# ── Config ─────────────────────────────────────────────────────
DB_CONFIG = {
    "host":     os.getenv("DB_HOST",     "localhost"),
    "port":     int(os.getenv("DB_PORT", 3306)),
    "user":     os.getenv("DB_USER",     "root"),
    "password": os.getenv("DB_PASSWORD", ""),
    "database": os.getenv("DB_NAME",     "earthquake_db"),
}
STATIC_DIR = os.path.dirname(os.path.abspath(__file__))

app = Flask(__name__, static_folder=STATIC_DIR)
app.secret_key = os.getenv("SECRET_KEY", "phivolcs-secret-key-2024")
CORS(app, supports_credentials=True)


def get_conn():
    return mysql.connector.connect(**DB_CONFIG)


def rows_to_dicts(cursor):
    cols = [d[0] for d in cursor.description]
    return [dict(zip(cols, row)) for row in cursor.fetchall()]


def serialize(obj):
    if isinstance(obj, (datetime, date)):
        return obj.isoformat()
    raise TypeError(f"Type {type(obj)} not serializable")


def json_response(data, status=200):
    return app.response_class(
        response=json.dumps(data, default=serialize),
        status=status,
        mimetype="application/json",
    )


def write_audit(cursor, table, record_id, action, old_vals=None, new_vals=None):
    changed_by = session.get("username", "system")
    cursor.execute(
        """INSERT INTO audit_log (table_name, record_id, action, changed_by, old_values, new_values)
           VALUES (%s, %s, %s, %s, %s, %s)""",
        (
            table,
            record_id,
            action,
            changed_by,
            json.dumps(old_vals, default=serialize) if old_vals else None,
            json.dumps(new_vals, default=serialize) if new_vals else None,
        ),
    )


def require_login(f):
    """Decorator: request must have an active session."""
    from functools import wraps
    @wraps(f)
    def decorated(*args, **kwargs):
        if "user_id" not in session:
            return json_response({"error": "Login required"}, 401)
        return f(*args, **kwargs)
    return decorated


def require_admin(f):
    """Decorator: request must be authenticated as admin."""
    from functools import wraps
    @wraps(f)
    def decorated(*args, **kwargs):
        if "user_id" not in session:
            return json_response({"error": "Login required"}, 401)
        if session.get("role") != "admin":
            return json_response({"error": "Admin access required"}, 403)
        return f(*args, **kwargs)
    return decorated


def risk_level(magnitude):
    if magnitude is None:
        return "Unknown"
    if magnitude < 4.0:
        return "Low"
    if magnitude < 5.0:
        return "Moderate"
    if magnitude < 7.0:
        return "High"
    return "Very High"


def _pt_seg_dist(px, py, ax, ay, bx, by):
    dx, dy = bx - ax, by - ay
    if dx == 0 and dy == 0:
        return math.hypot(px - ax, py - ay)
    t = max(0, min(1, ((px - ax) * dx + (py - ay) * dy) / (dx * dx + dy * dy)))
    return math.hypot(px - (ax + t * dx), py - (ay + t * dy))


def _min_dist_to_geom(lat, lng, geom_json_str):
    geom = json.loads(geom_json_str)
    if geom["type"] == "LineString":
        coords = geom["coordinates"]
    else:
        coords = [c for part in geom["coordinates"] for c in part]
    best = math.inf
    for i in range(len(coords) - 1):
        lon1, la1 = coords[i]
        lon2, la2 = coords[i + 1]
        d = _pt_seg_dist(lat, lng, la1, lon1, la2, lon2)
        if d < best:
            best = d
    return best


def find_nearest_fault_id(cursor, lat, lng, threshold_deg=2.0):
    cursor.execute("SELECT id, geom_json FROM fault_lines")
    best_id, best_dist = None, math.inf
    for row in cursor.fetchall():
        d = _min_dist_to_geom(lat, lng, row[1])
        if d < best_dist:
            best_dist = d
            best_id = row[0]
    return best_id if best_dist <= threshold_deg else None


# ── Auth routes ─────────────────────────────────────────────────

@app.route("/api/login", methods=["POST"])
def login():
    data = request.get_json(force=True)
    username = data.get("username", "").strip()
    password = data.get("password", "")

    if not username or not password:
        return json_response({"error": "Username and password are required"}, 400)

    conn = get_conn()
    cur  = conn.cursor()
    try:
        cur.execute(
            "SELECT id, username, role FROM users WHERE username=%s AND password=%s",
            (username, password),
        )
        row = cur.fetchone()
    finally:
        cur.close()
        conn.close()

    if not row:
        return json_response({"error": "Invalid username or password"}, 401)

    session["user_id"]  = row[0]
    session["username"] = row[1]
    session["role"]     = row[2]

    return json_response({"message": "Login successful", "username": row[1], "role": row[2]})


@app.route("/api/logout", methods=["POST"])
def logout():
    session.clear()
    return json_response({"message": "Logged out"})


@app.route("/api/me", methods=["GET"])
def me():
    if "user_id" not in session:
        return json_response({"logged_in": False}, 200)
    return json_response({
        "logged_in": True,
        "username":  session.get("username"),
        "role":      session.get("role"),
    })


# ── Static files ────────────────────────────────────────────────

@app.route("/")
def index():
    return send_from_directory(STATIC_DIR, "index.html")


@app.route("/<path:filename>")
def static_files(filename):
    return send_from_directory(STATIC_DIR, filename)


# ── Earthquake routes ────────────────────────────────────────────

@app.route("/api/earthquakes", methods=["GET"])
@require_login
def list_earthquakes():
    p = request.args

    conditions = []
    params     = []

    if p.get("lat") and p.get("lng"):
        try:
            lat = float(p["lat"])
            lng = float(p["lng"])
            r   = float(p.get("radius_deg", 0.5))
            conditions.append(
                "(ABS(e.latitude - %s) <= %s AND ABS(e.longitude - %s) <= %s)"
            )
            params += [lat, r, lng, r]
        except ValueError:
            return json_response({"error": "Invalid lat/lng/radius"}, 400)

    if p.get("min_mag"):
        conditions.append("e.magnitude >= %s")
        params.append(float(p["min_mag"]))
    if p.get("max_mag"):
        conditions.append("e.magnitude <= %s")
        params.append(float(p["max_mag"]))
    if p.get("risk"):
        conditions.append("e.risk_level = %s")
        params.append(p["risk"])
    if p.get("location"):
        conditions.append("(e.general_location LIKE %s OR e.specific_location LIKE %s)")
        like = f"%{p['location']}%"
        params += [like, like]
    if p.get("date_from"):
        conditions.append("e.date_time_ph >= %s")
        params.append(p["date_from"])
    if p.get("date_to"):
        conditions.append("e.date_time_ph <= %s")
        params.append(p["date_to"] + " 23:59:59")

    where = ("WHERE " + " AND ".join(conditions)) if conditions else ""

    sort_map = {
        "date_desc": "e.date_time_ph DESC",
        "date_asc":  "e.date_time_ph ASC",
        "mag_desc":  "e.magnitude DESC",
        "mag_asc":   "e.magnitude ASC",
    }
    order = sort_map.get(p.get("sort", "date_desc"), "e.date_time_ph DESC")

    try:
        limit = max(1, min(int(p.get("limit", 50)), 500))
        page  = max(1, int(p.get("page", 1)))
    except ValueError:
        return json_response({"error": "Invalid pagination params"}, 400)

    offset = (page - 1) * limit

    sql = f"""
        SELECT e.id, e.date_time_ph, e.latitude, e.longitude,
               e.depth_km, e.magnitude, e.risk_level,
               e.location, e.specific_location, e.general_location,
               f.name AS fault_name, f.slip_type AS fault_slip_type
        FROM earthquakes e
        LEFT JOIN fault_lines f ON e.nearest_fault_id = f.id
        {where}
        ORDER BY {order}
        LIMIT %s OFFSET %s
    """
    count_sql = f"SELECT COUNT(*) FROM earthquakes e {where}"

    conn = get_conn()
    cur  = conn.cursor()
    try:
        cur.execute(count_sql, params)
        total = cur.fetchone()[0]

        cur.execute(sql, params + [limit, offset])
        rows = rows_to_dicts(cur)
    finally:
        cur.close()
        conn.close()

    return json_response({
        "total":   total,
        "page":    page,
        "limit":   limit,
        "pages":   math.ceil(total / limit),
        "results": rows,
    })


@app.route("/api/earthquakes/<int:eid>", methods=["GET"])
@require_login
def get_earthquake(eid):
    conn = get_conn()
    cur  = conn.cursor()
    try:
        cur.execute("""
            SELECT e.*, f.name AS fault_name, f.slip_type
            FROM earthquakes e
            LEFT JOIN fault_lines f ON e.nearest_fault_id = f.id
            WHERE e.id = %s
        """, (eid,))
        rows = rows_to_dicts(cur)
    finally:
        cur.close()
        conn.close()

    if not rows:
        return json_response({"error": "Not found"}, 404)
    return json_response(rows[0])


@app.route("/api/earthquakes", methods=["POST"])
@require_admin
def create_earthquake():
    data = request.get_json(force=True)
    required = ["date_time_ph", "latitude", "longitude", "magnitude"]
    missing  = [f for f in required if f not in data]
    if missing:
        return json_response({"error": f"Missing fields: {missing}"}, 400)

    conn = get_conn()
    cur  = conn.cursor()
    try:
        lat = float(data["latitude"])
        lng = float(data["longitude"])
        fid = data.get("nearest_fault_id") or find_nearest_fault_id(cur, lat, lng)

        cur.execute("""
            INSERT INTO earthquakes
                (date_time_ph, latitude, longitude, depth_km, magnitude,
                 location, specific_location, general_location, nearest_fault_id)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)
        """, (
            data["date_time_ph"],
            lat,
            lng,
            data.get("depth_km"),
            float(data["magnitude"]),
            data.get("location"),
            data.get("specific_location"),
            data.get("general_location"),
            fid,
        ))
        new_id = cur.lastrowid
        write_audit(cur, "earthquakes", new_id, "INSERT", new_vals=data)
        conn.commit()
    except Exception as e:
        conn.rollback()
        cur.close(); conn.close()
        return json_response({"error": str(e)}, 500)
    finally:
        cur.close()
        conn.close()

    return json_response({"id": new_id, "message": "Earthquake record created."}, 201)


@app.route("/api/earthquakes/<int:eid>", methods=["PUT"])
@require_admin
def update_earthquake(eid):
    data = request.get_json(force=True)

    conn = get_conn()
    cur  = conn.cursor()
    try:
        cur.execute("SELECT * FROM earthquakes WHERE id=%s", (eid,))
        old = rows_to_dicts(cur)
        if not old:
            return json_response({"error": "Not found"}, 404)
        old_vals = old[0]

        allowed = [
            "date_time_ph","latitude","longitude","depth_km","magnitude",
            "location","specific_location","general_location","nearest_fault_id"
        ]
        updates = {k: v for k, v in data.items() if k in allowed}
        if not updates:
            return json_response({"error": "No valid fields to update"}, 400)

        if "latitude" in updates or "longitude" in updates:
            lat = float(updates.get("latitude",  old_vals["latitude"]))
            lng = float(updates.get("longitude", old_vals["longitude"]))
            if "nearest_fault_id" not in updates:
                updates["nearest_fault_id"] = find_nearest_fault_id(cur, lat, lng)

        set_clause = ", ".join(f"{k}=%s" for k in updates)
        values     = list(updates.values()) + [eid]
        cur.execute(f"UPDATE earthquakes SET {set_clause} WHERE id=%s", values)
        write_audit(cur, "earthquakes", eid, "UPDATE", old_vals=old_vals, new_vals=updates)
        conn.commit()
    except Exception as e:
        conn.rollback()
        return json_response({"error": str(e)}, 500)
    finally:
        cur.close()
        conn.close()

    return json_response({"message": "Updated successfully."})


@app.route("/api/earthquakes/<int:eid>", methods=["DELETE"])
@require_admin
def delete_earthquake(eid):
    conn = get_conn()
    cur  = conn.cursor()
    try:
        cur.execute("SELECT * FROM earthquakes WHERE id=%s", (eid,))
        old = rows_to_dicts(cur)
        if not old:
            return json_response({"error": "Not found"}, 404)

        cur.execute("DELETE FROM earthquakes WHERE id=%s", (eid,))
        write_audit(cur, "earthquakes", eid, "DELETE", old_vals=old[0])
        conn.commit()
    except Exception as e:
        conn.rollback()
        return json_response({"error": str(e)}, 500)
    finally:
        cur.close()
        conn.close()

    return json_response({"message": "Deleted successfully."})


# ── Fault routes ─────────────────────────────────────────────────

@app.route("/api/faults", methods=["GET"])
@require_login
def list_faults():
    conn = get_conn()
    cur  = conn.cursor()
    try:
        cur.execute("""
            SELECT id, name, slip_type, activity_confidence,
                   bbox_min_lat, bbox_max_lat, bbox_min_lng, bbox_max_lng
            FROM fault_lines ORDER BY name
        """)
        rows = rows_to_dicts(cur)
    finally:
        cur.close()
        conn.close()
    return json_response(rows)


@app.route("/api/faults/<int:fid>", methods=["GET"])
@require_login
def get_fault(fid):
    conn = get_conn()
    cur  = conn.cursor()
    try:
        cur.execute("SELECT * FROM fault_lines WHERE id=%s", (fid,))
        rows = rows_to_dicts(cur)
    finally:
        cur.close()
        conn.close()
    if not rows:
        return json_response({"error": "Not found"}, 404)
    return json_response(rows[0])


@app.route("/api/faults", methods=["POST"])
@require_admin
def create_fault():
    data = request.get_json(force=True)
    if not data.get("name"):
        return json_response({"error": "name is required"}, 400)

    conn = get_conn()
    cur  = conn.cursor()
    try:
        cur.execute("""
            INSERT INTO fault_lines
                (name, slip_type, strike_slip_rate, net_slip_rate,
                 activity_confidence, epistemic_quality, notes, reference)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s)
        """, (
            data["name"],
            data.get("slip_type"),
            data.get("strike_slip_rate"),
            data.get("net_slip_rate"),
            data.get("activity_confidence"),
            data.get("epistemic_quality"),
            data.get("notes"),
            data.get("reference"),
        ))
        new_id = cur.lastrowid
        write_audit(cur, "fault_lines", new_id, "INSERT", new_vals=data)
        conn.commit()
    except Exception as e:
        conn.rollback()
        return json_response({"error": str(e)}, 500)
    finally:
        cur.close()
        conn.close()
    return json_response({"id": new_id, "message": "Fault line created."}, 201)


@app.route("/api/faults/<int:fid>", methods=["PUT"])
@require_admin
def update_fault(fid):
    data = request.get_json(force=True)
    conn = get_conn()
    cur  = conn.cursor()
    try:
        cur.execute("SELECT * FROM fault_lines WHERE id=%s", (fid,))
        old = rows_to_dicts(cur)
        if not old:
            return json_response({"error": "Not found"}, 404)

        allowed = ["name","slip_type","strike_slip_rate","net_slip_rate",
                   "activity_confidence","epistemic_quality","notes","reference"]
        updates = {k: v for k, v in data.items() if k in allowed}
        if not updates:
            return json_response({"error": "No valid fields to update"}, 400)

        set_clause = ", ".join(f"{k}=%s" for k in updates)
        values     = list(updates.values()) + [fid]
        cur.execute(f"UPDATE fault_lines SET {set_clause} WHERE id=%s", values)
        write_audit(cur, "fault_lines", fid, "UPDATE", old_vals=old[0], new_vals=updates)
        conn.commit()
    except Exception as e:
        conn.rollback()
        return json_response({"error": str(e)}, 500)
    finally:
        cur.close()
        conn.close()
    return json_response({"message": "Fault updated."})


@app.route("/api/faults/<int:fid>", methods=["DELETE"])
@require_admin
def delete_fault(fid):
    conn = get_conn()
    cur  = conn.cursor()
    try:
        cur.execute("SELECT * FROM fault_lines WHERE id=%s", (fid,))
        old = rows_to_dicts(cur)
        if not old:
            return json_response({"error": "Not found"}, 404)
        cur.execute("DELETE FROM fault_lines WHERE id=%s", (fid,))
        write_audit(cur, "fault_lines", fid, "DELETE", old_vals=old[0])
        conn.commit()
    except Exception as e:
        conn.rollback()
        return json_response({"error": str(e)}, 500)
    finally:
        cur.close()
        conn.close()
    return json_response({"message": "Fault deleted."})


# ── Utility routes ────────────────────────────────────────────────

@app.route("/api/nearby", methods=["GET"])
@require_login
def nearby():
    try:
        lat = float(request.args["lat"])
        lng = float(request.args["lng"])
        r   = float(request.args.get("radius_deg", 0.5))
        lim = min(int(request.args.get("limit", 20)), 200)
    except (KeyError, ValueError):
        return json_response({"error": "lat and lng are required numbers"}, 400)

    conn = get_conn()
    cur  = conn.cursor()
    try:
        cur.execute("""
            SELECT e.id, e.date_time_ph, e.latitude, e.longitude,
                   e.depth_km, e.magnitude, e.risk_level,
                   e.location, e.specific_location, e.general_location,
                   f.name AS fault_name,
                   SQRT(POW(e.latitude - %s, 2) + POW(e.longitude - %s, 2)) AS dist_deg
            FROM earthquakes e
            LEFT JOIN fault_lines f ON e.nearest_fault_id = f.id
            WHERE ABS(e.latitude - %s) <= %s
              AND ABS(e.longitude - %s) <= %s
            ORDER BY dist_deg ASC
            LIMIT %s
        """, (lat, lng, lat, r, lng, r, lim))
        rows = rows_to_dicts(cur)
    finally:
        cur.close()
        conn.close()

    for row in rows:
        row["risk_description"] = {
            "Low":       "Minor shaking; little to no damage expected.",
            "Moderate":  "Light to moderate shaking; minor damage possible.",
            "High":      "Strong shaking; significant damage likely.",
            "Very High": "Severe shaking; major to catastrophic damage expected.",
        }.get(row.get("risk_level"), "Unknown")

    return json_response({"lat": lat, "lng": lng, "radius_deg": r, "results": rows})


@app.route("/api/stats", methods=["GET"])
@require_login
def stats():
    conn = get_conn()
    cur  = conn.cursor()
    try:
        cur.execute("SELECT COUNT(*) FROM earthquakes")
        total_eq = cur.fetchone()[0]

        cur.execute("SELECT COUNT(*) FROM fault_lines")
        total_faults = cur.fetchone()[0]

        cur.execute("""
            SELECT risk_level, COUNT(*) AS cnt
            FROM earthquakes GROUP BY risk_level
        """)
        risk_dist = {r[0]: r[1] for r in cur.fetchall()}

        cur.execute("""
            SELECT general_location, COUNT(*) AS cnt
            FROM earthquakes
            WHERE general_location IS NOT NULL
            GROUP BY general_location
            ORDER BY cnt DESC LIMIT 10
        """)
        top_locations = rows_to_dicts(cur)

        cur.execute("""
            SELECT YEAR(date_time_ph) AS yr, COUNT(*) AS cnt
            FROM earthquakes
            GROUP BY yr ORDER BY yr
        """)
        by_year = rows_to_dicts(cur)

        cur.execute("""
            SELECT e.magnitude, e.date_time_ph, e.location
            FROM earthquakes e
            ORDER BY e.magnitude DESC LIMIT 5
        """)
        strongest = rows_to_dicts(cur)

    finally:
        cur.close()
        conn.close()

    return json_response({
        "total_earthquakes": total_eq,
        "total_fault_lines": total_faults,
        "risk_distribution": risk_dist,
        "top_locations":     top_locations,
        "earthquakes_by_year": by_year,
        "strongest_earthquakes": strongest,
    })


@app.route("/api/audit", methods=["GET"])
@require_admin
def audit_log():
    lim = min(int(request.args.get("limit", 100)), 500)
    conn = get_conn()
    cur  = conn.cursor()
    try:
        cur.execute(
            "SELECT * FROM audit_log ORDER BY changed_at DESC LIMIT %s", (lim,)
        )
        rows = rows_to_dicts(cur)
    finally:
        cur.close()
        conn.close()
    return json_response(rows)


@app.route("/api/faults/geojson", methods=["GET"])
@require_login
def faults_geojson():
    conn = get_conn()
    cur  = conn.cursor()
    try:
        cur.execute("SELECT id, name, slip_type, activity_confidence, geom_json FROM fault_lines")
        rows = cur.fetchall()
    finally:
        cur.close()
        conn.close()

    features = []
    for row in rows:
        geom = json.loads(row[4]) if row[4] else None
        features.append({
            "type": "Feature",
            "properties": {
                "id":   row[0],
                "name": row[1],
                "slip_type": row[2],
                "activity_confidence": row[3],
            },
            "geometry": geom,
        })

    return app.response_class(
        response=json.dumps({"type": "FeatureCollection", "features": features}),
        status=200,
        mimetype="application/json",
    )


if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=5000)
