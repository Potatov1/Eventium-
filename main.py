import os
import math
import sqlite3
from datetime import datetime, timedelta, timezone
from typing import Optional, List, Dict, Any
import uuid
import requests
from dotenv import load_dotenv
from fastapi import (
    FastAPI, 
    HTTPException, 
    UploadFile, 
    File, 
    Depends, 
    Body, 
    Query, 
    Form, 
    Header,
    Path,
    Cookie,
    BackgroundTasks,
    Request,
    Response,
    status
)


from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, Field, constr
import jwt
from passlib.hash import bcrypt

# -------------------------
# Env & constants
# -------------------------
load_dotenv()
FOURSQUARE_API_KEY = os.getenv("FOURSQUARE_API_KEY")  # put in .env
if not FOURSQUARE_API_KEY:
    raise RuntimeError("FOURSQUARE_API_KEY is missing in .env")

JWT_SECRET = os.getenv("JWT_SECRET", "dev-secret-change-me")
JWT_ALG = "HS256"
TOKEN_EXPIRE_MIN = int(os.getenv("TOKEN_EXPIRE_MIN", "120"))

FSQ_BASE = "https://places-api.foursquare.com/places"
FSQ_HEADERS = {
    "Authorization": f"Bearer {FOURSQUARE_API_KEY}",
    "Accept": "application/json",
    "X-Places-API-Version": "2025-06-17",
}


# -------------------------
# DB init (uses existing DB)
# -------------------------
DB_PATH = os.getenv("DB_PATH", "new1.db")

def db():
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    return con


# -------------------------
# FastAPI app
# -------------------------
app = FastAPI(title="Events + Foursquare v2025")

# CORS (frontend uses same origin, but keep permissive in dev)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], allow_credentials=True,
    allow_methods=["*"], allow_headers=["*"],
)

# Static (frontend) — the "static" folder must exist with index.html inside
os.makedirs("static", exist_ok=True)
app.mount("/static", StaticFiles(directory="static"), name="static")

@app.get("/")
def serve_index():
    index_path = os.path.join("static", "index.html")
    if not os.path.exists(index_path):
        return JSONResponse({"message": "Backend OK. Put your index.html in ./static/index.html"}, status_code=200)
    return FileResponse(index_path)

# -------------------------
# Auth helpers
# -------------------------
def create_token(user_id: int, username: str) -> str:
    payload = {
        "sub": str(user_id),
        "username": username,
        "exp": datetime.now(timezone.utc) + timedelta(minutes=TOKEN_EXPIRE_MIN),
        "iat": datetime.now(timezone.utc),
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALG)

def get_current_user(authorization: Optional[str] = Header(None)) -> Dict[str, Any]:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="Missing Bearer token")
    token = authorization.split(" ", 1)[1].strip()
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALG])
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token expired")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="Invalid token")
    return {"user_id": int(payload["sub"]), "username": payload["username"]}
def require_admin(user=Depends(get_current_user)):
    with db() as con:
        cur = con.execute("SELECT is_admin FROM users WHERE id = ?", (user["user_id"],))
        row = cur.fetchone()
        if not row or row["is_admin"] != 1:
            raise HTTPException(403, "Admin access required")
    return user

# -------------------------
# Pydantic models
# -------------------------
class SignupIn(BaseModel):
    username: constr(min_length=3, max_length=30)
    password: constr(min_length=6, max_length=128)

class LoginIn(BaseModel):
    username: str
    password: str

class EventCreateIn(BaseModel):
    title: str
    description: Optional[str] = ""
    type: constr(pattern="^(public|private)$")

    date_time: str  # ISO string
    capacity: Optional[int] = None
    # FSQ selection (client will call /fsq_search and send chosen fsq_place payload)
    fsq_id: str
    venue_name: str
    venue_address: str
    venue_lat: float
    venue_lon: float
    venue_category: Optional[str] = None
    invite_code: Optional[str] = None

class EventOut(BaseModel):
    event_id: str
    title: str
    description: Optional[str]
    date_time: str
    type: str
    capacity: Optional[int]
    venue_name: Optional[str]
    venue_address: str
    venue_lat: Optional[float]
    venue_lon: Optional[float]
    venue_category: Optional[str]
    danger_rating: Optional[float] = 0.0
# -------------------------
# Auth endpoints
# -------------------------
@app.post("/signup")
def signup(payload: SignupIn):
    with db() as con:
        cur = con.cursor()
        try:
            cur.execute(
                "INSERT INTO users (username, password_hash) VALUES (?, ?)",
                (payload.username.lower(), bcrypt.hash(payload.password)),
            )
            con.commit()
        except sqlite3.IntegrityError:
            raise HTTPException(400, "Username already exists")
        user_id = cur.lastrowid
    token = create_token(user_id, payload.username)
    return {"token": token, "user_id": user_id, "username": payload.username}

@app.post("/login")
def login(payload: LoginIn):
    with db() as con:
        cur = con.execute("SELECT * FROM users WHERE username = ?", (payload.username.lower(),))
        row = cur.fetchone()
        if not row or not bcrypt.verify(payload.password, row["password_hash"]):
            raise HTTPException(401, "Invalid credentials")
        token = create_token(row["id"], payload.username)
        return {"token": token, "user_id": row["id"], "username": payload.username}

# -------------------------
# Foursquare Search (v2025)
# -------------------------
@app.get("/fsq_search")
def fsq_search(
    query: str = Query(..., description="Search text (e.g. pizza, coffee)"),
    lat: float = Query(...),
    lon: float = Query(...),
    radius: int = Query(5000, ge=1, le=100000),
    limit: int = Query(10, ge=1, le=50),
):
    params = {
        "query": query,
        "ll": f"{lat},{lon}",
        "radius": radius,
        "limit": limit
    }
    url = f"{FSQ_BASE}/search"
    try:
        r = requests.get(url, headers=FSQ_HEADERS, params=params, timeout=20)
        r.raise_for_status()
        return r.json()
    except requests.HTTPError as e:
        # Bubble up FSQ error content if present
        try:
            return JSONResponse(status_code=r.status_code, content=r.json())
        except Exception:
            raise HTTPException(r.status_code, f"Foursquare error: {e}")
    except requests.RequestException as e:
        raise HTTPException(502, f"Upstream error: {e}")

# -------------------------
# Event creation
# -------------------------
@app.get("/event/{event_id}")
def get_event(event_id: str):
    """
    Fetch full event details by event_id, including all uploaded images.
    """
    conn = db()
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    # Fetch event details
    cur.execute("SELECT * FROM events WHERE event_id = ?", (event_id,))
    event = cur.fetchone()
    if not event:
        conn.close()
        raise HTTPException(status_code=404, detail="Event not found")

    event_data = {k: event[k] for k in event.keys()}

    # Fetch all related images
    cur.execute("SELECT filename FROM event_images WHERE event_id = ?", (event_id,))
    images = [f"/static/uploads/{row['filename']}" for row in cur.fetchall()]
    event_data["images"] = [{"url": url} for url in images]

    conn.close()
    return event_data










@app.post("/create_event")
def create_event(payload: EventCreateIn, user=Depends(get_current_user)):
    # Spam filter on title and description
    if contains_spam(payload.title) or contains_spam(payload.description):
        raise HTTPException(400, "Event creation contains spammy content and is not allowed.")
    
    # Validate and convert date_time to UTC-aware ISO string
    try:
        dt = datetime.fromisoformat(payload.date_time.replace("Z", "+00:00"))
        payload_date_time_str = dt.isoformat()
    except Exception:
        raise HTTPException(400, "date_time must be ISO-8601 (e.g. 2025-08-20T18:30:00Z)")

    with db() as con:
        # Check for duplicate event by this user
        existing = con.execute("""
            SELECT event_id FROM events
            WHERE host_id = ? AND title = ? AND date_time = ? AND venue_name = ?
        """, (str(user["user_id"]), payload.title, payload_date_time_str, payload.venue_name)).fetchone()

        if existing:
            raise HTTPException(400, "You have already created a similar event.")
        
        # Proceed with event creation
        event_id = str(uuid.uuid4())
        con.execute(
            """
            INSERT INTO events (
                event_id, host_id, title, description, fsq_id, venue_name, venue_address,
                venue_lat, venue_lon, venue_category, type, invite_code, date_time, capacity
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                event_id, str(user["user_id"]), payload.title, payload.description, payload.fsq_id,
                payload.venue_name, payload.venue_address, payload.venue_lat, payload.venue_lon,
                payload.venue_category, payload.type, payload.invite_code, payload_date_time_str,
                payload.capacity
            )
        )
        con.commit()

        # Add tags after insert
        tags = ",".join(auto_tags(payload.description))
        con.execute("UPDATE events SET tags = ? WHERE event_id = ?", (tags, event_id))
        con.commit()

    return {"ok": True, "event_id": event_id}



@app.delete("/admin/delete_event/{event_id}")
def admin_delete_event(event_id: str, user=Depends(require_admin)):
    with db() as con:
        con.execute("DELETE FROM events WHERE event_id = ?", (event_id,))
        con.execute("DELETE FROM event_enrollment WHERE event_id = ?", (event_id,))
        con.commit()
    return {"ok": True, "message": f"Event {event_id} deleted"}

# After event insert in /create_event



# -------------------------
# Haversine + search events by radius
# -------------------------
def haversine_km(lat1, lon1, lat2, lon2):
    # Earth radius in KM
    R = 6371.0088
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = (math.sin(dlat/2)**2 +
         math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) *
         math.sin(dlon/2)**2)
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1-a))
    return R * c

@app.get("/search_events", response_model=List[EventOut])
def search_events(
    lat: float = Query(...),
    lon: float = Query(...),
    radius_km: float = Query(5.0, gt=0, le=100.0)
):
    now = datetime.now(timezone.utc)

    with db() as con:
        rows = con.execute("""
            SELECT event_id, title, description, date_time, type, capacity,
                   venue_name, venue_address, venue_lat, venue_lon, venue_category
            FROM events
            WHERE venue_lat IS NOT NULL AND venue_lon IS NOT NULL
        """).fetchall()

    results = []
    for r in rows:
        try:
            dt = datetime.fromisoformat(r["date_time"].replace("Z", "+00:00"))
        except Exception:
            continue

        # Skip expired events (past +1 hour)
        if now > dt + timedelta(hours=1):
            continue

        dist = haversine_km(lat, lon, r["venue_lat"], r["venue_lon"])
        if dist <= radius_km:
            danger_rating = calculate_danger_rating(r["title"], r["description"])
            results.append(EventOut(
                event_id=r["event_id"],
                title=r["title"],
                description=r["description"],
                date_time=r["date_time"],
                type=r["type"],
                capacity=r["capacity"],
                venue_name=r["venue_name"],
                venue_address=r["venue_address"],
                venue_lat=r["venue_lat"],
                venue_lon=r["venue_lon"],
                venue_category=r["venue_category"],
                danger_rating=danger_rating,
            ))
    return results

from uuid import uuid4

# -------------------------
# Enrollment Endpoints
# -------------------------

@app.post("/enroll/{event_id}")
def enroll(event_id: str, user_id: int = Query(..., description="User ID from login")):
    with db() as con:
        cur = con.cursor()

        # Check event exists
        event = cur.execute(
            "SELECT capacity FROM events WHERE event_id = ?",
            (event_id,)
        ).fetchone()
        if not event:
            raise HTTPException(404, "Event not found")

        # Prevent duplicate enrollment
        existing = cur.execute(
            "SELECT * FROM event_enrollment WHERE event_id = ? AND user_id = ?",
            (event_id, user_id)
        ).fetchone()
        if existing:
            raise HTTPException(400, "Already enrolled in this event")

        # Capacity check
        if event["capacity"] is not None:
            enrolled_count = cur.execute(
                "SELECT COUNT(*) FROM event_enrollment WHERE event_id = ?",
                (event_id,)
            ).fetchone()[0]
            if enrolled_count >= event["capacity"]:
                raise HTTPException(400, "Event is full")

        # Insert enrollment
        enrollment_id = str(uuid4())
        cur.execute(
            "INSERT INTO event_enrollment (enrollment_id, event_id, user_id) VALUES (?, ?, ?)",
            (enrollment_id, event_id, user_id)
        )
        con.commit()

    return {"ok": True, "event_id": event_id, "user_id": user_id, "enrollment_id": enrollment_id}


@app.get("/enrollments/{event_id}")
def list_enrollments(event_id: str):
    with db() as con:
        rows = con.execute("""
            SELECT e.enrollment_id, u.id as user_id, u.username, e.enrolled_at
            FROM event_enrollment e
            JOIN users u ON u.id = e.user_id
            WHERE e.event_id = ?
        """, (event_id,)).fetchall()
    return [
        {
            "enrollment_id": r["enrollment_id"],
            "user_id": r["user_id"],
            "username": r["username"],
            "enrolled_at": r["enrolled_at"],
        }
        for r in rows
    ]


@app.post("/reminders/{event_id}")
def add_reminder(
    event_id: str,
    notify_minutes_before: int = Body(..., embed=True, ge=5, le=1440),
    user=Depends(get_current_user)
):
    with db() as con:
        con.execute("""
            INSERT INTO reminders (user_id, event_id, notify_minutes_before)
            VALUES (?, ?, ?)
        """, (user["user_id"], event_id, notify_minutes_before))
        con.commit()
    return {"ok": True, "message": f"Reminder set {notify_minutes_before} mins before event"}


@app.delete("/unenroll/{event_id}")
def unenroll(event_id: str, user_id: int = Query(..., description="User ID from login")):
    with db() as con:
        cur = con.cursor()
        enrollment = cur.execute(
            "SELECT * FROM event_enrollment WHERE event_id = ? AND user_id = ?",
            (event_id, user_id)
        ).fetchone()

        if not enrollment:
            raise HTTPException(404, "Enrollment not found")

        cur.execute(
            "DELETE FROM event_enrollment WHERE event_id = ? AND user_id = ?",
            (event_id, user_id)
        )
        con.commit()

    return {"ok": True, "message": f"User {user_id} unenrolled from event {event_id}"}


# -------------------------
# Event Queries (added)
# -------------------------

def haversine_km(lat1, lon1, lat2, lon2):
    from math import radians, sin, cos, asin, sqrt
    if None in (lat1, lon1, lat2, lon2):
        return 1e9
    R = 6371.0
    dlat = radians(lat2 - lat1)
    dlon = radians(lon2 - lon1)
    a = sin(dlat/2)**2 + cos(radians(lat1)) * cos(radians(lat2)) * sin(dlon/2)**2
    c = 2 * asin(sqrt(a))
    return R * c


def row_to_event_dict(row):
    d = dict(row)
    # Ensure required fields exist and types are UI-friendly
    d["event_id"] = str(d.get("event_id"))
    d["title"] = d.get("title") or ""
    d["description"] = d.get("description") or ""
    # Lat/Lon
    try:
        d["venue_lat"] = float(d["venue_lat"]) if d.get("venue_lat") is not None else None
    except Exception:
        d["venue_lat"] = None
    try:
        d["venue_lon"] = float(d["venue_lon"]) if d.get("venue_lon") is not None else None
    except Exception:
        d["venue_lon"] = None
    # Date normalization -> ISO string for JS Date()
    dt = d.get("date_time")
    if dt is not None:
        try:
            if not isinstance(dt, str):
                import datetime
                if isinstance(dt, (datetime.datetime, datetime.date)):
                    dt = dt.isoformat()
                else:
                    dt = str(dt)
        except Exception:
            dt = str(dt)
    d["date_time"] = dt
    # Counts
    try:
        d["enrolled_count"] = int(d.get("enrolled_count", 0))
    except Exception:
        d["enrolled_count"] = 0
    # Derived flags
    d["danger_rating"] = float(calculate_danger_rating(d.get("title",""), d.get("description","") or "")) if 'calculate_danger_rating' in globals() else 0.0
    d["is_spam"] = bool(contains_spam(d.get("description","") or "")) if 'contains_spam' in globals() else False
    # Tags: UI expects comma-separated string; fetch from event_tags else auto
    tags = []
    try:
        with db() as con2:
            trows = con2.execute("SELECT tag FROM event_tags WHERE event_id = ?", (d["event_id"],)).fetchall()
            tags = [tr["tag"] for tr in trows]
    except Exception:
        pass
    if not tags:
        try:
            tags = auto_tags(d.get("description","") or "")
        except Exception:
            tags = []
    d["tags"] = ",".join(tags)
    # Normalize host_id to string if present
    if "host_id" in d and d["host_id"] is not None:
        d["host_id"] = str(d["host_id"])
    return d


@app.get("/search_events")
def search_events(lat: float = Query(...), lon: float = Query(...), radius_km: float = Query(5.0)):
    with db() as con:
        rows = con.execute("""
            SELECT e.*, 
                (SELECT COUNT(*) FROM event_enrollment ee WHERE ee.event_id = e.event_id) AS enrolled_count
            FROM events e
            WHERE e.venue_lat IS NOT NULL AND e.venue_lon IS NOT NULL
        """).fetchall()
    events = []
    for r in rows:
        ev = row_to_event_dict(r)
        try:
            d = haversine_km(lat, lon, float(ev.get("venue_lat")), float(ev.get("venue_lon")))
        except Exception:
            d = 1e9
        if d <= radius_km:
            ev["distance_km"] = d
            events.append(ev)
    # sort by distance then time
    events.sort(key=lambda x: (x.get("distance_km", 1e9), x.get("date_time") or ""))
    return events

@app.get("/joined_events/{user_id}")
def joined_events(user_id: int, user=Depends(get_current_user)):
    if user_id != user["user_id"]:
        # For simplicity, require the same user
        raise HTTPException(403, "Forbidden")
    with db() as con:
        rows = con.execute("""
            SELECT e.*, 
                (SELECT COUNT(*) FROM event_enrollment ee WHERE ee.event_id = e.event_id) AS enrolled_count
            FROM event_enrollment j
            JOIN events e ON e.event_id = j.event_id
            WHERE j.user_id = ?
            ORDER BY e.date_time DESC
        """, (user_id,)).fetchall()
    return [row_to_event_dict(r) for r in rows]

@app.get("/created_events/{user_id}")
def created_events(user_id: int, user=Depends(get_current_user)):
    if user_id != user["user_id"]:
        raise HTTPException(403, "Forbidden")
    with db() as con:
        rows = con.execute("""
            SELECT e.*, 
                (SELECT COUNT(*) FROM event_enrollment ee WHERE ee.event_id = e.event_id) AS enrolled_count
            FROM events e
            WHERE e.host_id = ?
            ORDER BY e.date_time DESC
        """, (str(user_id),)).fetchall()
    return [row_to_event_dict(r) for r in rows]
# -------------------------
# Simple agentic features
# -------------------------

from typing import List

# Keyword-based urgency levels
URGENCY_KEYWORDS = {
    "fire": "high",
    "accident": "high",
    "protest": "high",
    "riot": "high",
    "festival": "medium",
    "concert": "medium",
    "gathering": "medium",
    "meeting": "low",
    "sports": "low",
}

def classify_urgency(description: str) -> str:
    """Return urgency level based on keywords in description"""
    desc = (description or "").lower()
    for word, severity in URGENCY_KEYWORDS.items():
        if word in desc:
            return severity
    return "low"

def auto_tags(description: str) -> List[str]:
    """Generate simple tags from description keywords"""
    desc = (description or "").lower()
    tags = []
    for word in ["protest", "concert", "sports", "festival", "accident", "fire", "meeting"]:
        if word in desc:
            tags.append(word)
    return tags

SPAM_KEYWORDS = [
    "buy now", "free money", "click here", "visit", "offer", "discount",
    "subscribe", "winner", "credit card", "loan", "cheap", "guarantee",
    "act now", "risk free", "limited time", "urgent", "deal"
]

def contains_spam(text: str) -> bool:
    text_lower = (text or "").lower()
    for spam_word in SPAM_KEYWORDS:
        if spam_word in text_lower:
            return True
    return False
DANGER_KEYWORDS = {
    "fire": 9,
    "accident": 9,
    "riot": 8,
    "protest": 7,
    "festival": 4,
    "concert": 3,
    "meeting": 1,
    # add more if you want
}

def calculate_danger_rating(title: str, description: str) -> float:
    texts = [title.lower() if title else "", description.lower() if description else ""]
    scores = []

    for text in texts:
        for word, score in DANGER_KEYWORDS.items():
            if word in text:
                scores.append(score)

    if not scores:
        return 0.0  # no danger keywords found

    return sum(scores) / len(scores)

@app.get("/recommendations")
def recommendations(user_id: int = Query(..., description="User ID")):
    """
    Suggest events based on categories of previously enrolled events.
    Adds urgency + tags for a more 'agentic' feel.
    """
    with db() as con:
        cur = con.cursor()

        # Get categories user enrolled in
        categories = cur.execute("""
            SELECT DISTINCT ev.venue_category
            FROM event_enrollment en
            JOIN events ev ON ev.event_id = en.event_id
            WHERE en.user_id = ?
        """, (user_id,)).fetchall()

        if not categories:
            return {"recommendations": []}

        category_list = [c["venue_category"] for c in categories if c["venue_category"]]
        if not category_list:
            return {"recommendations": []}

        # Fetch upcoming events in same categories
        now = datetime.now(timezone.utc)
        rows = cur.execute("""
            SELECT *
            FROM events
            WHERE venue_category IN ({})
        """.format(",".join("?"*len(category_list))), category_list).fetchall()

    recs = []
    for r in rows:
        try:
            dt = datetime.fromisoformat(r["date_time"].replace("Z", "+00:00"))
        except Exception:
            continue

        # Skip expired events (past +1 hour)
        if now > dt + timedelta(hours=1):
            continue

        danger_rating = calculate_danger_rating(r["title"], r["description"])
        
        recs.append({
            "event_id": r["event_id"],
            "title": r["title"],
            "description": r["description"],
            "venue_category": r["venue_category"],
            "urgency": classify_urgency(r["description"]),
            "tags": r["tags"].split(",") if r["tags"] else auto_tags(r["description"])
        })

    return {"recommendations": recs}

from fastapi_utils.tasks import repeat_every

@app.on_event("startup")
@repeat_every(seconds=60)  # every minute
def send_reminders():
    now = datetime.now(timezone.utc)
    with db() as con:
        rows = con.execute("""
            SELECT r.id, r.user_id, r.event_id, r.notify_minutes_before, e.title, e.date_time
            FROM reminders r
            JOIN events e ON e.event_id = r.event_id
        """).fetchall()

        for r in rows:
            try:
                event_time = datetime.fromisoformat(r["date_time"].replace("Z", "+00:00"))
                notify_time = event_time - timedelta(minutes=r["notify_minutes_before"])
                if notify_time <= now < notify_time + timedelta(minutes=1):
                    print(f"[Reminder] Notify user {r['user_id']} about event '{r['title']}'")
            except Exception:
                continue


from fastapi import UploadFile, File
import shutil

@app.post("/upload_event_image/{event_id}")
async def upload_event_image(
    event_id: str,
    user_id: int = Form(...),
    file: UploadFile = File(...)
):
    """
    Upload an image for a specific event.
    Stores entry in event_images table and returns its URL.
    """
    conn = db()
    cur = conn.cursor()

    # Verify event exists
    cur.execute("SELECT 1 FROM events WHERE event_id = ?", (event_id,))
    if not cur.fetchone():
        conn.close()
        raise HTTPException(status_code=404, detail="Event not found")

    # Save file
    filename = f"{uuid.uuid4()}_{file.filename}"
    filepath = os.path.join("static", "uploads", filename)
    os.makedirs(os.path.dirname(filepath), exist_ok=True)

    with open(filepath, "wb") as buffer:
        buffer.write(await file.read())

    # Insert record
    cur.execute("""
        INSERT INTO event_images (event_id, user_id, filename, file_path)
        VALUES (?, ?, ?, ?)
    """, (event_id, user_id, filename, filepath))
    conn.commit()
    conn.close()

    return {"message": "Image uploaded", "url": f"/static/uploads/{filename}"}


# -------------------------
# Filter Events Endpoint
# -------------------------
@app.get("/filter_events")
def filter_events(type: Optional[str] = Query(None),
                  date: Optional[str] = Query(None),
                  location: Optional[str] = Query(None),
                  category: Optional[str] = Query(None)): # Add category filter
    try:
        with db() as con:
            query = """
                SELECT event_id, title, description, type, date_time,
                       venue_name, venue_address, venue_category
                FROM events
                WHERE 1=1
            """
            params = []

            if type:
                query += " AND LOWER(type) = LOWER(?)"
                params.append(type)

            if date:
                # Assuming date format is YYYY-MM-DD
                query += " AND date(date_time) = date(?)"
                params.append(date)

            if location:
                query += " AND (title LIKE ? OR venue_name LIKE ? OR venue_address LIKE ?)"
                params.extend([f"%{location}%"] * 3)

            if category: # Add category filter condition
                query += " AND LOWER(venue_category) LIKE LOWER(?)"
                params.append(f"%{category}%")


            rows = con.execute(query, params).fetchall()

        events = []
        for r in rows:
            events.append({
                "event_id": r["event_id"],
                "title": r["title"],
                "description": r["description"],
                "type": r["type"],
                "date_time": r["date_time"], # Use date_time directly
                "venue_name": r["venue_name"],
                "venue_address": r["venue_address"], # Use venue_address directly
                "venue_category": r["venue_category"] # Add venue_category
            })
        return {"events": events}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
@app.get("/events/{event_id}")
def get_event_preview(event_id: str):
    with db() as con:
        cur = con.cursor()

        # Fetch event
        event = cur.execute("SELECT * FROM events WHERE event_id = ?", (event_id,)).fetchone()
        if not event:
            raise HTTPException(404, "Event not found")

        # Count attendees
        attendee_count = cur.execute(
            "SELECT COUNT(*) FROM event_enrollment WHERE event_id = ?",
            (event_id,)
        ).fetchone()[0]

        # Get latest uploaded image for event (if any)
        image_row = None
        try:
            image_row = cur.execute(
                "SELECT filename FROM event_images WHERE event_id = ? ORDER BY rowid DESC LIMIT 1",
                (event_id,)
            ).fetchone()
        except Exception:
            # Table might not exist yet
            image_row = None

    # Build response
    return {
        "event_id": event["event_id"],
        "title": event["title"],
        "description": event["description"],
        "venue_name": event["venue_name"],
        "venue_address": event["venue_address"],
        "venue_lat": event["venue_lat"],
        "venue_lon": event["venue_lon"],
        "venue_category": event["venue_category"],
        "type": event["type"],
        "date_time": event["date_time"],
        "capacity": event["capacity"],
        "tags": event["tags"],
        "attendees": attendee_count,
        "image_url": f"/static/uploads/{image_row['filename']}" if image_row else None,
    }
