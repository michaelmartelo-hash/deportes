# main.py
import os
import asyncio
import logging
from datetime import datetime, date
from zoneinfo import ZoneInfo

import requests
from dateutil import parser as date_parser
from fastapi import FastAPI
from telegram import Bot
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

# ---------------------------
# CONFIG desde ENV (Render)
# ---------------------------
API_FOOTBALL_KEY = os.getenv("API_FOOTBALL_KEY")
API_TENNIS_KEY = os.getenv("API_TENNIS_KEY")  # opcional, no se usa intensamente aquí
ODDS_API_KEY = os.getenv("ODDS_API_KEY")

TOKEN = os.getenv("TOKEN")
CHAT_ID = int(os.getenv("CHAT_ID"))

# Timezone
COLOMBIA_TZ = "America/Bogota"
tz_col = ZoneInfo(COLOMBIA_TZ)

# Inicializar
bot = Bot(token=TOKEN)
app = FastAPI()
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("sports-notifier")

# ---------------------------
# CONFIG LIGAS (API-Football league IDs)
# ---------------------------
LEAGUE_IDS = {
    "Champions League": 2,
    "Premier League": 39,
    "LaLiga": 140,
    "Serie A": 135,
    "Bundesliga": 78,
    "Ligue 1": 61
}

# Top10 ATP (para filtrar tenis)
TOP10_TENNIS = {
    "Novak Djokovic","Carlos Alcaraz","Jannik Sinner","Daniil Medvedev",
    "Alexander Zverev","Holger Rune","Andrey Rublev","Casper Ruud",
    "Stefanos Tsitsipas","Hubert Hurkacz"
}

# ---------------------------
# HELPERS
# ---------------------------
def to_colombia(iso_dt_str):
    """Convierte ISO datetime (o datetime) a tz Colombia y devuelve objeto datetime"""
    if not iso_dt_str:
        return None
    if isinstance(iso_dt_str, str):
        dt = date_parser.isoparse(iso_dt_str)
    else:
        dt = iso_dt_str
    if dt.tzinfo is None:
        # asumir UTC si no tiene tz
        dt = dt.replace(tzinfo=ZoneInfo("UTC"))
    return dt.astimezone(tz_col)

def fmt_dt_col(dt):
    if dt is None:
        return "hora-desconocida"
    return dt.strftime("%Y-%m-%d %H:%M")

def safe_get(d, *keys, default=None):
    cur = d
    try:
        for k in keys:
            cur = cur.get(k, {})
        return cur or default
    except Exception:
        return default

# ---------------------------
# API-Football: fixtures por liga + fecha
# ---------------------------
def fetch_football_fixtures_for_league(league_id, target_date: date):
    headers = {"x-apisports-key": API_FOOTBALL_KEY} if API_FOOTBALL_KEY else {}
    url = "https://v3.football.api-sports.io/fixtures"
    params = {"league": league_id, "season": target_date.year, "date": target_date.isoformat()}
    try:
        r = requests.get(url, headers=headers, params=params, timeout=15)
        r.raise_for_status()
        data = r.json()
        return data.get("response", [])
    except Exception as e:
        logger.warning("Error fetching fixtures league %s: %s", league_id, e)
        return []

# ---------------------------
# The Odds API: obtener odds por deporte
# ---------------------------
def fetch_odds_for_sport(sport_key, date_from=None, date_to=None):
    if not ODDS_API_KEY:
        return []
    url = f"https://api.the-odds-api.com/v4/sports/{sport_key}/odds"
    params = {
        "apiKey": ODDS_API_KEY,
        "regions": "eu,us,uk",
        "markets": "h2h",  # head-to-head
        "dateFormat": "iso"
    }
    if date_from:
        params["dateFormat"] = "iso"
    try:
        r = requests.get(url, params=params, timeout=15)
        if r.status_code != 200:
            logger.warning("Odds API returned %s for sport %s", r.status_code, sport_key)
            return []
        return r.json()
    except Exception as e:
        logger.warning("Error fetching odds for %s: %s", sport_key, e)
        return []

def find_matching_odds_for_match(odds_list, team_a, team_b, target_dt):
    """
    Intenta encontrar la entrada de odds_list cuyo home/away coincida con los equipos y la fecha.
    Retorna el primer match con probabilidades (bookmakers) o None.
    """
    if not odds_list:
        return None
    ta = team_a.lower()
    tb = team_b.lower()
    for ev in odds_list:
        # comparar por equipos (hay mucha variedad en nombres, tratamos de aproximar)
        ev_teams = [t.lower() for t in ev.get("bookmakers", []) and ev.get("home_team","") and [ev.get("home_team",""), ev.get("away_team","")] or []]
        # The Odds API v4 returns fields: 'home_team','away_team','commence_time'
        home = ev.get("home_team","").lower()
        away = ev.get("away_team","").lower()
        if (ta in home or ta in away or tb in home or tb in away) and (ta in home+away or tb in home+away):
            # opcional: check datetime closeness (±12h)
            try:
                commence = date_parser.isoparse(ev.get("commence_time"))
                if target_dt:
                    dt_diff = abs((commence - target_dt).total_seconds())
                    if dt_diff > 60 * 60 * 24:  # si difiere > 24h, saltar
                        continue
            except Exception:
                pass
            return ev
    return None

def odds_to_probs_from_bookmakers(odds_event):
    """
    Extrae probabilidades implícitas promedio a partir de bookmakers (h2h).
    Retorna dict {'home':p, 'away':p, 'draw':p?}
    """
    if not odds_event:
        return {}
    markets = odds_event.get("bookmakers", [])
    invs = {}
    # recorrer bookmakers y sus mercados
    for bm in markets:
        for market in bm.get("markets", []):
            if market.get("key") != "h2h":
                continue
            for outcome in market.get("outcomes", []):
                name = outcome.get("name")
                price = outcome.get("price")
                if not name or price is None:
                    continue
                key = name.lower()
                invs.setdefault(key, []).append(1.0 / float(price) if float(price) > 0 else 0.0)
    # promediar y normalizar
    probs = {}
    for k, vals in invs.items():
        if vals:
            probs[k] = sum(vals) / len(vals)
    s = sum(probs.values())
    if s > 0:
        for k in probs:
            probs[k] = probs[k] / s
    return probs

# ---------------------------
# Construir reporte fútbol del día
# ---------------------------
def build_football_section(target_date: date):
    lines = []
    odds_soccer = fetch_odds_for_sport("soccer")  # intento general
    for league_name, lid in LEAGUE_IDS.items():
        fixtures = fetch_football_fixtures_for_league(lid, target_date)
        for f in fixtures:
            fixture_info = f.get("fixture", {})
            teams = f.get("teams", {})
            home = teams.get("home", {}).get("name")
            away = teams.get("away", {}).get("name")
            kickoff_iso = fixture_info.get("date")
            kickoff_dt = to_colombia(kickoff_iso)
            kickoff_txt = fmt_dt_col(kickoff_dt)
            # intentar obtener probabilidades desde odds
            matched = find_matching_odds_for_match(odds_soccer, home or "", away or "", date_parser.isoparse(fixture_info.get("date")) if fixture_info.get("date") else None)
            market_probs = odds_to_probs_from_bookmakers(matched) if matched else {}
            # modelo fallback: si no hay market_probs, prob 50/50 (o se podría mejorar con Elo)
            if market_probs:
                # map keys to 'home'/'away' if possible
                # intentar encontrar quien es home en market probs (bookmakers usan nombres de equipos)
                # simplificamos: mostramos el primer bookmaker h2h como referencia
                prob_text = ", ".join([f"{k}: {round(v*100,1)}%" for k,v in market_probs.items()])
            else:
                prob_text = "Probabilidades no disponibles."
            lines.append(f"• {league_name}: {home} vs {away} — {kickoff_txt} (Odds: {prob_text})")
    if not lines:
        return "No hay partidos importantes hoy."
    return "\n".join(lines)

# ---------------------------
# Tenis: buscar eventos tenis top10 via The Odds API (si disponible)
# ---------------------------
def build_tennis_section(target_date: date):
    odds_tennis = fetch_odds_for_sport("tennis")
    lines = []
    for ev in odds_tennis:
        try:
            commence = ev.get("commence_time")
            ev_dt = date_parser.isoparse(commence)
            ev_dt_col = ev_dt.astimezone(tz_col)
            if ev_dt_col.date() != target_date:
                continue
            home = ev.get("home_team") or ev.get("teams", [None, None])[0]
            away = ev.get("away_team") or ev.get("teams", [None, None])[1]
            if not home or not away:
                continue
            # filtrar top10
            if (home in TOP10_TENNIS) or (away in TOP10_TENNIS):
                # intentar probabilidades
                m = find_matching_odds_for_match([ev], home, away, ev_dt)
                probs = odds_to_probs_from_bookmakers(m) if m else {}
                prob_text = ", ".join([f"{k}: {round(v*100,1)}%" for k,v in probs.items()]) if probs else "Odds no disponibles"
                lines.append(f"• {home} vs {away} — {fmt_dt_col(ev_dt_col)} ({prob_text})")
        except Exception:
            continue
    if not lines:
        return "Hoy no juegan jugadores del Top 10."
    return "\n".join(lines)

# ---------------------------
# UFC: buscar eventos via The Odds API (mma_mixed_martial_arts)
# ---------------------------
def build_ufc_section(target_date: date):
    odds_mma = fetch_odds_for_sport("mma_mixed_martial_arts")
    main_event_lines = []
    # The Odds API returns lists of events; buscamos los del día
    for ev in odds_mma:
        try:
            commence = ev.get("commence_time")
            ev_dt = date_parser.isoparse(commence)
            ev_dt_col = ev_dt.astimezone(tz_col)
            if ev_dt_col.date() != target_date:
                continue
            # obtener peleas principales: la API estructura por 'bookmakers' y 'teams' (puede variar)
            home = ev.get("home_team") or ev.get("teams",[None, None])[0]
            away = ev.get("away_team") or ev.get("teams",[None, None])[1]
            # simplificar: listamos evento y hora
            m = find_matching_odds_for_match([ev], home or "", away or "", ev_dt)
            probs = odds_to_probs_from_bookmakers(m) if m else {}
            prob_text = ", ".join([f"{k}: {round(v*100,1)}%" for k,v in probs.items()]) if probs else "Odds no disponibles"
            main_event_lines.append(f"• {home} vs {away} — {fmt_dt_col(ev_dt_col)} ({prob_text})")
        except Exception:
            continue
    if not main_event_lines:
        return "Hoy no hay eventos UFC/MMA."
    # limitar a 5 peleas principales (si hay muchas)
    return "\n".join(main_event_lines[:5])

# ---------------------------
# Construir mensaje total
# ---------------------------
def build_full_report():
    today = datetime.now(tz_col).date()
    header = f"📊 *Reporte Deportivo* — {today.strftime('%Y-%m-%d')}\n\n"
    football = build_football_section(today)
    tennis = build_tennis_section(today)
    ufc = build_ufc_section(today)
    footer = "\n\n_Recuerda: probabilidades provistas por casas de apuestas cuando están disponibles._"
    msg = (
        f"{header}"
        f"⚽ *Fútbol (ligas seleccionadas):*\n{football}\n\n"
        f"🎾 *Tenis (Top 10):*\n{tennis}\n\n"
        f"🥋 *UFC / MMA:*\n{ufc}\n\n"
        f"{footer}"
    )
    return msg

# ---------------------------
# Envío por Telegram (no bloqueante)
# ---------------------------
async def send_message_telegram(text: str):
    loop = asyncio.get_event_loop()
    try:
        await loop.run_in_executor(None, lambda: bot.send_message(chat_id=CHAT_ID, text=text, parse_mode="Markdown"))
        logger.info("Mensaje enviado por Telegram.")
    except Exception as e:
        logger.exception("Error enviando mensaje Telegram: %s", e)

# ---------------------------
# Función principal que arma y manda el reporte
# ---------------------------
async def send_daily_report():
    try:
        logger.info("Generando reporte...")
        report = build_full_report()
        await send_message_telegram(report)
    except Exception as e:
        logger.exception("Error en send_daily_report: %s", e)

# ---------------------------
# Scheduler: solo a las horas deseadas (America/Bogota)
# ---------------------------
scheduler = AsyncIOScheduler()

def start_scheduler():
    tz = COLOMBIA_TZ
    times = [(8,0), (14,0), (16,30), (20,0)]
    for h,m in times:
        scheduler.add_job(send_daily_report, trigger=CronTrigger(hour=h, minute=m, timezone=tz), name=f"report_{h}_{m}")
    scheduler.start()
    logger.info("Scheduler iniciado con jobs: %s", times)

# ---------------------------
# FastAPI endpoints
# ---------------------------
@app.get("/")
def home():
    return {"status":"ok", "message":"Sports Notifier Bot Running"}

@app.get("/run_report")
async def run_report():
    await send_daily_report()
    return {"status":"sent"}

@app.on_event("startup")
async def on_startup():
    # arrancar scheduler
    start_scheduler()
    logger.info("App startup complete.")

# ---------------------------
# main para desarrollo local
# ---------------------------
if __name__ == "__main__":
    import uvicorn
    start_scheduler()
    uvicorn.run("main:app", host="0.0.0.0", port=8000)
