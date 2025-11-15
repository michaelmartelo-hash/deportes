# main.py (VERSIÓN CORREGIDA Y OPTIMIZADA PARA RENDER)

import os
import asyncio
import logging
from datetime import datetime, date
from zoneinfo import ZoneInfo
import requests
from dateutil import parser as date_parser
from fastapi import FastAPI
from telegram import Bot

# ---------------------------
# CONFIG ENV (Render)
# ---------------------------
API_FOOTBALL_KEY = os.getenv("API_FOOTBALL_KEY")
API_TENNIS_KEY = os.getenv("API_TENNIS_KEY")
ODDS_API_KEY = os.getenv("ODDS_API_KEY")

TOKEN = os.getenv("TOKEN")
CHAT_ID = int(os.getenv("CHAT_ID"))

COLOMBIA_TZ = "America/Bogota"
tz_col = ZoneInfo(COLOMBIA_TZ)

bot = Bot(token=TOKEN)
app = FastAPI()

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("sports-notifier")

# ---------------------------
# LIGAS
# ---------------------------
LEAGUE_IDS = {
    "Champions League": 2,
    "Premier League": 39,
    "LaLiga": 140,
    "Serie A": 135,
    "Bundesliga": 78,
    "Ligue 1": 61,
    "Amistosos Internacionales": 1,
    "Clasificatorias Copa Mundo": 10     # World Cup Qualifiers
}

# ---------------------------
# TOP TEN REAL
# ---------------------------
TOP10_TENNIS = {
    "djokovic", "alcaraz", "sinner", "medvedev", "zverev",
    "rune", "rublev", "ruud", "tsitsipas", "hurkacz"
}

# ---------------------------
# HELPERS
# ---------------------------
def normalize(name):
    if not name:
        return ""
    return name.lower().replace(".", "").strip()

def in_top10(name):
    """Detecta si un jugador está en el top10 usando fuzzy matching por apellidos."""
    n = normalize(name)
    for player in TOP10_TENNIS:
        if player in n:      # match parcial, funciona con "J. Sinner" o "SIN J."
            return True
    return False

def to_colombia(iso_dt_str):
    dt = date_parser.isoparse(iso_dt_str)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=ZoneInfo("UTC"))
    return dt.astimezone(tz_col)

def fmt_dt(dt):
    return dt.strftime("%Y-%m-%d %H:%M")

# ---------------------------
# FOOTBALL FIXTURES
# ---------------------------
def fetch_football_league(league_id, target_date):
    headers = {"x-apisports-key": API_FOOTBALL_KEY}
    url = "https://v3.football.api-sports.io/fixtures"
    params = {"league": league_id, "season": target_date.year, "date": target_date.isoformat()}

    try:
        r = requests.get(url, headers=headers, params=params, timeout=12)
        r.raise_for_status()
        return r.json().get("response", [])
    except:
        return []

def build_football_section(target_date):
    lines = []
    for league_name, lid in LEAGUE_IDS.items():
        fixtures = fetch_football_league(lid, target_date)
        for f in fixtures:
            home = f["teams"]["home"]["name"]
            away = f["teams"]["away"]["name"]
            kickoff = to_colombia(f["fixture"]["date"])
            lines.append(f"• {league_name}: {home} vs {away} — {fmt_dt(kickoff)}")
    return "\n".join(lines) if lines else "No hay partidos importantes hoy."

# ---------------------------
# TENIS — CORREGIDO (Sinner / Alcaraz detectados)
# ---------------------------
def fetch_tennis_odds():
    if not ODDS_API_KEY:
        return []
    url = "https://api.the-odds-api.com/v4/sports/tennis/odds"
    params = {
        "apiKey": ODDS_API_KEY,
        "regions": "eu,us,uk",
        "markets": "h2h",
        "dateFormat": "iso"
    }
    try:
        r = requests.get(url, params=params, timeout=10)
        if r.status_code != 200:
            return []
        return r.json()
    except:
        return []

def build_tennis_section(target_date):
    events = fetch_tennis_odds()
    lines = []

    for ev in events:
        try:
            dt = date_parser.isoparse(ev["commence_time"]).astimezone(tz_col)
            if dt.date() != target_date:
                continue

            home = ev.get("home_team")
            away = ev.get("away_team")
            if not home or not away:
                continue

            # ✔ fuzzy top10 matching
            if not (in_top10(home) or in_top10(away)):
                continue

            lines.append(f"• {home} vs {away} — {fmt_dt(dt)} (Top 10)")
        except:
            continue

    return "\n".join(lines) if lines else "Hoy no juegan jugadores del Top 10."

# ---------------------------
# UFC
# ---------------------------
def fetch_mma():
    if not ODDS_API_KEY:
        return []
    url = "https://api.the-odds-api.com/v4/sports/mma_mixed_martial_arts/odds"
    params = {
        "apiKey": ODDS_API_KEY,
        "regions": "us,eu",
        "markets": "h2h",
        "dateFormat": "iso"
    }
    try:
        r = requests.get(url, params=params, timeout=10)
        if r.status_code != 200:
            return []
        return r.json()
    except:
        return []

def build_ufc_section(target_date):
    events = fetch_mma()
    lines = []
    for ev in events:
        try:
            dt = date_parser.isoparse(ev["commence_time"]).astimezone(tz_col)
            if dt.date() != target_date:
                continue
            h = ev.get("home_team")
            a = ev.get("away_team")
            lines.append(f"• {h} vs {a} — {fmt_dt(dt)}")
        except:
            continue
    return "\n".join(lines) if lines else "Hoy no hay eventos UFC."

# ---------------------------
# FULL REPORT
# ---------------------------
def build_full_report():
    today = datetime.now(tz_col).date()

    return (
        f"📊 *Reporte Deportivo — {today}*\n\n"
        f"⚽ *Fútbol:*\n{build_football_section(today)}\n\n"
        f"🎾 *Tenis — Top 10:*\n{build_tennis_section(today)}\n\n"
        f"🥋 *UFC:*\n{build_ufc_section(today)}"
    )

# ---------------------------
# SEND TELEGRAM
# ---------------------------
async def send_message(text):
    loop = asyncio.get_event_loop()
    await loop.run_in_executor(None, lambda: bot.send_message(chat_id=CHAT_ID, text=text, parse_mode="Markdown"))

async def send_daily_report():
    try:
        msg = build_full_report()
        await send_message(msg)
        logger.info("Reporte enviado.")
    except Exception as e:
        logger.exception("Error enviando reporte: %s", e)

# ---------------------------
# FASTAPI ENDPOINTS
# ---------------------------
@app.get("/")
def home():
    return {"status": "ok"}

@app.get("/run_report")
async def run_report():
    await send_daily_report()
    return {"status": "sent"}
