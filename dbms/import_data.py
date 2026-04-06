import json
import math
import os
import sys
from datetime import datetime

import mysql.connector
import pandas as pd
from tqdm import tqdm  


DB_CONFIG = {
    "host":     os.getenv("DB_HOST",     "localhost"),
    "port":     int(os.getenv("DB_PORT", 3306)),
    "user":     os.getenv("DB_USER",     "root"),
    "password": os.getenv("DB_PASSWORD", ""),
    "database": os.getenv("DB_NAME",     "earthquake_db"),
}

GEOJSON_PATH = "philippines_faults.geojson"
CSV_PATH     = "phivolcs_earthquake_data.csv"

BATCH_SIZE = 500  


def haversine_deg(lat1, lon1, lat2, lon2):
    return math.hypot(lat2 - lat1, lon2 - lon1)


def point_to_segment_dist(px, py, ax, ay, bx, by):
    dx, dy = bx - ax, by - ay
    if dx == 0 and dy == 0:
        return math.hypot(px - ax, py - ay)
    t = max(0, min(1, ((px - ax) * dx + (py - ay) * dy) / (dx * dx + dy * dy)))
    return math.hypot(px - (ax + t * dx), py - (ay + t * dy))


def min_dist_to_linestring(lat, lng, coords):
    best = math.inf
    for i in range(len(coords) - 1):
        lon1, la1 = coords[i]
        lon2, la2 = coords[i + 1]
        d = point_to_segment_dist(lat, lng, la1, lon1, la2, lon2)
        if d < best:
            best = d
    return best


def bbox(coords):
    lats = [c[1] for c in coords]
    lngs = [c[0] for c in coords]
    return min(lats), max(lats), min(lngs), max(lngs)

def load_faults(cursor):
    print("\n📂 Loading fault lines from GeoJSON …")
    with open(GEOJSON_PATH, encoding="utf-8") as f:
        gj = json.load(f)

    fault_rows = []
    for feat in gj["features"]:
        props = feat.get("properties", {})
        geom  = feat["geometry"]

        if geom["type"] == "LineString":
            all_coords = [geom["coordinates"]]
        elif geom["type"] == "MultiLineString":
            all_coords = geom["coordinates"]
        else:
            continue

        flat_coords = [c for part in all_coords for c in part]
        if not flat_coords:
            continue

        mn_lat, mx_lat, mn_lng, mx_lng = bbox(flat_coords)

        fault_rows.append((
            props.get("name") or "Unknown",
            props.get("slip_type"),
            props.get("strike_slip_rate"),
            props.get("net_slip_rate"),
            props.get("activity_confidence"),
            props.get("epistemic_quality"),
            props.get("average_dip"),
            props.get("dip_dir"),
            props.get("upper_seis_depth"),
            props.get("lower_seis_depth"),
            props.get("average_rake"),
            props.get("notes"),
            props.get("reference"),
            json.dumps(geom),
            mn_lat, mx_lat, mn_lng, mx_lng,
        ))

    sql = """
        INSERT INTO fault_lines
            (name, slip_type, strike_slip_rate, net_slip_rate,
             activity_confidence, epistemic_quality, average_dip,
             dip_dir, upper_seis_depth, lower_seis_depth, average_rake,
             notes, reference, geom_json,
             bbox_min_lat, bbox_max_lat, bbox_min_lng, bbox_max_lng)
        VALUES
            (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
    """
    cursor.executemany(sql, fault_rows)
    print(f"   ✅  {len(fault_rows)} fault lines inserted.")

    cursor.execute("SELECT id, geom_json, name FROM fault_lines")
    faults = []
    for row in cursor.fetchall():
        geom = json.loads(row[1])
        if geom["type"] == "LineString":
            coords = geom["coordinates"]
        else:
            coords = [c for part in geom["coordinates"] for c in part]
        faults.append({"id": row[0], "name": row[2], "coords": coords})
    return faults

def nearest_fault_id(lat, lng, faults, threshold_deg=2.0):
    """Return the id of the nearest fault within `threshold_deg`
    degrees, or None if nothing is close enough."""
    best_id   = None
    best_dist = math.inf
    for fault in faults:
        d = min_dist_to_linestring(lat, lng, fault["coords"])
        if d < best_dist:
            best_dist = d
            best_id   = fault["id"]
    return best_id if best_dist <= threshold_deg else None

def load_earthquakes(cursor, faults):
    print("\n📂 Loading earthquake data from CSV …")
    df = pd.read_csv(CSV_PATH)
    df.columns = [c.strip() for c in df.columns]
    df = df.dropna(subset=["Latitude", "Longitude", "Magnitude"])

    df["Date_Time_PH"] = pd.to_datetime(df["Date_Time_PH"], errors="coerce")
    df = df.dropna(subset=["Date_Time_PH"])

    for col in ["Latitude", "Longitude", "Magnitude", "Depth_In_Km"]:
        df[col] = pd.to_numeric(df[col], errors="coerce")

    df = df.dropna(subset=["Latitude", "Longitude", "Magnitude"])

    total   = len(df)
    batches = []
    current = []

    print(f"   Resolving nearest faults for {total:,} rows …")
    for _, row in tqdm(df.iterrows(), total=total, unit="eq"):
        lat = float(row["Latitude"])
        lng = float(row["Longitude"])
        fid = nearest_fault_id(lat, lng, faults)

        depth = row["Depth_In_Km"]
        current.append((
            row["Date_Time_PH"].strftime("%Y-%m-%d %H:%M:%S"),
            lat,
            lng,
            float(depth) if pd.notna(depth) else None,
            float(row["Magnitude"]),
            str(row["Location"])[:512]           if pd.notna(row.get("Location"))           else None,
            str(row["Specific_Location"])[:255]  if pd.notna(row.get("Specific_Location"))  else None,
            str(row["General_Location"])[:255]   if pd.notna(row.get("General_Location"))   else None,
            fid,
        ))
        if len(current) >= BATCH_SIZE:
            batches.append(current)
            current = []

    if current:
        batches.append(current)

    sql = """
        INSERT INTO earthquakes
            (date_time_ph, latitude, longitude, depth_km, magnitude,
             location, specific_location, general_location, nearest_fault_id)
        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)
    """
    print("   Inserting into MySQL …")
    for batch in tqdm(batches, unit="batch"):
        cursor.executemany(sql, batch)

    print(f"   ✅  {total:,} earthquake records inserted.")

def main():
    print("🔌 Connecting to MySQL …")
    conn = mysql.connector.connect(**DB_CONFIG)
    conn.autocommit = False
    cursor = conn.cursor()

    try:
        print("🧹 Clearing existing data …")
        cursor.execute("SET FOREIGN_KEY_CHECKS=0")
        cursor.execute("TRUNCATE TABLE earthquakes")
        cursor.execute("TRUNCATE TABLE fault_lines")
        cursor.execute("TRUNCATE TABLE audit_log")
        cursor.execute("SET FOREIGN_KEY_CHECKS=1")
        conn.commit()

        faults = load_faults(cursor)
        conn.commit()

        load_earthquakes(cursor, faults)
        conn.commit()

        print("\n🎉 Import complete!")

        # Quick stats
        cursor.execute("SELECT COUNT(*) FROM fault_lines")
        print(f"   Fault lines : {cursor.fetchone()[0]:,}")
        cursor.execute("SELECT COUNT(*) FROM earthquakes")
        print(f"   Earthquakes : {cursor.fetchone()[0]:,}")

    except Exception as e:
        conn.rollback()
        print(f"\n❌ Error: {e}")
        sys.exit(1)
    finally:
        cursor.close()
        conn.close()


if __name__ == "__main__":
    main()
