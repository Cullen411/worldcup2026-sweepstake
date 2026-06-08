# ⚽ World Cup 2026 Sweepstake — Synology Setup Guide

## What you get
- **Public view**: Everyone can see the draw and tournament bracket at `http://YOUR-NAS-IP:8888`
- **Admin panel**: Password-protected at `http://YOUR-NAS-IP:8888/admin`
- **SQLite DB**: Single file `sweepstake.db` — no database server needed

---

## Installation on Synology DSM

### Step 1 – Install Python 3
1. Open **Package Center**
2. Search for **Python 3.x** and install it

### Step 2 – Copy the app to your NAS
Upload the entire `wc2026-sweepstake/` folder to a shared folder.  
Recommended path: `/volume1/web/wc2026-sweepstake/`

### Step 3 – Install dependencies (SSH into your NAS)

```bash
ssh admin@YOUR-NAS-IP
cd /volume1/web/wc2026-sweepstake
python3 -m pip install --user -r requirements.txt
```

### Step 4 – Set up Task Scheduler

1. Open **Control Panel → Task Scheduler**
2. Click **Create → Triggered Task → User-defined script**
3. Fill in:
   - **Task name**: `WC2026 Sweepstake`
   - **User**: `admin` (or your user)
   - **Event**: `Boot-up`
4. In the **Task Settings** tab, paste this into "Run command":

```bash
cd /volume1/web/wc2026-sweepstake
python3 app.py >> /volume1/web/wc2026-sweepstake/app.log 2>&1 &
```

5. Click **OK**

### Step 5 – Open firewall port (if needed)
1. **Control Panel → Security → Firewall**
2. Add a rule to allow TCP port `8888` from your LAN

---

## First run

Run manually to see your admin password:
```bash
cd /volume1/web/wc2026-sweepstake
python3 app.py
```

You'll see:
```
==================================================
  ⚽  World Cup 2026 Sweepstake
  🔐  Admin password: YourPassword
  🌐  Running at: http://0.0.0.0:8888
==================================================
```

**Save your admin password!** Or set a custom one (see below).

---

## Custom admin password (optional)

Edit `app.py` line 12 and replace the default:
```python
ADMIN_PASSWORD = "your-custom-password-here"
```

Or set it as an environment variable in the Task Scheduler command:
```bash
cd /volume1/web/wc2026-sweepstake
ADMIN_PASSWORD="MySecretPass" python3 app.py >> app.log 2>&1 &
```

---

## How to run a sweepstake

1. Go to `http://YOUR-NAS-IP:8888/admin` and log in
2. Add all participant names (up to 16)
3. Click **🎲 Run the Draw** — 2 teams assigned to each person randomly
4. Share `http://YOUR-NAS-IP:8888` with everyone
5. As matches happen, go to admin and update scores + status (Upcoming / Live / Completed)

---

## Files
```
wc2026-sweepstake/
├── app.py            # Main Flask app
├── filters.py        # Jinja2 helpers
├── requirements.txt  # Flask dependency
├── sweepstake.db     # SQLite DB (auto-created on first run)
├── SETUP.md          # This file
└── templates/
    ├── base.html     # Shared layout
    ├── index.html    # Public view
    ├── admin.html    # Admin panel
    └── login.html    # Admin login
```
