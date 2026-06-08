import os
import json
import random
import sqlite3
import secrets
import urllib.request
import urllib.error
import time
from functools import wraps
from flask import Flask, render_template, request, redirect, url_for, session, jsonify, g
import hashlib

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", secrets.token_hex(32))

from filters import register_filters
register_filters(app)

ADMIN_PASSWORD  = os.environ.get("ADMIN_PASSWORD", "YOUR-PASSWORD")
FDORG_API_KEY   = os.environ.get("FDORG_API_KEY", "")   # football-data.org token
YOUTUBE_API_KEY = os.environ.get("YOUTUBE_API_KEY", "") # YouTube Data API v3
DB_PATH         = os.path.join(os.path.dirname(__file__), "sweepstake.db")
SITE_TITLE      = "World Cup 2026 SweepStake"

# Ports — run on both so LAN (8888) and external port-forward (8080) both work
PORTS = [int(p) for p in os.environ.get("PORTS", "8888,8080").split(",")]

# Simple in-process cache so we don't hammer the API on every page load
_cache = {}
CACHE_TTL = 300  # 5 minutes

def _cached(key, fn):
    entry = _cache.get(key)
    if entry and (time.time() - entry["ts"]) < CACHE_TTL:
        return entry["data"]
    try:
        data = fn()
        _cache[key] = {"data": data, "ts": time.time()}
        return data
    except Exception as e:
        app.logger.warning(f"Cache refresh failed for {key}: {e}")
        return entry["data"] if entry else None


def guess_browser(ua):
    ua = (ua or "").lower()
    if "edg/" in ua or " edge" in ua: return "Edge"
    if "opr/" in ua or "opera" in ua: return "Opera"
    if "chrome/" in ua and "chromium" not in ua and "edg/" not in ua and "opr/" not in ua: return "Chrome"
    if "firefox/" in ua: return "Firefox"
    if "safari/" in ua and "chrome/" not in ua and "chromium" not in ua: return "Safari"
    if "msie" in ua or "trident/" in ua: return "Internet Explorer"
    if "bot" in ua or "crawl" in ua or "spider" in ua: return "Bot"
    return "Other"


def guess_platform(ua):
    ua = (ua or "").lower()
    if "iphone" in ua or "ipad" in ua or "ipod" in ua: return "iOS"
    if "android" in ua: return "Android"
    if "windows" in ua: return "Windows"
    if "macintosh" in ua or "mac os x" in ua: return "macOS"
    if "linux" in ua and "android" not in ua: return "Linux"
    return "Other"


def _fdorg_get(path):
    """Call football-data.org v4 API."""
    url = f"https://api.football-data.org/v4{path}"
    req = urllib.request.Request(url, headers={"X-Auth-Token": FDORG_API_KEY})
    with urllib.request.urlopen(req, timeout=8) as resp:
        return json.loads(resp.read())

def fetch_live_matches():
    if not FDORG_API_KEY:
        return None
    return _cached("live_matches", lambda: _fdorg_get("/competitions/WC/matches?season=2026"))

def fetch_top_scorers():
    if not FDORG_API_KEY:
        return None
    return _cached("top_scorers", lambda: _fdorg_get("/competitions/WC/scorers?season=2026&limit=10"))

# ─── World Cup 2026 – all 48 qualified teams with FIFA April 2026 rankings ────
# Source: FIFA Men's World Ranking, 1 April 2026 + official draw (Dec 2025)
# Groups A-L (12 groups of 4). fifa_rank = global ranking.
# Seeded tier = top 24 (roughly top half) for draw purposes.
TEAMS = [
    # Group A
    {"name": "Mexico",              "flag": "🇲🇽", "group": "A", "fifa_rank": 15},
    {"name": "South Korea",         "flag": "🇰🇷", "group": "A", "fifa_rank": 25},
    {"name": "South Africa",        "flag": "🇿🇦", "group": "A", "fifa_rank": 60},
    {"name": "Czechia",             "flag": "🇨🇿", "group": "A", "fifa_rank": 41},
    # Group B
    {"name": "Canada",              "flag": "🇨🇦", "group": "B", "fifa_rank": 30},
    {"name": "Switzerland",         "flag": "🇨🇭", "group": "B", "fifa_rank": 19},
    {"name": "Qatar",               "flag": "🇶🇦", "group": "B", "fifa_rank": 35},
    {"name": "Bosnia & Herzegovina","flag": "🇧🇦", "group": "B", "fifa_rank": 65},
    # Group C
    {"name": "Brazil",              "flag": "🇧🇷", "group": "C", "fifa_rank": 6},
    {"name": "Morocco",             "flag": "🇲🇦", "group": "C", "fifa_rank": 8},
    {"name": "Haiti",               "flag": "🇭🇹", "group": "C", "fifa_rank": 83},
    {"name": "Scotland",            "flag": "🏴󠁧󠁢󠁳󠁣󠁴󠁿", "group": "C", "fifa_rank": 47},
    # Group D
    {"name": "USA",                 "flag": "🇺🇸", "group": "D", "fifa_rank": 16},
    {"name": "Paraguay",            "flag": "🇵🇾", "group": "D", "fifa_rank": 55},
    {"name": "Australia",           "flag": "🇦🇺", "group": "D", "fifa_rank": 26},
    {"name": "Türkiye",             "flag": "🇹🇷", "group": "D", "fifa_rank": 42},
    # Group E
    {"name": "Germany",             "flag": "🇩🇪", "group": "E", "fifa_rank": 10},
    {"name": "Ecuador",             "flag": "🇪🇨", "group": "E", "fifa_rank": 24},
    {"name": "Ivory Coast",         "flag": "🇨🇮", "group": "E", "fifa_rank": 33},
    {"name": "Curaçao",             "flag": "🇨🇼", "group": "E", "fifa_rank": 82},
    # Group F
    {"name": "Netherlands",         "flag": "🇳🇱", "group": "F", "fifa_rank": 7},
    {"name": "Japan",               "flag": "🇯🇵", "group": "F", "fifa_rank": 18},
    {"name": "Sweden",              "flag": "🇸🇪", "group": "F", "fifa_rank": 39},
    {"name": "Tunisia",             "flag": "🇹🇳", "group": "F", "fifa_rank": 40},
    # Group G
    {"name": "Belgium",             "flag": "🇧🇪", "group": "G", "fifa_rank": 9},
    {"name": "Iran",                "flag": "🇮🇷", "group": "G", "fifa_rank": 21},
    {"name": "Egypt",               "flag": "🇪🇬", "group": "G", "fifa_rank": 29},
    {"name": "New Zealand",         "flag": "🇳🇿", "group": "G", "fifa_rank": 85},
    # Group H
    {"name": "Spain",               "flag": "🇪🇸", "group": "H", "fifa_rank": 2},
    {"name": "Uruguay",             "flag": "🇺🇾", "group": "H", "fifa_rank": 17},
    {"name": "Saudi Arabia",        "flag": "🇸🇦", "group": "H", "fifa_rank": 57},
    {"name": "Cape Verde",          "flag": "🇨🇻", "group": "H", "fifa_rank": 69},
    # Group I
    {"name": "France",              "flag": "🇫🇷", "group": "I", "fifa_rank": 1},
    {"name": "Senegal",             "flag": "🇸🇳", "group": "I", "fifa_rank": 14},
    {"name": "Norway",              "flag": "🇳🇴", "group": "I", "fifa_rank": 44},
    {"name": "Iraq",                "flag": "🇮🇶", "group": "I", "fifa_rank": 63},
    # Group J
    {"name": "Argentina",           "flag": "🇦🇷", "group": "J", "fifa_rank": 3},
    {"name": "Austria",             "flag": "🇦🇹", "group": "J", "fifa_rank": 23},
    {"name": "Algeria",             "flag": "🇩🇿", "group": "J", "fifa_rank": 36},
    {"name": "Jordan",              "flag": "🇯🇴", "group": "J", "fifa_rank": 72},
    # Group K
    {"name": "Portugal",            "flag": "🇵🇹", "group": "K", "fifa_rank": 5},
    {"name": "Colombia",            "flag": "🇨🇴", "group": "K", "fifa_rank": 13},
    {"name": "DR Congo",            "flag": "🇨🇩", "group": "K", "fifa_rank": 51},
    {"name": "Uzbekistan",          "flag": "🇺🇿", "group": "K", "fifa_rank": 68},
    # Group L
    {"name": "England",             "flag": "🏴󠁧󠁢󠁥󠁮󠁧󠁿", "group": "L", "fifa_rank": 4},
    {"name": "Croatia",             "flag": "🇭🇷", "group": "L", "fifa_rank": 11},
    {"name": "Ghana",               "flag": "🇬🇭", "group": "L", "fifa_rank": 74},
    {"name": "Panama",              "flag": "🇵🇦", "group": "L", "fifa_rank": 53},
]

# Top 24 by FIFA rank = "seeded" pot (half the 48-team field)
SEEDED_TEAMS   = sorted([t for t in TEAMS if t["fifa_rank"] <= 30], key=lambda x: x["fifa_rank"])
UNSEEDED_TEAMS = sorted([t for t in TEAMS if t["fifa_rank"] > 30],  key=lambda x: x["fifa_rank"])

def seeded_draw(participants, teams_per_player=2):
    """
    Seeded sweepstake draw.
    Every participant gets one team from Pot 1 (FIFA top 30) guaranteed.
    Remaining slots come from the full pool minus already-assigned teams.
    When total_slots <= total teams available, no team repeats.
    When total_slots > total teams, extras wrap from unseeded pool.
    """
    count        = len(participants)
    total_slots  = count * teams_per_player
    total_avail  = len(TEAMS)
    extra_per    = max(0, teams_per_player - 1)
    extra_needed = count * extra_per

    # Build pot 1 (seeded) — one per player
    pot1 = sorted([t for t in TEAMS if t["fifa_rank"] <= 30], key=lambda x: x["fifa_rank"])
    seed_pool = pot1.copy()
    while len(seed_pool) < count:
        seed_pool += pot1.copy()
    seed_pool = seed_pool[:count]
    random.shuffle(seed_pool)

    # Build extra pool
    if total_slots <= total_avail:
        # Perfect fit or under — exclude seeded names, pull rest without repeats
        used = {t["name"] for t in seed_pool}
        remaining = [t for t in TEAMS if t["name"] not in used]
        random.shuffle(remaining)
        extra_pool = remaining[:extra_needed]
    else:
        # More slots than teams — allow repeats from unseeded, then seeded
        pot2 = sorted([t for t in TEAMS if t["fifa_rank"] > 30], key=lambda x: x["fifa_rank"])
        extra_pool = pot2.copy()
        while len(extra_pool) < extra_needed:
            extra_pool += (pot2.copy() if pot2 else pot1.copy())
        extra_pool = extra_pool[:extra_needed]
        random.shuffle(extra_pool)

    assignments = {}
    for i, p in enumerate(participants):
        player_teams = [seed_pool[i]["name"]]
        for j in range(extra_per):
            player_teams.append(extra_pool[i * extra_per + j]["name"])
        assignments[p["id"]] = player_teams
    return assignments


def seeded_draw_all(participants):
    """
    Special case of seeded draw that uses ALL 48 teams with zero repeats.
    Works for any number of participants — distributes as evenly as possible.
    e.g. 7 players: 6 get 7 teams, 1 gets 6 teams (all 48 used, none repeated).
    e.g. 8 players: all get exactly 6 teams.
    e.g. 10 players: all get 4 teams, 8 left over (so uses 40 of 48).
    Always guarantees: no repeats, seeded team per player.
    """
    count       = len(participants)
    total_avail = len(TEAMS)
    base_tpp    = total_avail // count      # minimum teams per player
    remainder   = total_avail % count       # number of players who get one extra

    # Sort all teams by rank for pot assignment
    pot1 = sorted([t for t in TEAMS if t["fifa_rank"] <= 30], key=lambda x: x["fifa_rank"])
    pot2 = sorted([t for t in TEAMS if t["fifa_rank"] > 30],  key=lambda x: x["fifa_rank"])

    # Give each player one seeded team from pot1
    seed_pool = pot1.copy()
    while len(seed_pool) < count:
        seed_pool += pot1.copy()
    seed_pool = seed_pool[:count]
    random.shuffle(seed_pool)

    # Remaining teams: everything not in the seeded assignment
    used = {t["name"] for t in seed_pool}
    remaining = [t for t in TEAMS if t["name"] not in used]
    random.shuffle(remaining)

    # Distribute: first `remainder` players get (base_tpp) extra teams,
    # the rest get (base_tpp - 1) extra teams
    assignments = {}
    extra_idx = 0
    for i, p in enumerate(participants):
        # How many total teams does this player get?
        player_total = base_tpp + (1 if i < remainder else 0)
        extras_needed = player_total - 1  # minus the seeded one
        player_teams = [seed_pool[i]["name"]]
        for _ in range(extras_needed):
            if extra_idx < len(remaining):
                player_teams.append(remaining[extra_idx]["name"])
                extra_idx += 1
        assignments[p["id"]] = player_teams

    return assignments


# Map football-data.org team names → our internal names
# football-data.org uses its own naming conventions; map everything that differs
FDORG_NAME_MAP = {
    # Confirmed API names from football-data.org v4
    "United States":              "USA",
    "Korea Republic":             "South Korea",
    "IR Iran":                    "Iran",
    # Bosnia variants
    "Bosnia-Herzegovina":         "Bosnia & Herzegovina",
    "Bosnia and Herzegovina":     "Bosnia & Herzegovina",
    "Bosnia & Herzegovina":       "Bosnia & Herzegovina",
    # Turkey/Türkiye
    "Turkey":                     "Türkiye",
    "Türkiye":                    "Türkiye",
    # Cape Verde
    "Cape Verde Islands": "Cape Verde",
    # DR Congo variants
    "Congo DR":                   "DR Congo",
    "Congo, DR":                  "DR Congo",
    "Democratic Republic of Congo": "DR Congo",
    # Ivory Coast variants
    "Côte d'Ivoire":              "Ivory Coast",
    "Cote d'Ivoire":             "Ivory Coast",
    # Other common variants
    "Czechia":                    "Czechia",
    "Czech Republic":             "Czechia",
    "Scotland":                   "Scotland",
    "Curacao":                    "Curaçao",
    "Curaçao":                    "Curaçao",
    "Paraguay":                   "Paraguay",
    "New Zealand":                "New Zealand",
}

ROUNDS = ["Group Stage", "Round of 16", "Quarter-Finals", "Semi-Finals", "Final"]

# ─── Helpers ──────────────────────────────────────────────────────────────────
def normalise_team(name):
    """Normalise football-data.org team names to our sweepstake names."""
    return FDORG_NAME_MAP.get(name, name)

def owner_of_team(participants_list, team_name):
    """Return the sweepstake participant who holds this team, or None."""
    for p in participants_list:
        try:
            teams = json.loads(p["teams"]) if isinstance(p["teams"], str) else p["teams"]
        except Exception:
            teams = []
        if team_name in teams:
            return p["name"]
    return None

# ─── Database helpers ─────────────────────────────────────────────────────────
def get_db():
    if "db" not in g:
        g.db = sqlite3.connect(DB_PATH)
        g.db.row_factory = sqlite3.Row
    return g.db

@app.teardown_appcontext
def close_db(e=None):
    db = g.pop("db", None)
    if db:
        db.close()

def init_db():
    with app.app_context():
        db = get_db()
        db.executescript("""
            CREATE TABLE IF NOT EXISTS participants (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL UNIQUE,
                teams TEXT NOT NULL DEFAULT '[]',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS matches (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                round TEXT NOT NULL,
                team_a TEXT,
                team_b TEXT,
                score_a INTEGER,
                score_b INTEGER,
                status TEXT DEFAULT 'upcoming',
                stage_order INTEGER DEFAULT 0,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS draw_done (
                id INTEGER PRIMARY KEY CHECK (id = 1),
                done INTEGER DEFAULT 0
            );
            INSERT OR IGNORE INTO draw_done (id, done) VALUES (1, 0);
            CREATE TABLE IF NOT EXISTS banner (
                id INTEGER PRIMARY KEY CHECK (id = 1),
                message TEXT DEFAULT '',
                active INTEGER DEFAULT 0,
                style TEXT DEFAULT 'info'
            );
            INSERT OR IGNORE INTO banner (id, message, active, style) VALUES (1, '', 0, 'info');
            CREATE TABLE IF NOT EXISTS reactions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                match_key TEXT NOT NULL,
                emoji TEXT NOT NULL,
                ts TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS access_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ts TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                path TEXT,
                ip TEXT,
                ua TEXT
            );
        """)
        db.commit()
        # Migrate: add teams_per_player if upgrading from older DB
        try:
            db.execute("ALTER TABLE draw_done ADD COLUMN teams_per_player INTEGER DEFAULT 2")
            db.commit()
        except Exception:
            pass
        # Migrate: add paid status to participants
        try:
            db.execute("ALTER TABLE participants ADD COLUMN paid INTEGER DEFAULT 0")
            db.commit()
        except Exception:
            pass  # column already exists
        # Migrate: add prize_pot
        try:
            db.execute("ALTER TABLE draw_done ADD COLUMN prize_pot REAL DEFAULT 0")
            db.commit()
        except Exception:
            pass

# ─── Access logging ──────────────────────────────────────────────────────────
@app.after_request
def log_access(response):
    try:
        path = request.path
        # Only log real page views, not API/static calls
        if not path.startswith('/api/') and not path.startswith('/static/'):
            ip = request.headers.get('X-Forwarded-For', request.remote_addr or '').split(',')[0].strip()
            ua = request.headers.get('User-Agent', '')[:200]
            with sqlite3.connect(DB_PATH) as conn:
                conn.execute(
                    "INSERT INTO access_log (path, ip, ua) VALUES (?,?,?)",
                    (path, ip, ua)
                )
    except Exception:
        pass
    return response

# ─── Auth ─────────────────────────────────────────────────────────────────────
def admin_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not session.get("admin"):
            return redirect(url_for("admin_login"))
        return f(*args, **kwargs)
    return decorated

# ─── Public routes ────────────────────────────────────────────────────────────
@app.route("/")
def index():
    db = get_db()
    participants = db.execute("SELECT * FROM participants ORDER BY name").fetchall()
    matches      = db.execute("SELECT * FROM matches ORDER BY stage_order, id").fetchall()
    draw_done    = db.execute("SELECT done FROM draw_done WHERE id=1").fetchone()["done"]
    prize_row  = db.execute("SELECT prize_pot FROM draw_done WHERE id=1").fetchone()
    prize_pot  = float(prize_row["prize_pot"] or 0) if prize_row else 0
    n_players  = len(participants)
    prizes = {
        "pot":    prize_pot,
        "first":  round(prize_pot * 0.70, 2),
        "second": round(prize_pot * 0.20, 2),
        "topscorer": round(prize_pot * 0.10, 2),
    }
    banner_row = db.execute("SELECT * FROM banner WHERE id=1").fetchone()
    banner = dict(banner_row) if banner_row else {"message":"","active":0,"style":"info"}
    return render_template("index.html",
        banner=banner,
        participants=participants,
        matches=matches,
        rounds=ROUNDS,
        draw_done=draw_done,
        teams=TEAMS,
        teams_map={t["name"]: t for t in TEAMS},
        seeded_names={t["name"] for t in SEEDED_TEAMS},
        site_title=SITE_TITLE,
        api_configured=bool(FDORG_API_KEY),
        flags_json=json.dumps({t["name"]: t["flag"] for t in TEAMS}),
        prizes=prizes,
        n_players=n_players,
    )

# ─── Live data API (called by frontend JS every 5 min) ───────────────────────
@app.route("/api/live")
def api_live():
    db       = get_db()
    parts    = db.execute("SELECT * FROM participants ORDER BY name").fetchall()
    parts    = [dict(p) for p in parts]
    for p in parts:
        try:
            p["teams"] = json.loads(p["teams"])
        except Exception:
            p["teams"] = []

    # ── Live matches from football-data.org ──
    live_data   = fetch_live_matches()
    api_matches = []
    if live_data and "matches" in live_data:
        for m in live_data["matches"]:
            home = normalise_team(m.get("homeTeam", {}).get("name", ""))
            away = normalise_team(m.get("awayTeam", {}).get("name", ""))
            score = m.get("score", {})
            full  = score.get("fullTime", {})
            api_matches.append({
                "home": home,
                "away": away,
                "score_home": full.get("home"),
                "score_away": full.get("away"),
                "status": m.get("status", ""),
                "round": m.get("stage", ""),
                "matchday": m.get("matchday"),
                "utcDate": m.get("utcDate", ""),
            })

    # ── Top scorers ──
    scorers_data = fetch_top_scorers()
    scorers = []
    if scorers_data and "scorers" in scorers_data:
        for s in scorers_data["scorers"][:10]:
            player  = s.get("player", {})
            team_nm = normalise_team(s.get("team", {}).get("name", ""))
            owner   = owner_of_team(parts, team_nm)
            scorers.append({
                "name":        player.get("name", ""),
                "nationality": player.get("nationality", ""),
                "team":        team_nm,
                "goals":       s.get("goals", 0),
                "assists":     s.get("assists", 0) or 0,
                "owner":       owner,
            })

    return jsonify({
        "api_configured": bool(FDORG_API_KEY),
        "cache_age": round(time.time() - _cache.get("live_matches", {}).get("ts", time.time())),
        "matches":  api_matches,
        "scorers":  scorers,
        "participants": parts,
        "groups":   {t["name"]: t.get("group","") for t in TEAMS},
    })

# ─── Admin routes ─────────────────────────────────────────────────────────────
@app.route("/admin/login", methods=["GET","POST"])
def admin_login():
    error = None
    if request.method == "POST":
        if request.form.get("password") == ADMIN_PASSWORD:
            session["admin"] = True
            return redirect(url_for("admin_panel"))
        error = "Invalid password"
    return render_template("login.html", error=error, site_title=SITE_TITLE)

@app.route("/admin/logout")
def admin_logout():
    session.pop("admin", None)
    return redirect(url_for("index"))

@app.route("/admin", methods=["GET"])
@admin_required
def admin_panel():
    db = get_db()
    participants = db.execute("SELECT * FROM participants ORDER BY name").fetchall()
    matches      = db.execute("SELECT * FROM matches ORDER BY stage_order, id").fetchall()
    draw_row2    = db.execute("SELECT done, teams_per_player, prize_pot FROM draw_done WHERE id=1").fetchone()
    draw_done    = draw_row2["done"]
    teams_per_player2 = draw_row2["teams_per_player"] if draw_row2["teams_per_player"] else 2
    prize_pot2   = float(draw_row2["prize_pot"] or 0)
    teams_map = {t["name"]: t for t in TEAMS}
    banner_row3 = db.execute("SELECT * FROM banner WHERE id=1").fetchone()
    banner3 = dict(banner_row3) if banner_row3 else {"message":"","active":0,"style":"info"}
    # Provide hashed versions of API keys for safe display in admin UI (no raw keys rendered)
    youtube_key_hash = hashlib.sha256(YOUTUBE_API_KEY.encode()).hexdigest() if YOUTUBE_API_KEY else ""
    fdorg_key_hash = hashlib.sha256(FDORG_API_KEY.encode()).hexdigest() if FDORG_API_KEY else ""

    return render_template("admin.html",
        participants=participants,
        matches=matches,
        rounds=ROUNDS,
        draw_done=draw_done,
        banner=banner3,
        teams_per_player=teams_per_player2,
        teams=TEAMS,
        teams_map=teams_map,
        seeded_names={t["name"] for t in SEEDED_TEAMS},
        site_title=SITE_TITLE,
        api_configured=bool(FDORG_API_KEY),
        fdorg_key_hash=fdorg_key_hash,
        youtube_configured=bool(YOUTUBE_API_KEY),
        youtube_key_hash=youtube_key_hash,
        prize_pot=prize_pot2,
        prizes={
            "pot": prize_pot2,
            "first": round(prize_pot2 * 0.70, 2),
            "second": round(prize_pot2 * 0.20, 2),
            "topscorer": round(prize_pot2 * 0.10, 2),
        },
    )

@app.route("/admin/participants", methods=["POST"])
@admin_required
def add_participant():
    name = request.form.get("name","").strip()
    if name:
        db = get_db()
        try:
            db.execute("INSERT INTO participants (name, teams) VALUES (?, '[]')", (name,))
            db.commit()
        except sqlite3.IntegrityError:
            pass
    return redirect(url_for("admin_panel"))

@app.route("/admin/participants/<int:pid>/delete", methods=["POST"])
@admin_required
def delete_participant(pid):
    db = get_db()
    db.execute("DELETE FROM participants WHERE id=?", (pid,))
    db.commit()
    return redirect(url_for("admin_panel"))

@app.route("/admin/draw", methods=["POST"])
@admin_required
def do_draw():
    db = get_db()
    participants = db.execute("SELECT * FROM participants ORDER BY name").fetchall()
    if not participants:
        return redirect(url_for("admin_panel"))
    try:
        teams_per_player = max(1, min(20, int(request.form.get("teams_per_player", 2))))
    except (ValueError, TypeError):
        teams_per_player = 2
    use_all = request.form.get("use_all_teams") == "1"

    # Check if this came from the live draw UI (pre-computed assignments)
    live_draw_json = request.form.get("live_draw_assignments")
    if live_draw_json:
        try:
            raw = json.loads(live_draw_json)
            # Keys are strings from JS — convert to int
            assignments = {int(k): v for k, v in raw.items()}
        except Exception:
            assignments = None
    else:
        assignments = None

    if assignments is None:
        if use_all:
            count = len(participants)
            assignments = seeded_draw_all(participants)
            teams_per_player = len(TEAMS) // count
        else:
            assignments = seeded_draw(participants, teams_per_player)

    for pid, teams in assignments.items():
        db.execute("UPDATE participants SET teams=? WHERE id=?", (json.dumps(teams), pid))
    db.execute("UPDATE draw_done SET done=1, teams_per_player=? WHERE id=1", (teams_per_player,))
    # Note: use_all is recalculated from teams_per_player on load, no extra column needed
    db.commit()
    return redirect(url_for("admin_panel"))

@app.route("/admin/draw/reset", methods=["POST"])
@admin_required
def reset_draw():
    db = get_db()
    db.execute("UPDATE participants SET teams='[]'")
    db.execute("UPDATE draw_done SET done=0 WHERE id=1")
    db.commit()
    return redirect(url_for("admin_panel"))

@app.route("/admin/matches", methods=["POST"])
@admin_required
def add_match():
    data = request.form
    db   = get_db()
    db.execute("""
        INSERT INTO matches (round, team_a, team_b, score_a, score_b, status, stage_order)
        VALUES (?,?,?,?,?,?,?)
    """, (
        data.get("round"),
        data.get("team_a"),
        data.get("team_b"),
        data.get("score_a") or None,
        data.get("score_b") or None,
        data.get("status","upcoming"),
        ROUNDS.index(data.get("round","Group Stage"))
    ))
    db.commit()
    return redirect(url_for("admin_panel"))

@app.route("/admin/matches/<int:mid>/update", methods=["POST"])
@admin_required
def update_match(mid):
    data = request.form
    db   = get_db()
    db.execute("""
        UPDATE matches SET score_a=?, score_b=?, status=?, updated_at=CURRENT_TIMESTAMP
        WHERE id=?
    """, (data.get("score_a") or None, data.get("score_b") or None,
          data.get("status","upcoming"), mid))
    db.commit()
    return jsonify({"ok": True})

@app.route("/admin/matches/<int:mid>/delete", methods=["POST"])
@admin_required
def delete_match(mid):
    db = get_db()
    db.execute("DELETE FROM matches WHERE id=?", (mid,))
    db.commit()
    return redirect(url_for("admin_panel"))

@app.route("/api/highlights")
def api_highlights():
    """Search YouTube for match highlights."""
    home  = request.args.get("home", "")
    away  = request.args.get("away", "")
    if not home or not away:
        return jsonify({"error": "missing teams"}), 400
    if not YOUTUBE_API_KEY:
        return jsonify({"error": "no_key"}), 200

    cache_key = f"yt_{home}_{away}"
    def fetch_yt():
        query = f"{home} vs {away} 2026 World Cup highlights"
        url = (
            "https://www.googleapis.com/youtube/v3/search"
            f"?part=snippet&q={urllib.request.quote(query)}"
            f"&type=video&maxResults=3&order=relevance"
            f"&key={YOUTUBE_API_KEY}"
        )
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=8) as resp:
            data = json.loads(resp.read())
        items = []
        for item in data.get("items", []):
            vid_id = item["id"].get("videoId", "")
            title  = item["snippet"].get("title", "")
            thumb  = item["snippet"].get("thumbnails", {}).get("medium", {}).get("url", "")
            channel= item["snippet"].get("channelTitle", "")
            if vid_id:
                items.append({"id": vid_id, "title": title,
                               "thumb": thumb, "channel": channel})
        return items

    # Cache for 30 minutes
    entry = _cache.get(cache_key)
    if entry and (time.time() - entry["ts"]) < 1800:
        return jsonify({"items": entry["data"], "cached": True})
    try:
        items = fetch_yt()
        _cache[cache_key] = {"data": items, "ts": time.time()}
        return jsonify({"items": items})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/admin/youtube-key", methods=["POST"])
@admin_required
def save_youtube_key():
    global YOUTUBE_API_KEY
    key = request.form.get("youtube_key", "").strip()
    # If no key provided, do not overwrite existing key (allows leaving field blank to keep current)
    if not key:
        return redirect(url_for("admin_panel"))
    YOUTUBE_API_KEY = key
    env_path = os.path.join(os.path.dirname(__file__), ".env")
    lines = []
    if os.path.exists(env_path):
        with open(env_path) as f:
            lines = [l for l in f.readlines() if not l.startswith("YOUTUBE_API_KEY=")]
    lines.append("YOUTUBE_API_KEY=" + key + "\n")
    with open(env_path, "w") as f:
        f.writelines(lines)
    return redirect(url_for("admin_panel"))


@app.route("/api/live-draw-prep")
@admin_required
def live_draw_prep():
    """Pre-compute a draw for the live draw UI without saving it."""
    db   = get_db()
    parts = db.execute("SELECT * FROM participants ORDER BY name").fetchall()
    if not parts:
        return jsonify({"error": "No participants"}), 400

    draw_row = db.execute("SELECT teams_per_player FROM draw_done WHERE id=1").fetchone()
    tpp      = draw_row["teams_per_player"] if draw_row else 2

    # Check use-all flag
    use_all = request.args.get("use_all","0") == "1"
    if use_all:
        assignments = seeded_draw_all(parts)
    else:
        assignments = seeded_draw(parts, tpp)

    # Convert to round-robin reveal sequence
    # Shuffle player order so draw sequence is unpredictable each time
    player_list = [dict(p) for p in parts]
    random.shuffle(player_list)
    max_teams   = max(len(v) for v in assignments.values())

    rounds = []
    for round_idx in range(max_teams):
        for player in player_list:
            pid = player["id"]
            team_list = assignments.get(pid, [])
            if round_idx < len(team_list):
                tname = team_list[round_idx]
                team_obj = next((t for t in TEAMS if t["name"] == tname), {})
                is_seeded = team_obj.get("fifa_rank", 99) <= 30
                rounds.append({
                    "player_id":   pid,
                    "player_name": player["name"],
                    "team":        tname,
                    "flag":        team_obj.get("flag", ""),
                    "fifa_rank":   team_obj.get("fifa_rank", 0),
                    "is_seeded":   is_seeded,
                    "round_idx":   round_idx,
                })

    # Also return full assignments so admin can save after draw
    final = {str(pid): teams for pid, teams in assignments.items()}

    return jsonify({
        "sequence": rounds,
        "assignments": final,
        "players": [{"id": p["id"], "name": p["name"]} for p in player_list],
    })


@app.route("/admin/toggle-paid/<int:pid>", methods=["POST"])
@admin_required
def toggle_paid(pid):
    db = get_db()
    row = db.execute("SELECT paid FROM participants WHERE id=?", (pid,)).fetchone()
    if row:
        new_val = 0 if row["paid"] else 1
        db.execute("UPDATE participants SET paid=? WHERE id=?", (new_val, pid))
        db.commit()
    return redirect(url_for("admin_panel"))


@app.route("/admin/banner", methods=["POST"])
@admin_required
def save_banner():
    message = request.form.get("message", "").strip()
    active  = 1 if request.form.get("active") == "1" else 0
    style   = request.form.get("style", "info")
    db = get_db()
    db.execute("UPDATE banner SET message=?, active=?, style=? WHERE id=1",
               (message, active, style))
    db.commit()
    return redirect(url_for("admin_panel"))

@app.route("/admin/prize-pot", methods=["POST"])
@admin_required
def save_prize_pot():
    try:
        pot = float(request.form.get("prize_pot", 0))
        pot = max(0, pot)
    except (ValueError, TypeError):
        pot = 0
    db = get_db()
    db.execute("UPDATE draw_done SET prize_pot=? WHERE id=1", (pot,))
    db.commit()
    return redirect(url_for("admin_panel"))

@app.route("/api/news")
def api_news():
    """Fetch and return World Cup news from Sky Sports RSS, cached 15 min."""
    import xml.etree.ElementTree as ET

    def fetch_news():
        import re as _re
        url = "https://news.google.com/rss/search?q=FIFA+World+Cup+2026&hl=en-GB&gl=GB&ceid=GB:en"
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=8) as resp:
            raw = resp.read()
        root = ET.fromstring(raw)
        items = []
        for item in root.findall(".//item")[:10]:
            title   = item.findtext("title", "").strip()
            link    = item.findtext("link", "").strip()
            pubdate = item.findtext("pubDate", "").strip()
            source  = item.find("source")
            src_name = source.text.strip() if source is not None else ""
            # Clean title — Google News appends " - Source Name"
            clean_title = title.rsplit(' - ', 1)[0].strip() if ' - ' in title else title
            items.append({
                "title":  clean_title,
                "source": src_name,
                "link":   link,
                "date":   pubdate,
            })
        # Sort newest first
        from email.utils import parsedate_to_datetime
        def parse_date(item):
            try: return parsedate_to_datetime(item["date"])
            except: return __import__('datetime').datetime.min
        items.sort(key=parse_date, reverse=True)
        return items

    data = _cached("google_news_v2", fetch_news)
    return jsonify({"items": data or [], "ok": bool(data)})

@app.route("/admin/api-key", methods=["POST"])
@admin_required
def save_api_key():
    """Persist the football-data.org key to an env file for restarts."""
    global FDORG_API_KEY
    key = request.form.get("api_key","").strip()
    # If no key provided, do not overwrite existing key
    if not key:
        return redirect(url_for("admin_panel"))
    FDORG_API_KEY = key
    env_path = os.path.join(os.path.dirname(__file__), ".env")
    lines = []
    if os.path.exists(env_path):
        with open(env_path) as f:
            lines = [l for l in f.readlines() if not l.startswith("FDORG_API_KEY=")]
    lines.append(f"FDORG_API_KEY={key}\n")
    with open(env_path, "w") as f:
        f.writelines(lines)
    _cache.clear()
    return redirect(url_for("admin_panel"))

@app.route("/api/team_goals")
def api_team_goals():
    """Return goals scored by each team from live data, mapped to sweepstake participants."""
    db = get_db()
    participants = [dict(p) for p in db.execute("SELECT * FROM participants ORDER BY name").fetchall()]
    for p in participants:
        try: p["teams"] = json.loads(p["teams"])
        except: p["teams"] = []

    # Fetch live match data for goal tallies
    live = fetch_live_matches()
    team_goals = {}  # team_name -> goals scored

    if live and "matches" in live:
        for m in live["matches"]:
            status = m.get("status", "")
            if status not in ("FINISHED", "IN_PLAY", "PAUSED"):
                continue
            score = m.get("score", {}).get("fullTime", {})
            home_goals = score.get("home") or 0
            away_goals = score.get("away") or 0
            home = normalise_team(m.get("homeTeam", {}).get("name", ""))
            away = normalise_team(m.get("awayTeam", {}).get("name", ""))
            if home:
                team_goals[home] = team_goals.get(home, 0) + home_goals
            if away:
                team_goals[away] = team_goals.get(away, 0) + away_goals

    # Build participant totals
    leaderboard = []
    for p in participants:
        teams_detail = []
        total = 0
        for t in p["teams"]:
            g = team_goals.get(t, 0)
            total += g
            flag = next((tm["flag"] for tm in TEAMS if tm["name"] == t), "")
            teams_detail.append({"name": t, "flag": flag, "goals": g})
        teams_detail.sort(key=lambda x: x["goals"], reverse=True)
        leaderboard.append({
            "player":  p["name"],
            "total":   total,
            "teams":   teams_detail,
        })

    leaderboard.sort(key=lambda x: x["total"], reverse=True)
    # Add rank
    for i, entry in enumerate(leaderboard):
        entry["rank"] = i + 1

    return jsonify({
        "leaderboard": leaderboard,
        "api_configured": bool(FDORG_API_KEY),
    })


@app.route("/api/reactions", methods=["GET","POST"])
def api_reactions():
    db = get_db()
    if request.method == "POST":
        data = request.get_json(silent=True) or {}
        match_key = data.get("match_key","")[:40]
        emoji = data.get("emoji","")[:4]
        ALLOWED = ["🔥","😱","💀","🎉","😬","🤝","⚽","🏆"]
        if match_key and emoji in ALLOWED:
            db.execute("INSERT INTO reactions (match_key, emoji) VALUES (?,?)", (match_key, emoji))
            db.commit()
        return jsonify({"ok": True})
    # GET — return counts per match_key
    rows = db.execute("""
        SELECT match_key, emoji, COUNT(*) as n
        FROM reactions GROUP BY match_key, emoji
    """).fetchall()
    out = {}
    for r in rows:
        mk = r["match_key"]
        if mk not in out: out[mk] = {}
        out[mk][r["emoji"]] = r["n"]
    return jsonify(out)


@app.route("/api/digest")
def api_digest():
    """Generate a WhatsApp-ready daily digest."""
    db    = get_db()
    parts = [dict(p) for p in db.execute("SELECT * FROM participants ORDER BY name").fetchall()]
    for p in parts:
        try: p["teams"] = json.loads(p["teams"])
        except: p["teams"] = []

    live_data = fetch_live_matches()
    matches   = []
    if live_data and "matches" in live_data:
        for m in live_data["matches"]:
            home  = normalise_team(m.get("homeTeam",{}).get("name",""))
            away  = normalise_team(m.get("awayTeam",{}).get("name",""))
            score = m.get("score",{}).get("fullTime",{})
            matches.append({
                "home": home, "away": away,
                "score_home": score.get("home"), "score_away": score.get("away"),
                "status": m.get("status",""), "utcDate": m.get("utcDate",""),
                "round": m.get("stage",""),
            })

    today = __import__('datetime').date.today().isoformat()
    yesterday = (__import__('datetime').date.today() - __import__('datetime').timedelta(days=1)).isoformat()

    finished_today = [m for m in matches if m["status"]=="FINISHED" and m["utcDate"][:10] in (today, yesterday)]
    upcoming_today = [m for m in matches if m["status"] in ("TIMED","SCHEDULED") and m["utcDate"][:10] == today]

    def owner_names(team):
        for p in parts:
            if team in p["teams"]: return p["name"]
        return None

    def flag(t):
        for tm in TEAMS:
            if tm["name"] == t: return tm["flag"]
        return ""

    # Build prize standings
    team_goals = {}
    for m in matches:
        if m["status"] in ("FINISHED","IN_PLAY"):
            h, a = m["home"], m["away"]
            gh = m["score_home"] or 0
            ga = m["score_away"] or 0
            team_goals[h] = team_goals.get(h,0) + gh
            team_goals[a] = team_goals.get(a,0) + ga

    standings = []
    for p in parts:
        total = sum(team_goals.get(t,0) for t in p["teams"])
        standings.append({"name": p["name"], "goals": total})
    standings.sort(key=lambda x: x["goals"], reverse=True)

    # Format BST time
    def bst(utc):
        if not utc: return ""
        from datetime import datetime, timezone, timedelta
        dt = datetime.fromisoformat(utc.replace("Z","+00:00"))
        bst_dt = dt.astimezone(timezone(timedelta(hours=1)))
        return bst_dt.strftime("%H:%M BST")

    lines = [f"⚽ *World Cup 2026 SweepStake — Daily Digest*"]
    lines.append(f"📅 {__import__('datetime').date.today().strftime('%A %d %B %Y')}")
    lines.append("")

    if finished_today:
        lines.append("*📋 Yesterday's Results:*")
        for m in finished_today:
            ho = owner_names(m["home"])
            ao = owner_names(m["away"])
            hchip = f"({ho})" if ho else ""
            achip = f"({ao})" if ao else ""
            lines.append(f"  {flag(m['home'])} {m['home']} {hchip} {m['score_home']}–{m['score_away']} {m['away']} {achip} {flag(m['away'])}")
        lines.append("")

    if upcoming_today:
        lines.append("*📆 Today's Fixtures:*")
        for m in upcoming_today:
            ho = owner_names(m["home"])
            ao = owner_names(m["away"])
            hchip = f"({ho})" if ho else ""
            achip = f"({ao})" if ao else ""
            lines.append(f"  {bst(m['utcDate'])} — {flag(m['home'])} {m['home']} {hchip} vs {m['away']} {achip} {flag(m['away'])}")
        lines.append("")

    lines.append("*🏆 Current Prize Standings (by team goals):*")
    for i, s in enumerate(standings[:7]):
        medal = ["🥇","🥈","🥉","4️⃣","5️⃣","6️⃣","7️⃣"][i]
        lines.append(f"  {medal} {s['name']} — {s['goals']} goals")

    lines.append("")
    lines.append(f"🌐 Full standings: {request.host_url}")

    return jsonify({"digest": "\n".join(lines)})


@app.route("/api/participant_stats")
def api_participant_stats():
    """Per-participant deep stats."""
    db    = get_db()
    parts = [dict(p) for p in db.execute("SELECT * FROM participants ORDER BY name").fetchall()]
    for p in parts:
        try: p["teams"] = json.loads(p["teams"])
        except: p["teams"] = []

    live_data = fetch_live_matches()
    matches   = []
    if live_data and "matches" in live_data:
        for m in live_data["matches"]:
            home  = normalise_team(m.get("homeTeam",{}).get("name",""))
            away  = normalise_team(m.get("awayTeam",{}).get("name",""))
            score = m.get("score",{}).get("fullTime",{})
            matches.append({
                "home": home, "away": away,
                "score_home": score.get("home"), "score_away": score.get("away"),
                "status": m.get("status",""), "utcDate": m.get("utcDate",""),
                "round": m.get("stage",""),
            })

    finished = [m for m in matches if m["status"] == "FINISHED"]

    def team_stats(team):
        played=won=drawn=lost=gf=ga=cs=biggest_win=0
        form=[]
        for m in finished:
            if m["home"] == team:
                gh,gar = m["score_home"] or 0, m["score_away"] or 0
                played+=1; gf+=gh; ga+=gar
                if gh > gar: won+=1; form.append("W"); biggest_win=max(biggest_win,gh-gar)
                elif gh == gar: drawn+=1; form.append("D")
                else: lost+=1; form.append("L")
                if gar == 0: cs+=1
            elif m["away"] == team:
                gh,gar = m["score_away"] or 0, m["score_home"] or 0
                played+=1; gf+=gh; ga+=gar
                if gh > gar: won+=1; form.append("W"); biggest_win=max(biggest_win,gh-gar)
                elif gh == gar: drawn+=1; form.append("D")
                else: lost+=1; form.append("L")
                if gar == 0: cs+=1
        return {"played":played,"won":won,"drawn":drawn,"lost":lost,
                "gf":gf,"ga":ga,"gd":gf-ga,"clean_sheets":cs,
                "form":form[-5:],"win_rate":round(won/played*100) if played else 0,
                "gpg":round(gf/played,1) if played else 0,
                "biggest_win":biggest_win}

    result = []
    for p in parts:
        totals = {"played":0,"won":0,"drawn":0,"lost":0,"gf":0,"ga":0,"gd":0,
                  "clean_sheets":0,"win_rate":0,"gpg":0}
        teams_detail = []
        all_form = []
        for t in p["teams"]:
            s = team_stats(t)
            teams_detail.append({"team":t,"flag":next((tm["flag"] for tm in TEAMS if tm["name"]==t),""),"stats":s})
            for k in ["played","won","drawn","lost","gf","ga","gd","clean_sheets"]:
                totals[k] += s[k]
            all_form += s["form"]
        if totals["played"]:
            totals["win_rate"] = round(totals["won"]/totals["played"]*100)
            totals["gpg"]      = round(totals["gf"]/totals["played"],1)
        totals["form"] = all_form[-5:]
        result.append({"player":p["name"],"totals":totals,"teams":teams_detail})

    result.sort(key=lambda x: (-x["totals"]["pts"] if "pts" in x["totals"] else -x["totals"]["won"]))
    return jsonify({"stats": result})


@app.route("/api/stats")
@admin_required
def api_stats():
    db = get_db()

    # Daily visits — last 14 days
    daily = db.execute("""
        SELECT DATE(ts) as day, COUNT(*) as visits
        FROM access_log
        WHERE ts >= DATE('now', '-14 days')
        AND path = '/'
        GROUP BY DATE(ts)
        ORDER BY day ASC
    """).fetchall()

    # Hourly distribution — all time, page views only
    hourly = db.execute("""
        SELECT CAST(strftime('%H', ts) AS INTEGER) as hour, COUNT(*) as visits
        FROM access_log
        WHERE path = '/'
        GROUP BY hour
        ORDER BY hour ASC
    """).fetchall()

    # Top paths
    paths = db.execute("""
        SELECT path, COUNT(*) as hits
        FROM access_log
        GROUP BY path
        ORDER BY hits DESC
        LIMIT 10
    """).fetchall()

    # Total unique IPs today
    today_stats = db.execute("""
        SELECT COUNT(*) as total, COUNT(DISTINCT ip) as unique_ips
        FROM access_log
        WHERE DATE(ts) = DATE('now') AND path = '/'
    """).fetchone()

    # Total unique IPs over the last 7 days
    week_stats = db.execute("""
        SELECT COUNT(DISTINCT ip) as unique_ips
        FROM access_log
        WHERE DATE(ts) >= DATE('now', '-7 days') AND path = '/'
    """).fetchone()

    # Browser / platform breakdown from User-Agent history
    ua_rows = db.execute("SELECT ua, COUNT(*) as hits FROM access_log GROUP BY ua").fetchall()
    browser_counts = {}
    platform_counts = {}
    for row in ua_rows:
        browser = guess_browser(row["ua"])
        platform = guess_platform(row["ua"])
        browser_counts[browser] = browser_counts.get(browser, 0) + row["hits"]
        platform_counts[platform] = platform_counts.get(platform, 0) + row["hits"]

    def top_items(counts, limit=5):
        items = sorted(counts.items(), key=lambda kv: kv[1], reverse=True)
        return [{"name": name, "hits": hits} for name, hits in items[:limit]]

    # All-time total
    alltime = db.execute("SELECT COUNT(*) as n FROM access_log WHERE path='/'").fetchone()

    return jsonify({
        "daily":         [dict(r) for r in daily],
        "hourly":        [dict(r) for r in hourly],
        "paths":         [dict(r) for r in paths],
        "today":         dict(today_stats),
        "week_unique":   week_stats["unique_ips"],
        "alltime":       alltime["n"],
        "top_browsers":  top_items(browser_counts),
        "top_platforms": top_items(platform_counts),
    })


# ─── Load .env on startup ─────────────────────────────────────────────────────
def load_env():
    global FDORG_API_KEY, YOUTUBE_API_KEY
    env_path = os.path.join(os.path.dirname(__file__), ".env")
    if os.path.exists(env_path):
        with open(env_path) as f:
            for line in f:
                line = line.strip()
                if "=" in line and not line.startswith("#"):
                    k, v = line.split("=", 1)
                    if k == "FDORG_API_KEY":
                        FDORG_API_KEY = v
                    if k == "YOUTUBE_API_KEY":
                        YOUTUBE_API_KEY = v

# ─── Entrypoint ───────────────────────────────────────────────────────────────
if __name__ == "__main__":
    load_env()
    init_db()
    print("=" * 55)
    print(f"  ⚽  {SITE_TITLE}")
    print(f"  🔐  Admin password : {ADMIN_PASSWORD}")
    print(f"  🌐  Ports          : {', '.join(str(p) for p in PORTS)}")
    if not FDORG_API_KEY:
        print("  ⚠️   No API key set — live data disabled.")
        print(f"       Add key at http://0.0.0.0:{PORTS[0]}/admin")
    else:
        print(f"  📡  Live data      : football-data.org ✅")
    print("=" * 55)
    import threading
    # Spin up a listener on each port; last one runs on the main thread
    for port in PORTS[:-1]:
        t = threading.Thread(
            target=lambda p=port: app.run(host="0.0.0.0", port=p, debug=False, use_reloader=False),
            daemon=True
        )
        t.start()
        print(f"  🌐  Also on          : http://0.0.0.0:{port}")
    app.run(host="0.0.0.0", port=PORTS[-1], debug=False, use_reloader=False)
