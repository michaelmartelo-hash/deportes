# main.py
import os
import asyncio
import logging
from datetime import datetime, date, timezone
from zoneinfo import ZoneInfo
import math
import requests
from fastapi import FastAPI

# ---------------------------
# CONFIG / ENV
# ---------------------------
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("sports-notifier")

API_FOOTBALL_KEY = os.getenv("API_FOOTBALL_KEY")
API_TENNIS_KEY = os.getenv("API_TENNIS_KEY")
ODDS_API_KEY = os.getenv("ODDS_API_KEY")

TELEGRAM_TOKEN = os.getenv("TOKEN")
TELEGRAM_CHAT_ID = os.getenv("CHAT_ID")  # keep as string for requests

# timezone
COLOMBIA = ZoneInfo("America/Bogota")

# Top20 FIFA (filter selecciones) — NORMALIZADO
FIFA_TOP20 = {
    "argentina","francia","inglaterra","bélgica","brasil",
    "países bajos","portugal","españa","italia","croacia",
    "ee.uu.","colombia","méxico","marruecos","alemania",
    "suiza","uruguay","dinamarca","japón","senegal"
}

def norm(s):
    if not s:
        return ""
    return s.lower().replace("á","a").replace("é","e").replace("í","i").replace("ó","o").replace("ú","u").strip()

FIFA_TOP20 = set(norm(x) for x in FIFA_TOP20)

# Top10 ATP (simple last names / partials)
TOP10_ATP = {
    "djokovic","alcaraz","sinner","zverev","medvedev",
    "rune","rublev","ruud","tsitsipas","hurkacz"
}

def tennis_in_top10(name):
    n = norm(name)
    for p in TOP10_ATP:
        if p in n:
            return True
    return False

# ---------------------------
# UTIL: escape HTML for Telegram and chunk messages
# ---------------------------
def escape_html(s: str) -> str:
    if s is None:
        return ""
    return (s.replace("&","&amp;")
             .replace("<","&lt;")
             .replace(">","&gt;"))

TELEGRAM_MAX = 3900

def chunk_message(text):
    if len(text) <= TELEGRAM_MAX:
        return [text]
    parts = []
    start = 0
    while start < len(text):
        end = min(len(text), start + TELEGRAM_MAX)
        if end < len(text):
            nl = text.rfind("\n", start, end)
            if nl > start:
                parts.append(text[start:nl])
                start = nl + 1
                continue
        parts.append(text[start:end])
        start = end
    return parts

# ---------------------------
# Odds API helpers
# ---------------------------
def fetch_odds(sport_key):
    if not ODDS_API_KEY:
        return []
    url = f"https://api.the-odds-api.com/v4/sports/{sport_key}/odds"
    params = {"apiKey": ODDS_API_KEY, "regions": "us,eu,uk", "markets": "h2h", "dateFormat": "iso"}
    try:
        r = requests.get(url, params=params, timeout=10)
        if r.status_code != 200:
            logger.warning("Odds API returned status %s for %s: %s", r.status_code, sport_key, r.text[:200])
            return []
        return r.json()
    except Exception as e:
        logger.warning("Error fetching odds for %s: %s", sport_key, e)
        return []

def find_odds_for_match(odds_list, team_a, team_b, target_dt=None):
    if not odds_list:
        return None
    ta = norm(team_a)
    tb = norm(team_b)
    for ev in odds_list:
        home = norm(ev.get("home_team",""))
        away = norm(ev.get("away_team",""))
        if (ta and (ta in home or ta in away)) and (tb and (tb in home or tb in away)):
            try:
                commence = ev.get("commence_time")
                if commence and target_dt:
                    ev_dt = datetime.fromisoformat(commence.replace("Z","+00:00")).astimezone(COLOMBIA)
                    diff = abs((ev_dt - target_dt).total_seconds())
                    if diff > 60*60*24:
                        continue
            except Exception:
                pass
            return ev
    return None

def odds_to_probs(odds_event):
    if not odds_event:
        return {}
    try:
        bms = odds_event.get("bookmakers", [])
        for bm in bms:
            for market in bm.get("markets", []):
                if market.get("key") == "h2h":
                    outcomes = market.get("outcomes", [])
                    probs = {}
                    for o in outcomes:
                        name = o.get("name")
                        price = o.get("price")
                        if price and price > 0:
                            probs[name] = 1.0 / float(price)
                    s = sum(probs.values())
                    if s > 0:
                        for k in list(probs.keys()):
                            probs[k] = round(probs[k] / s * 100, 1)
                        return probs
    except Exception as e:
        logger.debug("odds_to_probs error: %s", e)
    return {}

# ---------------------------
# FOOTBALL: selecciones
# ---------------------------
def get_football_matches():
    logger.info("Fetching football fixtures (selecciones)...")
    if not API_FOOTBALL_KEY:
        logger.warning("No API_FOOTBALL_KEY configured")
        return []
    url = "https://v3.football.api-sports.io/fixtures"
    today = datetime.now(COLOMBIA).date().isoformat()
    params = {"date": today}
    headers = {"x-apisports-key": API_FOOTBALL_KEY}
    try:
        r = requests.get(url, headers=headers, params=params, timeout=12)
        logger.info("API-Football status: %s", r.status_code)
        if r.status_code != 200:
            logger.error("API-Football error: %s", r.text[:300])
            return []
        payload = r.json()
    except Exception as e:
        logger.error("API-Football request failed: %s", e)
        return []

    res = []
    odds_soccer = fetch_odds("soccer")

    for f in payload.get("response", []):
        try:
            home = f["teams"]["home"]["name"]
            away = f["teams"]["away"]["name"]

            # FILTRO CORREGIDO: Selecciones nacionales usando country
            home_nat = f["teams"]["home"].get("national", False)
            away_nat = f["teams"]["away"].get("national", False)

            if not home_nat and not away_nat:
                continue

            # adicional: validar si el país está en el top20
            home_c = norm(f["teams"]["home"].get("country", ""))
            away_c = norm(f["teams"]["away"].get("country", ""))

            if home_c not in FIFA_TOP20 and away_c not in FIFA_TOP20:
                continue

            kickoff_iso = f["fixture"]["date"]
            kickoff_dt = datetime.fromisoformat(kickoff_iso.replace("Z","+00:00")).astimezone(COLOMBIA)
            kickoff_txt = kickoff_dt.strftime("%Y-%m-%d %H:%M")

            matched = find_odds_for_match(odds_soccer, home, away, kickoff_dt)
            probs = odds_to_probs(matched) if matched else {}

            res.append({
                "home": home,
                "away": away,
                "kickoff": kickoff_txt,
                "probs": probs
            })
        except Exception:
            continue

    logger.info("Football (selecciones) found %d matches", len(res))
    return res

# ---------------------------
# TENNIS
# ---------------------------
def get_tennis_matches():
    logger.info("Fetching tennis matches from api-tennis.com (top10 filter)...")
    if not API_TENNIS_KEY:
        logger.warning("No API_TENNIS_KEY configured")
        return []
    url = "https://api-tennis.com/v1/matches"
    params = {"date": "today", "apikey": API_TENNIS_KEY}
    try:
        r = requests.get(url, params=params, timeout=10)
        logger.info("API-Tennis status: %s", r.status_code)
        if r.status_code != 200:
            logger.error("API-Tennis returned %s: %s", r.status_code, r.text[:300])
            return []
        payload = r.json()
    except Exception as e:
        logger.error("API-Tennis request failed: %s", e)
        return []

    res = []
    odds_tennis = fetch_odds("tennis")

    for m in payload.get("data", []):
        try:
            p1 = m.get("player1") or m.get("home") or ""
            p2 = m.get("player2") or m.get("away") or ""

            if tennis_in_top10(p1) or tennis_in_top10(p2):
                ts = m.get("time")
                try:
                    if isinstance(ts, (int, float)):
                        dt = datetime.fromtimestamp(int(ts), tz=timezone.utc).astimezone(COLOMBIA)
                    else:
                        dt = datetime.fromisoformat(str(ts)).astimezone(COLOMBIA)
                except Exception:
                    dt = None

                time_txt = dt.strftime("%Y-%m-%d %H:%M") if dt else "?"

                matched = find_odds_for_match(odds_tennis, p1, p2, dt)
                probs = odds_to_probs(matched) if matched else {}

                res.append({
                    "p1": p1,
                    "p2": p2,
                    "time": time_txt,
                    "probs": probs
                })
        except Exception:
            continue

    logger.info("Tennis top10 matches found: %d", len(res))
    return res

# ---------------------------
# UFC — mejora detección
# ---------------------------
def get_ufc_events():
    logger.info("Fetching MMA events (filter UFC)...")
    events = fetch_odds("mma_mixed_martial_arts")
    res = []
    today = datetime.now(COLOMBIA).date()

    for ev in events:
        try:
            title = ev.get("sport_title", "")
            # detectar UFC incluso si title dice "MMA" pero aparece organization
            if "ufc" not in title.lower() and "ufc" not in norm(ev.get("league", "")):
                continue

            commence = ev.get("commence_time")
            if not commence:
                continue

            ev_dt = datetime.fromisoformat(commence.replace("Z","+00:00")).astimezone(COLOMBIA)
            if ev_dt.date() != today:
                continue

            markets = ev.get("bookmakers", [])
            outcomes = []
            for bm in markets:
                for mk in bm.get("markets", []):
                    if mk.get("key") == "h2h":
                        outcomes = mk.get("outcomes", [])
                        break
                if outcomes:
                    break

            if len(outcomes) >= 2:
                f1 = outcomes[0].get("name")
                f2 = outcomes[1].get("name")
            else:
                f1 = ev.get("home_team")
                f2 = ev.get("away_team")

            probs = odds_to_probs(ev)
            res.append({
                "title": title,
                "time": ev_dt.strftime("%Y-%m-%d %H:%M"),
                "f1": f1,
                "f2": f2,
                "probs": probs
            })
        except Exception:
            continue

    logger.info("UFC events found: %d", len(res))
    return res[:5]

# ---------------------------
# BUILD REPORT
# ---------------------------
def build_report_text():
    now = datetime.now(COLOMBIA).strftime("%Y-%m-%d %H:%M")
    out = []
    out.append(f"📊 Reporte Deportivo — {now} (Colombia)\n")

    # Football
    football = get_football_matches()
    out.append("⚽ Partidos de selecciones (Top 20 FIFA):")
    if football:
        for m in football:
            probs = m.get("probs", {})
            prob_text = ""
            if probs:
                items = list(probs.items())
                if len(items) >= 2:
                    prob_text = f" — Prob: {items[0][1]}% / {items[1][1]}%"
            out.append(f"• {m['home']} vs {m['away']} — {m['kickoff']}{prob_text}")
    else:
        out.append("No hay partidos importantes hoy.")
    out.append("")

    # Tennis
    tennis = get_tennis_matches()
    out.append("🎾 Tenis — Top 10:")
    if tennis:
        for t in tennis:
            probs = t.get("probs", {})
            prob_text = ""
            if probs:
                items = list(probs.items())
                if len(items) >= 2:
                    prob_text = f" — Prob: {items[0][1]}% / {items[1][1]}%"
            out.append(f"• {t['p1']} vs {t['p2']} — {t['time']}{prob_text}")
    else:
        out.append("No hay partidos hoy del Top 10 o falla de la API.")
    out.append("")

    # UFC
    ufc = get_ufc_events()
    out.append("🥋 UFC — Principales peleas:")
    if ufc:
        for e in ufc:
            probs = e.get("probs", {})
            prob_text = ""
            if probs:
                items = list(probs.items())
                if len(items) >= 2:
                    prob_text = f" — Prob: {items[0][1]}% / {items[1][1]}%"
            out.append(f"• {e['f1']} vs {e['f2']} — {e['time']}{prob_text}")
    else:
        out.append("No hay eventos UFC hoy.")
    out.append("")

    out.append("_Probabilidades provistas por casas de apuestas cuando están disponibles._")
    return "\n".join(out)

# ---------------------------
# SEND TELEGRAM
# ---------------------------
def send_to_telegram_full(text):
    safe = escape_html(text)
    parts = chunk_message(safe)
    sent_any = False
    for p in parts:
        try:
            url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
            payload = {"chat_id": TELEGRAM_CHAT_ID, "text": p, "parse_mode": "HTML"}
            r = requests.post(url, json=payload, timeout=10)
            logger.info("Telegram status: %s - %s", r.status_code, r.text[:200])
            if r.status_code == 200:
                sent_any = True
        except Exception as e:
            logger.error("Error sending Telegram chunk: %s", e)
    return sent_any

# ---------------------------
# MAIN TASK
# ---------------------------
async def send_daily_report():
    try:
        logger.info("Generando reporte...")
        text = build_report_text()
        logger.info("Reporte generado, tamaño %d chars", len(text))
        ok = await asyncio.get_event_loop().run_in_executor(None, lambda: send_to_telegram_full(text))
        if ok:
            logger.info("Reporte enviado correctamente a Telegram.")
        else:
            logger.error("No se pudo enviar el reporte a Telegram.")
    except Exception as e:
        logger.exception("Error en send_daily_report: %s", str(e))

# ---------------------------
# FASTAPI
# ---------------------------
app = FastAPI()

@app.get("/run_report")
async def run_report():
    logger.info("/run_report llamado")
    asyncio.create_task(send_daily_report())
    return {"status": "Reporte enviado"}

@app.get("/")
def home():
    return {"status": "ok", "msg": "Sports Notifier Running"}

# ---------------------------
# ENTRYPOINT LOCAL
# ---------------------------
if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", 10000))
    uvicorn.run("main:app", host="0.0.0.0", port=port, log_level
