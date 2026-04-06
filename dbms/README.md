# PHIVOLCS Earthquake Risk Mapping System
## Setup & Run Guide

---

## Prerequisites
- Python 3.9+
- MySQL 8.0+
- Node is NOT required (pure Python backend)

---

## 1 — MySQL Setup

Open MySQL and run the schema:

```bash
mysql -u root -p < schema.sql
```

Or paste the SQL file contents directly into MySQL Workbench.

---

## 2 — Python Dependencies

```bash
pip install -r requirements.txt
```

---

## 3 — Configure Database Credentials

The app reads these environment variables (all have defaults for local dev):

| Variable      | Default     | Description           |
|---------------|-------------|-----------------------|
| DB_HOST       | localhost   | MySQL host            |
| DB_PORT       | 3306        | MySQL port            |
| DB_USER       | root        | MySQL username        |
| DB_PASSWORD   |  (empty)    | MySQL password        |
| DB_NAME       | earthquake_db | Database name       |

**Linux / macOS:**
```bash
export DB_USER=root
export DB_PASSWORD=yourpassword
```

**Windows (Command Prompt):**
```cmd
set DB_USER=root
set DB_PASSWORD=yourpassword
```

Or just edit the `DB_CONFIG` dict at the top of `app.py` and `import_data.py` directly.

---

## 4 — Import Data (one-time)

Place the CSV and GeoJSON files in the same folder as `import_data.py`, then:

```bash
python import_data.py
```

This will:
1. Clear existing data (safe to re-run)
2. Insert all 166 fault lines from `philippines_faults.geojson`
3. Insert all ~125,000 earthquakes from `phivolcs_earthquake_data.csv`
4. Resolve the nearest fault for every earthquake (this takes a few minutes)

---

## 5 — Start the Backend

```bash
python app.py
```

The Flask server starts at **http://localhost:5000**

Open your browser and go to **http://localhost:5000** — the map loads automatically.

---

## API Reference

### Earthquakes
| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/earthquakes` | List/filter/paginate |
| GET | `/api/earthquakes/<id>` | Single record |
| POST | `/api/earthquakes` | Create new record |
| PUT | `/api/earthquakes/<id>` | Update record |
| DELETE | `/api/earthquakes/<id>` | Delete record |

### Fault Lines
| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/faults` | List all faults |
| GET | `/api/faults/<id>` | Single fault |
| GET | `/api/faults/geojson` | GeoJSON for Leaflet map |
| POST | `/api/faults` | Create fault |
| PUT | `/api/faults/<id>` | Update fault |
| DELETE | `/api/faults/<id>` | Delete fault |

### Utilities
| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/nearby?lat=&lng=&radius_deg=` | Earthquakes near a point |
| GET | `/api/stats` | Summary statistics |
| GET | `/api/audit` | Audit log (CRUD history) |

### Example Queries
```
# Earthquakes near Manila, radius 1°
GET /api/nearby?lat=14.5995&lng=120.9842&radius_deg=1

# All High-risk earthquakes in Batangas
GET /api/earthquakes?location=Batangas&risk=High&sort=mag_desc

# Earthquakes M6+ since 2020
GET /api/earthquakes?min_mag=6&date_from=2020-01-01&sort=mag_desc
```

---

## File Structure

```
earthquake_system/
├── schema.sql          ← Run this first in MySQL
├── import_data.py      ← One-time CSV/GeoJSON import
├── app.py              ← Flask backend (CRUD API)
├── index.html          ← Frontend map application
├── requirements.txt    ← Python packages
├── phivolcs_earthquake_data.csv
└── philippines_faults.geojson
```

---

## Database Tables

| Table | Description |
|-------|-------------|
| `fault_lines` | 166 Philippine fault lines with geometry |
| `earthquakes` | ~125K earthquake records (2016–present) |
| `audit_log` | Every Create/Update/Delete operation logged |
| `v_earthquake_details` | View joining earthquakes + fault names |

### Risk Level (auto-computed column)
| Magnitude | Risk Level |
|-----------|------------|
| < 4.0 | Low |
| 4.0 – 4.9 | Moderate |
| 5.0 – 6.9 | High |
| ≥ 7.0 | Very High |
