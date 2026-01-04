import os
import base64
import hashlib
import hmac
import secrets
from datetime import datetime, timedelta, time, date
from zoneinfo import ZoneInfo
from typing import List, Optional

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
import psycopg
from psycopg.rows import dict_row
import httpx
from apscheduler.schedulers.background import BackgroundScheduler

# --- Env helpers ---
def env(name: str, default: Optional[str] = None) -> str:
    val = os.getenv(name, default)
    if val is None or val == "":
        raise RuntimeError(f"Missing required env var: {name}")
    return val

DB_HOST = env("DB_HOST")
DB_PORT = env("DB_PORT", "5432")
DB_NAME = env("DB_NAME")
DB_USER = env("DB_USER")
DB_PASSWORD = env("DB_PASSWORD")
GEOCODE_CONTACT = os.getenv("GEOCODE_CONTACT", "you@example.com")
BREVO_API_KEY = os.getenv("BREVO_API_KEY")
BREVO_SENDER_EMAIL = os.getenv("BREVO_SENDER_EMAIL")
BREVO_SENDER_NAME = os.getenv("BREVO_SENDER_NAME", "CampusPulse")

DATABASE_URL = f"host={DB_HOST} port={DB_PORT} dbname={DB_NAME} user={DB_USER} password={DB_PASSWORD}"

app = FastAPI(title="CampusPulse")
_scheduler: Optional[BackgroundScheduler] = None

# Static JS
app.mount("/static", StaticFiles(directory="app/static"), name="static")

# External API
BVG_BASE_URL = "https://v6.bvg.transport.rest"
NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"
BREVO_EMAIL_URL = "https://api.brevo.com/v3/smtp/email"
TZ = ZoneInfo("Europe/Berlin")

# Template (tiny: we just return it raw)
INDEX_PATH = os.path.join("app", "templates", "index.html")
LOGIN_PATH = os.path.join("app", "templates", "login.html")
SIGNUP_PATH = os.path.join("app", "templates", "signup.html")


def get_conn():
    return psycopg.connect(DATABASE_URL, row_factory=dict_row)


def init_db():
    # Create table if not exists
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS users (
                    id SERIAL PRIMARY KEY,
                    email TEXT NOT NULL UNIQUE,
                    password_hash TEXT NOT NULL,
                    created_at TIMESTAMP NOT NULL DEFAULT NOW()
                );
                """
            )
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS classes (
                    id SERIAL PRIMARY KEY,
                    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                    course_name TEXT NOT NULL,
                    start_time TIMESTAMP NOT NULL,
                    end_time TIMESTAMP NOT NULL,
                    location TEXT NOT NULL
                );
                """
            )
            cur.execute(
                """
                ALTER TABLE classes
                ADD COLUMN IF NOT EXISTS user_id INTEGER;
                """
            )
            cur.execute(
                """
                ALTER TABLE classes
                ADD COLUMN IF NOT EXISTS end_time TIMESTAMP;
                """
            )
            cur.execute(
                """
                DO $$
                BEGIN
                    IF NOT EXISTS (
                        SELECT 1
                        FROM information_schema.table_constraints
                        WHERE constraint_name = 'classes_user_id_fkey'
                          AND table_name = 'classes'
                    ) THEN
                        ALTER TABLE classes
                        ADD CONSTRAINT classes_user_id_fkey
                        FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE;
                    END IF;
                END
                $$;
                """
            )
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS sessions (
                    id SERIAL PRIMARY KEY,
                    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                    token TEXT NOT NULL UNIQUE,
                    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
                    expires_at TIMESTAMP NOT NULL
                );
                """
            )
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS user_preferences (
                    user_id INTEGER PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
                    allow_ubahn BOOLEAN NOT NULL DEFAULT TRUE,
                    allow_sbahn BOOLEAN NOT NULL DEFAULT TRUE,
                    allow_regional BOOLEAN NOT NULL DEFAULT TRUE,
                    allow_tram BOOLEAN NOT NULL DEFAULT TRUE,
                    allow_bus BOOLEAN NOT NULL DEFAULT TRUE,
                    timing_pref TEXT NOT NULL DEFAULT 'earlier',
                    arrival_time TEXT,
                    home_location TEXT
                );
                """
            )
            cur.execute(
                """
                ALTER TABLE user_preferences
                ADD COLUMN IF NOT EXISTS home_location TEXT;
                """
            )
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS email_notifications (
                    id SERIAL PRIMARY KEY,
                    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                    send_date DATE NOT NULL,
                    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
                    UNIQUE (user_id, send_date)
                );
                """
            )
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS reminder_logs (
                    id SERIAL PRIMARY KEY,
                    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                    send_date DATE NOT NULL,
                    kind TEXT NOT NULL,
                    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
                    UNIQUE (user_id, send_date, kind)
                );
                """
            )
        conn.commit()


@app.on_event("startup")
def on_startup():
    init_db()
    global _scheduler
    if _scheduler is None:
        scheduler = BackgroundScheduler(timezone=str(TZ))
        scheduler.add_job(send_daily_emails, "cron", hour=7, minute=0)
        scheduler.add_job(send_return_reminders, "interval", minutes=5)
        scheduler.start()
        _scheduler = scheduler


@app.on_event("shutdown")
def on_shutdown():
    global _scheduler
    if _scheduler:
        _scheduler.shutdown()
        _scheduler = None


class ClassIn(BaseModel):
    course_name: str
    start_time: datetime
    end_time: datetime
    location: str


class AuthIn(BaseModel):
    email: str
    password: str


class SignupIn(BaseModel):
    email: str
    password: str
    home_location: Optional[str] = None


class PreferencesIn(BaseModel):
    allow_ubahn: Optional[bool] = None
    allow_sbahn: Optional[bool] = None
    allow_regional: Optional[bool] = None
    allow_tram: Optional[bool] = None
    allow_bus: Optional[bool] = None
    timing_pref: Optional[str] = None
    arrival_time: Optional[str] = None
    home_location: Optional[str] = None


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    iterations = 120_000
    dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
    return "pbkdf2_sha256$%d$%s$%s" % (
        iterations,
        base64.b64encode(salt).decode("ascii"),
        base64.b64encode(dk).decode("ascii"),
    )


def verify_password(password: str, stored: str) -> bool:
    try:
        algo, iter_s, salt_b64, hash_b64 = stored.split("$", 3)
        if algo != "pbkdf2_sha256":
            return False
        iterations = int(iter_s)
        salt = base64.b64decode(salt_b64.encode("ascii"))
        expected = base64.b64decode(hash_b64.encode("ascii"))
    except Exception:
        return False
    dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
    return hmac.compare_digest(dk, expected)


def create_session(conn, user_id: int) -> str:
    token = secrets.token_urlsafe(32)
    expires_at = datetime.utcnow() + timedelta(days=7)
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO sessions (user_id, token, expires_at)
            VALUES (%s, %s, %s);
            """,
            (user_id, token, expires_at),
        )
    return token


def get_current_user(request: Request):
    token = request.cookies.get("session")
    if not token:
        return None
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT u.id, u.email
                FROM sessions s
                JOIN users u ON u.id = s.user_id
                WHERE s.token = %s AND s.expires_at > NOW();
                """,
                (token,),
            )
            row = cur.fetchone()
    return row


def require_user(request: Request):
    user = get_current_user(request)
    if not user:
        raise HTTPException(status_code=401, detail="Unauthorized")
    return user

@app.get("/", response_class=HTMLResponse)
def index(request: Request):
    if not get_current_user(request):
        return RedirectResponse("/login")
    with open(INDEX_PATH, "r", encoding="utf-8") as f:
        return f.read()


@app.get("/login", response_class=HTMLResponse)
def login_page(request: Request):
    if get_current_user(request):
        return RedirectResponse("/")
    with open(LOGIN_PATH, "r", encoding="utf-8") as f:
        return f.read()


@app.get("/signup", response_class=HTMLResponse)
def signup_page(request: Request):
    if get_current_user(request):
        return RedirectResponse("/")
    with open(SIGNUP_PATH, "r", encoding="utf-8") as f:
        return f.read()


@app.get("/api/db-test")
def db_test(request: Request):
    require_user(request)
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT NOW() AS now;")
            row = cur.fetchone()
    return {"ok": True, "db_time": row["now"]}


@app.get("/api/classes")
def list_classes(request: Request):
    user = require_user(request)
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT id, course_name, start_time, end_time, location
                FROM classes
                WHERE user_id = %s
                ORDER BY start_time DESC
                LIMIT 50;
                """
                ,
                (user["id"],),
            )
            rows = cur.fetchall()
    return {"items": rows}


@app.delete("/api/classes/{class_id}")
def delete_class(class_id: int, request: Request):
    user = require_user(request)
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "DELETE FROM classes WHERE id = %s AND user_id = %s RETURNING id;",
                (class_id, user["id"]),
            )
            row = cur.fetchone()
        conn.commit()
    if not row:
        raise HTTPException(status_code=404, detail="Class not found")
    return {"ok": True}


def bvg_get(path: str, params: list[tuple[str, str]]):
    url = f"{BVG_BASE_URL}{path}"
    try:
        with httpx.Client(timeout=10.0) as client:
            resp = client.get(url, params=params, headers={"User-Agent": "CampusPulse/1.0"})
        resp.raise_for_status()
    except httpx.HTTPStatusError as exc:
        raise HTTPException(status_code=exc.response.status_code, detail=exc.response.text)
    except httpx.RequestError as exc:
        raise HTTPException(status_code=502, detail=f"BVG request failed: {exc.__class__.__name__}")
    return resp.json()


@app.get("/api/bvg/locations")
def bvg_locations(request: Request):
    require_user(request)
    params = list(request.query_params.multi_items())
    return bvg_get("/locations", params)


@app.get("/api/bvg/locations/nearby")
def bvg_locations_nearby(request: Request):
    require_user(request)
    params = list(request.query_params.multi_items())
    return bvg_get("/locations/nearby", params)


@app.get("/api/public/locations/nearby")
def public_locations_nearby(request: Request):
    params = list(request.query_params.multi_items())
    return bvg_get("/locations/nearby", params)


@app.get("/api/bvg/stops/{stop_id}/departures")
def bvg_departures(stop_id: str, request: Request):
    require_user(request)
    params = list(request.query_params.multi_items())
    return bvg_get(f"/stops/{stop_id}/departures", params)


@app.get("/api/bvg/journeys")
def bvg_journeys(request: Request):
    require_user(request)
    params = list(request.query_params.multi_items())
    return bvg_get("/journeys", params)


@app.get("/api/geocode")
def geocode(request: Request, query: str):
    require_user(request)
    params = {
        "q": query,
        "format": "json",
        "limit": 1,
        "addressdetails": 0,
    }
    headers = {
        "User-Agent": f"CampusPulse/1.0 ({GEOCODE_CONTACT})",
        "Accept-Language": "en",
    }
    try:
        with httpx.Client(timeout=10.0) as client:
            resp = client.get(NOMINATIM_URL, params=params, headers=headers)
        resp.raise_for_status()
    except httpx.HTTPStatusError as exc:
        raise HTTPException(status_code=exc.response.status_code, detail=exc.response.text)
    except httpx.RequestError as exc:
        raise HTTPException(status_code=502, detail=f"Geocoding failed: {exc.__class__.__name__}")
    data = resp.json()
    if not data:
        raise HTTPException(status_code=404, detail="Address not found")
    item = data[0]
    return {
        "name": item.get("display_name") or query,
        "latitude": float(item["lat"]),
        "longitude": float(item["lon"]),
    }


@app.post("/api/notify/test")
def notify_test(request: Request):
    user = require_user(request)
    if not BREVO_API_KEY:
        raise HTTPException(status_code=500, detail="BREVO_API_KEY not set")
    if not BREVO_SENDER_EMAIL:
        raise HTTPException(status_code=500, detail="BREVO_SENDER_EMAIL not set")
    payload = {
        "sender": {"name": BREVO_SENDER_NAME, "email": BREVO_SENDER_EMAIL},
        "to": [{"email": user["email"], "name": user["email"]}],
        "subject": "CampusPulse test notification",
        "htmlContent": "<p>Your CampusPulse email notifications are working.</p>",
    }
    headers = {"api-key": BREVO_API_KEY, "content-type": "application/json"}
    try:
        with httpx.Client(timeout=10.0) as client:
            resp = client.post(BREVO_EMAIL_URL, json=payload, headers=headers)
        resp.raise_for_status()
    except httpx.HTTPStatusError as exc:
        raise HTTPException(status_code=exc.response.status_code, detail=exc.response.text)
    except httpx.RequestError as exc:
        raise HTTPException(status_code=502, detail=f"Brevo request failed: {exc.__class__.__name__}")
    return {"ok": True}


@app.post("/api/notify/daily-test")
def notify_daily_test(request: Request):
    user = require_user(request)
    today = datetime.now(TZ).date()
    if not BREVO_API_KEY or not BREVO_SENDER_EMAIL:
        raise HTTPException(status_code=500, detail="Brevo is not configured")
    with get_conn() as conn:
        prefs = preferences_for_user(conn, user["id"])
        classes = classes_for_day(conn, user["id"], today)
    home = (prefs or {}).get("home_location")
    journey = None
    if home:
        origin = resolve_location(home)
        destination = resolve_location("Campus Jungfernsee")
        journey = build_journey(origin, destination, prefs or {})
    html = build_journey_email(user["email"], classes, journey)
    send_brevo_email(user["email"], "CampusPulse daily reminder (test)", html)
    return {"ok": True}


def extract_coords(item: dict) -> Optional[tuple[float, float]]:
    if not item:
        return None
    if "latitude" in item and "longitude" in item:
        return float(item["latitude"]), float(item["longitude"])
    loc = item.get("location") or {}
    if "latitude" in loc and "longitude" in loc:
        return float(loc["latitude"]), float(loc["longitude"])
    return None


def normalize_stop_id(item: dict) -> Optional[str]:
    if not item:
        return None
    def pick_id(val: Optional[str]) -> Optional[str]:
        if not val or not isinstance(val, str):
            return None
        last = val.split(":")[-1]
        return last or None
    ibnr = pick_id(item.get("ibnr"))
    if ibnr and ibnr.isdigit():
        return ibnr
    sid = pick_id(item.get("id"))
    if sid and sid.isdigit():
        return sid
    station = item.get("station") or {}
    sid = pick_id(station.get("id"))
    if sid and sid.isdigit():
        return sid
    return None


def resolve_location(query: str) -> dict:
    items = bvg_get("/locations", [("query", query), ("results", "5")])
    for item in items or []:
        stop_id = normalize_stop_id(item)
        if stop_id:
            coords = extract_coords(item)
            return {"id": stop_id, "name": item.get("name") or query, "coords": coords}
    for item in items or []:
        coords = extract_coords(item)
        if coords:
            return {"id": None, "name": item.get("name") or query, "coords": coords}
    # fallback geocode
    params = {"q": query, "format": "json", "limit": 1, "addressdetails": 0}
    headers = {
        "User-Agent": f"CampusPulse/1.0 ({GEOCODE_CONTACT})",
        "Accept-Language": "en",
    }
    with httpx.Client(timeout=10.0) as client:
        resp = client.get(NOMINATIM_URL, params=params, headers=headers)
    resp.raise_for_status()
    data = resp.json()
    if not data:
        return {"id": None, "name": query, "coords": None}
    item = data[0]
    return {
        "id": None,
        "name": item.get("display_name") or query,
        "coords": (float(item["lat"]), float(item["lon"])),
    }


def preferences_for_user(conn, user_id: int) -> dict:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT allow_ubahn, allow_sbahn, allow_regional, allow_tram,
                   allow_bus, timing_pref, arrival_time, home_location
            FROM user_preferences
            WHERE user_id = %s;
            """,
            (user_id,),
        )
        row = cur.fetchone()
    if not row:
        return {}
    return row


def classes_for_day(conn, user_id: int, day: date) -> list[dict]:
    start = datetime.combine(day, time.min)
    end = datetime.combine(day, time.max)
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT course_name, start_time, end_time, location
            FROM classes
            WHERE user_id = %s AND start_time >= %s AND start_time <= %s
            ORDER BY start_time ASC;
            """,
            (user_id, start, end),
        )
        return cur.fetchall()


def build_arrival_datetime(arrival_time_str: Optional[str], timing_pref: str) -> Optional[datetime]:
    if not arrival_time_str:
        return None
    try:
        hh, mm = map(int, arrival_time_str.split(":"))
    except Exception:
        return None
    now = datetime.now(TZ)
    target = datetime(now.year, now.month, now.day, hh, mm, tzinfo=TZ)
    offset = 10 if timing_pref == "later" else -10
    return target + timedelta(minutes=offset)


def build_journey_email(user_email: str, classes: list[dict], journey: Optional[dict]) -> str:
    class_rows = ""
    for c in classes:
        start_str = c["start_time"].strftime("%H:%M")
        end_str = c["end_time"].strftime("%H:%M") if c.get("end_time") else ""
        time_str = f"{start_str}-{end_str}" if end_str else start_str
        class_rows += f"<tr><td>{time_str}</td><td>{c['course_name']}</td><td>{c['location']}</td></tr>"
    if not class_rows:
        class_rows = "<tr><td colspan='3'>No classes today.</td></tr>"

    journey_html = ""
    if journey:
        legs = journey.get("legs") or []
        leg_rows = ""
        for leg in legs:
            dep = (leg.get("departure") or "")[11:16]
            arr = (leg.get("arrival") or "")[11:16]
            mode = leg.get("line", {}).get("name") or leg.get("mode") or "Travel"
            origin = leg.get("origin", {}).get("name") or "Start"
            dest = leg.get("destination", {}).get("name") or "End"
            leg_rows += f"<tr><td>{mode}</td><td>{dep}-{arr}</td><td>{origin} → {dest}</td></tr>"
        journey_html = f"""
          <h3 style="margin:20px 0 8px;">Route to Campus Jungfernsee</h3>
          <table style="width:100%;border-collapse:collapse;">
            <tr><th align="left">Line</th><th align="left">Time</th><th align="left">Segment</th></tr>
            {leg_rows}
          </table>
        """

    return f"""
    <div style="font-family:Arial,sans-serif;color:#0f172a;line-height:1.4;">
      <h2 style="margin:0 0 8px;">CampusPulse Daily Reminder</h2>
      <p>Good morning {user_email}, here is your schedule for today.</p>
      <h3 style="margin:16px 0 8px;">Classes</h3>
      <table style="width:100%;border-collapse:collapse;">
        <tr><th align="left">Time</th><th align="left">Course</th><th align="left">Location</th></tr>
        {class_rows}
      </table>
      {journey_html}
    </div>
    """


def send_brevo_email(to_email: str, subject: str, html: str):
    if not BREVO_API_KEY or not BREVO_SENDER_EMAIL:
        return
    payload = {
        "sender": {"name": BREVO_SENDER_NAME, "email": BREVO_SENDER_EMAIL},
        "to": [{"email": to_email, "name": to_email}],
        "subject": subject,
        "htmlContent": html,
    }
    headers = {"api-key": BREVO_API_KEY, "content-type": "application/json"}
    with httpx.Client(timeout=10.0) as client:
        resp = client.post(BREVO_EMAIL_URL, json=payload, headers=headers)
    resp.raise_for_status()


def build_journey(origin: dict, destination: dict, prefs: dict) -> Optional[dict]:
    params = {"results": "3", "polylines": "false"}
    if origin.get("id") and destination.get("id"):
        params["from"] = origin["id"]
        params["to"] = destination["id"]
    else:
        if not origin.get("coords") or not destination.get("coords"):
            return None
        params["from.latitude"] = origin["coords"][0]
        params["from.longitude"] = origin["coords"][1]
        params["from.name"] = origin.get("name") or "Start"
        params["to.latitude"] = destination["coords"][0]
        params["to.longitude"] = destination["coords"][1]
        params["to.name"] = destination.get("name") or "Campus Jungfernsee"
    params["products[subway]"] = str(prefs.get("allow_ubahn", True)).lower()
    params["products[suburban]"] = str(prefs.get("allow_sbahn", True)).lower()
    params["products[regional]"] = str(prefs.get("allow_regional", True)).lower()
    params["products[tram]"] = str(prefs.get("allow_tram", True)).lower()
    params["products[bus]"] = str(prefs.get("allow_bus", True)).lower()
    arrival = build_arrival_datetime(prefs.get("arrival_time"), prefs.get("timing_pref", "earlier"))
    if arrival:
        params["arrival"] = arrival.isoformat()
    data = bvg_get("/journeys", list(params.items()))
    journeys = data.get("journeys") or []
    if not journeys:
        return None
    return journeys[0]


def send_daily_emails():
    today = datetime.now(TZ).date()
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT id, email FROM users;")
            users = cur.fetchall()
        for user in users:
            user_id = user["id"]
            email = user["email"]
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT 1 FROM email_notifications WHERE user_id = %s AND send_date = %s;",
                    (user_id, today),
                )
                already = cur.fetchone()
            if already:
                continue
            prefs = preferences_for_user(conn, user_id)
            classes = classes_for_day(conn, user_id, today)
            if not classes:
                continue
            home = prefs.get("home_location") if prefs else None
            journey = None
            if home:
                origin = resolve_location(home)
                destination = resolve_location("Campus Jungfernsee")
                journey = build_journey(origin, destination, prefs or {})
            html = build_journey_email(email, classes, journey)
            try:
                send_brevo_email(email, "CampusPulse daily reminder", html)
            except Exception:
                continue
            with conn.cursor() as cur:
                cur.execute(
                    "INSERT INTO email_notifications (user_id, send_date) VALUES (%s, %s);",
                    (user_id, today),
                )
            conn.commit()


def last_class_end(conn, user_id: int, day: date) -> Optional[datetime]:
    start = datetime.combine(day, time.min)
    end = datetime.combine(day, time.max)
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT MAX(end_time) AS last_end
            FROM classes
            WHERE user_id = %s AND end_time >= %s AND end_time <= %s;
            """,
            (user_id, start, end),
        )
        row = cur.fetchone()
    return row["last_end"] if row else None


def send_return_reminders():
    now = datetime.now(TZ)
    today = now.date()
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT id, email FROM users;")
            users = cur.fetchall()
        for user in users:
            user_id = user["id"]
            email = user["email"]
            last_end = last_class_end(conn, user_id, today)
            if not last_end:
                continue
            target = last_end - timedelta(minutes=30)
            if not (target <= now <= target + timedelta(minutes=5)):
                continue
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT 1 FROM reminder_logs WHERE user_id = %s AND send_date = %s AND kind = %s;",
                    (user_id, today, "return"),
                )
                already = cur.fetchone()
            if already:
                continue
            prefs = preferences_for_user(conn, user_id)
            home = (prefs or {}).get("home_location")
            journey = None
            if home:
                origin = resolve_location("Campus Jungfernsee")
                destination = resolve_location(home)
                journey = build_journey(origin, destination, prefs or {})
            classes = classes_for_day(conn, user_id, today)
            html = build_journey_email(email, classes, journey)
            try:
                send_brevo_email(email, "CampusPulse reminder: time to head home", html)
            except Exception:
                continue
            with conn.cursor() as cur:
                cur.execute(
                    "INSERT INTO reminder_logs (user_id, send_date, kind) VALUES (%s, %s, %s);",
                    (user_id, today, "return"),
                )
            conn.commit()


@app.post("/api/classes", status_code=201)
def create_class(payload: ClassIn, request: Request):
    user = require_user(request)
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO classes (user_id, course_name, start_time, end_time, location)
                VALUES (%s, %s, %s, %s, %s)
                RETURNING id, course_name, start_time, end_time, location;
                """,
                (
                    user["id"],
                    payload.course_name,
                    payload.start_time,
                    payload.end_time,
                    payload.location,
                ),
            )
            row = cur.fetchone()
        conn.commit()
    return row


@app.get("/api/auth/me")
def auth_me(request: Request):
    user = get_current_user(request)
    if not user:
        raise HTTPException(status_code=401, detail="Unauthorized")
    return {"id": user["id"], "email": user["email"]}


@app.post("/api/auth/signup")
def auth_signup(payload: SignupIn):
    email = payload.email.strip().lower()
    if not email.endswith("@ue-germany.de"):
        raise HTTPException(status_code=400, detail="Email must end with @ue-germany.de")
    if len(payload.password) < 8:
        raise HTTPException(status_code=400, detail="Password must be at least 8 characters")
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT id FROM users WHERE email = %s;", (email,))
            existing = cur.fetchone()
            if existing:
                raise HTTPException(status_code=409, detail="User already exists")
            password_hash = hash_password(payload.password)
            cur.execute(
                """
                INSERT INTO users (email, password_hash)
                VALUES (%s, %s)
                RETURNING id, email;
                """,
                (email, password_hash),
            )
            user = cur.fetchone()
            if payload.home_location:
                cur.execute(
                    """
                    INSERT INTO user_preferences (user_id, home_location)
                    VALUES (%s, %s)
                    ON CONFLICT (user_id) DO UPDATE SET home_location = EXCLUDED.home_location;
                    """,
                    (user["id"], payload.home_location),
                )
            token = create_session(conn, user["id"])
        conn.commit()
    response = HTMLResponse(content="", status_code=204)
    response.set_cookie(
        "session",
        token,
        httponly=True,
        samesite="lax",
        max_age=60 * 60 * 24 * 7,
    )
    return response


@app.post("/api/auth/login")
def auth_login(payload: AuthIn):
    email = payload.email.strip().lower()
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id, email, password_hash FROM users WHERE email = %s;",
                (email,),
            )
            user = cur.fetchone()
            if not user or not verify_password(payload.password, user["password_hash"]):
                raise HTTPException(status_code=401, detail="Invalid credentials")
            token = create_session(conn, user["id"])
        conn.commit()
    response = HTMLResponse(content="", status_code=204)
    response.set_cookie(
        "session",
        token,
        httponly=True,
        samesite="lax",
        max_age=60 * 60 * 24 * 7,
    )
    return response


@app.post("/api/auth/logout")
def auth_logout(request: Request):
    token = request.cookies.get("session")
    if token:
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("DELETE FROM sessions WHERE token = %s;", (token,))
            conn.commit()
    response = HTMLResponse(content="", status_code=204)
    response.delete_cookie("session")
    return response


@app.get("/api/preferences")
def get_preferences(request: Request):
    user = require_user(request)
    defaults = {
        "allow_ubahn": True,
        "allow_sbahn": True,
        "allow_regional": True,
        "allow_tram": True,
        "allow_bus": True,
        "timing_pref": "earlier",
        "arrival_time": "",
        "home_location": "",
    }
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT allow_ubahn, allow_sbahn, allow_regional, allow_tram,
                       allow_bus, timing_pref, arrival_time, home_location
                FROM user_preferences
                WHERE user_id = %s;
                """,
                (user["id"],),
            )
            row = cur.fetchone()
    if not row:
        return defaults
    return {
        "allow_ubahn": row["allow_ubahn"],
        "allow_sbahn": row["allow_sbahn"],
        "allow_regional": row["allow_regional"],
        "allow_tram": row["allow_tram"],
        "allow_bus": row["allow_bus"],
        "timing_pref": row["timing_pref"],
        "arrival_time": row["arrival_time"] or "",
        "home_location": row["home_location"] or "",
    }


@app.post("/api/preferences")
def save_preferences(payload: PreferencesIn, request: Request):
    user = require_user(request)
    timing_pref = payload.timing_pref or "earlier"
    if timing_pref not in {"earlier", "later"}:
        raise HTTPException(status_code=400, detail="Invalid timing preference")
    current_home = None
    if payload.home_location is None:
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT home_location FROM user_preferences WHERE user_id = %s;",
                    (user["id"],),
                )
                row = cur.fetchone()
                if row:
                    current_home = row["home_location"]
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO user_preferences (
                    user_id, allow_ubahn, allow_sbahn, allow_regional,
                    allow_tram, allow_bus, timing_pref, arrival_time, home_location
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (user_id) DO UPDATE SET
                    allow_ubahn = EXCLUDED.allow_ubahn,
                    allow_sbahn = EXCLUDED.allow_sbahn,
                    allow_regional = EXCLUDED.allow_regional,
                    allow_tram = EXCLUDED.allow_tram,
                    allow_bus = EXCLUDED.allow_bus,
                    timing_pref = EXCLUDED.timing_pref,
                    arrival_time = EXCLUDED.arrival_time,
                    home_location = EXCLUDED.home_location;
                """,
                (
                    user["id"],
                    payload.allow_ubahn if payload.allow_ubahn is not None else True,
                    payload.allow_sbahn if payload.allow_sbahn is not None else True,
                    payload.allow_regional if payload.allow_regional is not None else True,
                    payload.allow_tram if payload.allow_tram is not None else True,
                    payload.allow_bus if payload.allow_bus is not None else True,
                    timing_pref,
                    payload.arrival_time or None,
                    payload.home_location if payload.home_location is not None else current_home,
                ),
            )
        conn.commit()
    return {"ok": True}
