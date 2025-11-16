# providers.py
import os
import requests
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
import logging

logger = logging.getLogger("providers")

# ENV VARS
API_FOOTBALL_KEY = os.getenv("API_FOOTBALL_KEY")           # legacy api-sports
FOOTBALL_DATA_API_KEY = os.getenv("FOOTBALL_DATA_API_KEY") # football-data.org
ODDS_API_KEY = os.getenv("ODDS_API_KEY")                   # The Odds API
API_TENNIS_KEY = os.getenv("API_TENNIS_KEY")
THESPORTSDB_API_KEY = os.getenv("THESPORTSDB_API_KEY")     # TheSportsDB

COLOMBIA = ZoneInfo("America/Bogota")

# Reuse normalization & top lists (kept similar to main)
def norm(s):
    if not s:
        return ""
    return s.lower().replace("á","a").replace("é","e").replace("í","i").replace("ó","o").replace("ú","u").strip()

FIFA_TOP20 = {
    "argentina","francia","inglaterra","bélgica","brasil",
    "países bajos","portugal","españa","italia","croacia",
    "ee.uu.","colombia","méxico","marruecos","alemania",
    "suiza","uruguay","dinamarca","japón","senegal"
}
FIFA_TOP20 = set(norm(x) for x in FIFA_TOP20)

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
# Odds helpers (The Odds API)
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
# FOOTBALL: football-data.org implementation (preferred)
# ---------------------------
def fetch_football_data_matches():
    if not FOOTBALL_DATA_API_KEY:
        logger.info("No FOOTBALL_DATA_API_KEY configured")
        return []
    base = "https://api.football-data.org/v4/"
    today = datetime.now(COLOMBIA).date().isoformat()
    url = base + f"matches?dateFrom={today}&dateTo={today}"
    headers = {"X-Auth-Token": FOOTBALL_DATA_API_KEY}
    try:
        r = requests.get(url, headers=headers, timeout=12)
        logger.info("football-data status: %s", r.status_code)
        if r.status_code != 200:
            logger.warning("football-data returned %s: %s", r.status_code, r.text[:300])
            return []
        payload = r.json()
    except Exception as e:
        logger.error("football-data request failed: %s", e)
        return []

    res = []
    odds_soccer = fetch_odds("soccer")

    for m in payload.get("matches", []):
        try:
            comp_name = m.get("competition", {}).get("name", "")
            home = m.get("homeTeam", {}).get("name", "")
            away = m.get("awayTeam", {}).get("name", "")
            kickoff_iso = m.get("utcDate")
            try:
                kickoff_dt = datetime.fromisoformat(kickoff_iso.replace("Z","+00:00")).astimezone(COLOMBIA)
                kickoff_txt = kickoff_dt.strftime("%Y-%m-%d %H:%M")
            except Exception:
                kickoff_txt = kickoff_iso

            home_country = norm(home)
            away_country = norm(away)

            if home_country not in FIFA_TOP20 and away_country not in FIFA_TOP20:
                continue

            matched = find_odds_for_match(odds_soccer, home, away, kickoff_dt)
            probs = odds_to_probs(matched) if matched else {}

            res.append({
                "home": home,
                "away": away,
                "kickoff": kickoff_txt,
                "probs": probs,
                "competition": comp_name
            })
        except Exception:
            continue

    logger.info("Football (football-data) found %d matches", len(res))
    return res

# ---------------------------
# FOOTBALL: api-sports fallback (legacy)
# ---------------------------
def fetch_api_sports_fixtures():
    if not API_FOOTBALL_KEY:
        logger.info("No API_FOOTBALL_KEY configured")
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
            home_nat = f["teams"]["home"].get("national", False)
            away_nat = f["teams"]["away"].get("national", False)
            if not home_nat and not away_nat:
                continue
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

    logger.info("Football (api-sports) found %d matches", len(res))
    return res

# Public wrapper: try football-data first, then fallback to api-sports
def get_football_matches():
    fd = fetch_football_data_matches()
    if fd:
        return fd
    return fetch_api_sports_fixtures()

# ---------------------------
# TENNIS (api-tennis)
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
                    # handle unix timestamp or iso
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
# UFC / MMA: combine TheOddsAPI and TheSportsDB
# ---------------------------
def fetch_thesportsdb_ufc_events():
    """Use TheSportsDB to fetch events for today (if key provided)."""
    if not THESPORTSDB_API_KEY:
        return []
    today = datetime.now(COLOMBIA).strftime("%Y-%m-%d")
    url = f"https://www.thesportsdb.com/api/v1/json/{THESPORTSDB_API_KEY}/eventsday.php?d={today}&s=UFC"
    try:
        r = requests.get(url, timeout=10)
        if r.status_code != 200:
            logger.warning("TheSportsDB returned %s: %s", r.status_code, r.text[:300])
            return []
        payload = r.json()
    except Exception as e:
        logger.warning("TheSportsDB request failed: %s", e)
        return []

    res = []
    events = payload.get("events") or []
    for e in events:
        try:
            # fields: strEvent, dateEvent, strTime, strVenue, etc.
            name = e.get("strEvent", "UFC Event")
            date_ev = e.get("dateEvent")
            time_ev = e.get("strTime")
            # Try to build datetime (assume event time is in local of event; best-effort)
            time_str = f"{date_ev} {time_ev}" if date_ev and time_ev else (date_ev or "")
            res.append({
                "title": name,
                "time_raw": time_str,
                "f1": e.get("strHomeTeam") or e.get("strEvent"),
                "f2": e.get("strAwayTeam") or "",
                "probs": {}
            })
        except Exception:
            continue
    return res

def get_ufc_events():
    logger.info("Fetching MMA events (filter UFC)...")
    res = []
    today = datetime.now(COLOMBIA).date()

    # 1) Try odds provider (The Odds API)
    events = fetch_odds("mma_mixed_martial_arts")
    for ev in events:
        try:
            title = ev.get("sport_title", "") or ev.get("title", "")
            # detect UFC by title or league
            if "ufc" not in title.lower() and "ufc" not in norm(ev.get("league", "") or ""):
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

    # 2) Complement with TheSportsDB if configured
    ts_events = fetch_thesportsdb_ufc_events()
    for te in ts_events:
        try:
            # Only add if not already present (by title/time)
            found = False
            for r0 in res:
                if norm(r0.get("title","")) == norm(te.get("title","")):
                    found = True
                    break
            if found:
                continue
            # parse time_raw best-effort
            time_txt = te.get("time_raw") or ""
            res.append({
                "title": te.get("title"),
                "time": time_txt,
                "f1": te.get("f1"),
                "f2": te.get("f2"),
                "probs": te.get("probs", {})
            })
        except Exception:
            continue

    logger.info("UFC events found: %d", len(res))
    return res[:10]
