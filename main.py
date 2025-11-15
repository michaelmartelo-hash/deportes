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

# Top20 FIFA (filter selecciones)
FIFA_TOP20 = {
    "argentina","francia","inglaterra","bélgica","brasil",
    "países bajos","portugal","españa","italia","croacia",
    "ee.uu.","colombia","méxico","marruecos","alemania",
    "suiza","uruguay","dinamarca","japón","senegal"
}
# normalize helper
def norm(s):
    if not s:
        return ""
    return s.lower().strip()

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

TELEGRAM_MAX = 3900  # leave margin under 4096

def chunk_message(text):
    """Split into chunks safe for Telegram (approx TELEGRAM_MAX chars)."""
    if len(text) <= TELEGRAM_MAX:
        return [text]
    parts = []
    start = 0
    while start < len(text):
        end = min(len(text), start + TELEGRAM_MAX)
        # try to break at newline for nicer split
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
    """Match event from odds_list approximately by team names and datetime."""
    if not odds_list:
        return None
    ta = norm(team_a)
    tb = norm(team_b)
    for ev in odds_list:
        home = norm(ev.get("home_team",""))
        away = norm(ev.get("away_team",""))
        if (ta and (ta in home or ta in away)) and (tb and (tb in home or tb in away)):
            # optional date closeness
            try:
                commence = ev.get("commence_time")
                if commence and target_dt:
                    ev_dt = datetime.fromisoformat(commence.replace("Z","+00:00")).astimezone(COLOMBIA)
                    diff = abs((ev_dt - target_dt).total_seconds())
                    if diff > 60*60*24:  # >24h
                        continue
            except Exception:
                pass
            return ev
    return None

def odds_to_probs(odds_event):
    """Compute simple implied probabilities from first bookmaker h2h outcomes."""
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
                    # normalize
                    s = sum(probs.values())
                    if s > 0:
                        for k in list(probs.keys()):
                            probs[k] = round(probs[k] / s * 100, 1)
                        return probs
    except Exception as e:
        logger.debug("odds_to_probs error: %s", e)
    return {}

# ---------------------------
# FOOTBALL: selecciones (API-Football)
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
    odds_soccer = fetch_odds("soccer")  # general soccer odds
    for f in payload.get("response", []):
        try:
            home = f["teams"]["home"]["name"]
            away = f["teams"]["away"]["name"]
            # only national teams check: many fixtures include league teams - we filter by presence in FIFA_TOP20 set
            if norm(home) in FIFA_TOP20 or norm(away) in FIFA_TOP20:
                kickoff_iso = f["fixture"]["date"]
                kickoff_dt = datetime.fromisoformat(kickoff_iso.replace("Z","+00:00")).astimezone(COLOMBIA)
                kickoff_txt = kickoff_dt.strftime("%Y-%m-%d %H:%M")
                # try to find odds
                matched = find_odds_for_match(odds_soccer, home, away, kickoff_dt)
                probs = odds_to_probs(matched) if matched else {}
                res.append({
                    "home": home,
                    "away": away,
                    "kickoff": kickoff_txt,
                    "probs": probs
                })
        except Exception as e:
            logger.debug("Error parsing fixture: %s", e)
            continue
    logger.info("Football (selecciones) found %d matches", len(res))
    return res

# ---------------------------
# TENNIS: api-tennis.com (solo TOP10)
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
        logger.error("API-Tennis request failed (DNS/timeout likely): %s", e)
        return []

    res = []
    # try odds tennis events list
    odds_tennis = fetch_odds("tennis")
    for m in payload.get("data", []):
        try:
            p1 = m.get("player1") or m.get("home") or ""
            p2 = m.get("player2") or m.get("away") or ""
            # filter top10 fuzzy
            if tennis_in_top10(p1) or tennis_in_top10(p2):
                # time handling: api-tennis returns timestamp or datetime string; handle both
                ts = m.get("time")
                try:
                    if isinstance(ts, int) or isinstance(ts, float):
                        dt = datetime.fromtimestamp(int(ts), tz=timezone.utc).astimezone(COLOMBIA)
                    else:
                        # iso string?
                        dt = datetime.fromisoformat(str(ts)).astimezone(COLOMBIA)
                except Exception:
                    dt = None
                time_txt = dt.strftime("%Y-%m-%d %H:%M") if dt else "?"
                # find odds if any
                match_id = str(m.get("id") or "")
                matched = find_odds_for_match(odds_tennis, p1, p2, dt)
                probs = odds_to_probs(matched) if matched else {}
                res.append({
                    "p1": p1,
                    "p2": p2,
                    "time": time_txt,
                    "probs": probs
                })
        except Exception as e:
            logger.debug("Error parsing tennis match: %s", e)
            continue
    logger.info("Tennis top10 matches found: %d", len(res))
    return res

# ---------------------------
# UFC: odds API filtering only UFC events for today
# ---------------------------
def get_ufc_events():
    logger.info("Fetching MMA events (filter UFC)...")
    events = fetch_odds("mma_mixed_martial_arts")
    res = []
    today = datetime.now(COLOMBIA).date()
    for ev in events:
        try:
            title = ev.get("sport_title","")
            if "ufc" not in title.lower():
                continue
            commence = ev.get("commence_time")
            if not commence:
                continue
            ev_dt = datetime.fromisoformat(commence.replace("Z","+00:00")).astimezone(COLOMBIA)
            if ev_dt.date() != today:
                continue
            # build fight lines from outcomes
            markets = ev.get("bookmakers", [])
            # try to get fight names in outcomes
            outcomes = []
            for bm in markets:
                for mk in bm.get("markets", []):
                    if mk.get("key") == "h2h":
                        outcomes = mk.get("outcomes", [])
                        break
                if outcomes:
                    break
            # outcomes may include fighter names
            if len(outcomes) >= 2:
                f1 = outcomes[0].get("name")
                f2 = outcomes[1].get("name")
            else:
                # fallback: use event teams if present
                f1 = ev.get("home_team") or ev.get("teams", [None, None])[0]
                f2 = ev.get("away_team") or ev.get("teams", [None, None])[1]
            probs = odds_to_probs(ev)
            res.append({
                "title": title,
                "time": ev_dt.strftime("%Y-%m-%d %H:%M"),
                "f1": f1,
                "f2": f2,
                "probs": probs
            })
        except Exception as e:
            logger.debug("Error parsing mma event: %s", e)
            continue
    logger.info("UFC events found: %d", len(res))
    # limit to 5 main fights for summary
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
            probs = m.get("probs",{})
            prob_text = ""
            if probs:
                # choose keys by matching names
                home_prob = None
                away_prob = None
                for k,v in probs.items():
                    if norm(k) == norm(m["home"]):
                        home_prob = v
                    if norm(k) == norm(m["away"]):
                        away_prob = v
                # fallback: first two keys
                if home_prob is None or away_prob is None:
                    keys = list(probs.items())
                    if len(keys) >= 2:
                        home_prob = keys[0][1]
                        away_prob = keys[1][1]
                if home_prob is not None and away_prob is not None:
                    prob_text = f" — Prob: {home_prob}% / {away_prob}%"
            out.append(f"• {m['home']} vs {m['away']} — {m['kickoff']}{prob_text}")
    else:
        out.append("No hay partidos importantes hoy.")
    out.append("")

    # Tennis
    tennis = get_tennis_matches()
    out.append("🎾 Tenis — Top 10:")
    if tennis:
        for t in tennis:
            probs = t.get("probs",{})
            prob_text = ""
            if probs:
                # map by name fuzzy
                a = next(iter(probs.keys()), None)
                if a:
                    # try to find p1 and p2 in probs keys
                    p1prob = None
                    p2prob = None
                    for k,v in probs.items():
                        if tennis_in_top10(k) and tennis_in_top10(t['p1']) and norm(k) in norm(t['p1']):
                            p1prob = v
                        if tennis_in_top10(k) and tennis_in_top10(t['p2']) and norm(k) in norm(t['p2']):
                            p2prob = v
                    # fallback assign first two
                    if p1prob is None or p2prob is None:
                        items = list(probs.items())
                        if len(items) >= 2:
                            p1prob = items[0][1]
                            p2prob = items[1][1]
                    if p1prob is not None and p2prob is not None:
                        prob_text = f" — Prob: {p1prob}% / {p2prob}%"
            out.append(f"• {t['p1']} vs {t['p2']} — {t['time']}{prob_text}")
    else:
        out.append("No juegan jugadores del Top 10 hoy o Tennis API no disponible.")
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
            out.append(f"• {e.get('f1')} vs {e.get('f2')} — {e.get('time')}{prob_text}")
    else:
        out.append("No hay eventos UFC hoy.")
    out.append("")

    # footer
    out.append("_Probabilidades provistas por casas de apuestas cuando están disponibles._")
    text = "\n".join(out)
    return text

# ---------------------------
# SEND TO TELEGRAM (safe: escape + chunk)
# ---------------------------
def send_to_telegram_full(text):
    # escape HTML entities
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
# MAIN: background task
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
            logger.error("No se pudo enviar el reporte a Telegram (status != 200).")
    except Exception as e:
        # escape before logging to avoid HTML parsing in logs (not necessary but tidy)
        logger.exception("Error en send_daily_report: %s", str(e).replace("<","&lt;").replace(">","&gt;"))

# ---------------------------
# FASTAPI endpoints
# ---------------------------
app = FastAPI()

@app.get("/run_report")
async def run_report():
    logger.info("/run_report llamado")
    # run in background so HTTP returns quickly
    asyncio.create_task(send_daily_report())
    return {"status": "Reporte enviado"}

@app.get("/")
def home():
    return {"status":"ok", "msg":"Sports Notifier Running"}

# ---------------------------
# ENTRYPOINT (for local dev)
# ---------------------------
if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", 10000))
    uvicorn.run("main:app", host="0.0.0.0", port=port, log_level="info")
