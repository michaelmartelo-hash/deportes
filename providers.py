import os
import requests
import logging
from datetime import datetime
from zoneinfo import ZoneInfo

log = logging.getLogger("providers")

# ============================
# ENV VARIABLES
# ============================
FOOTBALL_DATA_API_KEY = os.getenv("FOOTBALL_DATA_API_KEY")
API_FOOTBALL_KEY = os.getenv("API_FOOTBALL_KEY")
API_TENNIS_KEY = os.getenv("API_TENNIS_KEY")   # api-tennis
THE_SPORTS_DB_KEY = os.getenv("THESPORTSDB_KEY")  # UFC

# Zona horaria Colombia
COL_TZ = ZoneInfo("America/Bogota")


# ----------------------------------------------------------
# FOOTBALL (modo amplio: sin filtros de liga/selecciones)
# ----------------------------------------------------------
def get_football_matches():
    matches_output = []

    today_utc = datetime.now(ZoneInfo("UTC")).date()

    # ===== Source 1: football-data.org =====
    try:
        headers = {"X-Auth-Token": FOOTBALL_DATA_API_KEY}
        r = requests.get("https://api.football-data.org/v4/matches", headers=headers, timeout=20)
        log.info(f"football-data status: {r.status_code}")

        data = r.json()
        log.info(f"football-data raw matches: {len(data.get('matches', []))}")

        for m in data.get("matches", []):
            utc_str = m.get("utcDate")
            if not utc_str:
                continue
            match_dt = datetime.fromisoformat(utc_str.replace("Z", "+00:00"))
            if match_dt.date() != today_utc:
                continue
            home = m["homeTeam"]["name"]
            away = m["awayTeam"]["name"]
            comp = m["competition"]["name"]
            matches_output.append(
                f"⚽ {home} vs {away}\n   {comp} - {match_dt.astimezone(COL_TZ).strftime('%I:%M %p')}"
            )
    except Exception as e:
        log.error(f"football-data error: {e}")

    # ===== Source 2: api-football =====
    try:
        url = "https://v3.football.api-sports.io/fixtures?date=" + str(today_utc)
        headers = {"x-apisports-key": API_FOOTBALL_KEY}
        r = requests.get(url, headers=headers, timeout=20)
        log.info(f"API-Football status: {r.status_code}")

        data = r.json()
        log.info(f"api-football raw matches: {len(data.get('response', []))}")

        for f in data.get("response", []):
            fixture = f.get("fixture", {})
            teams = f.get("teams", {})
            utc_str = fixture.get("date")
            if not utc_str:
                continue
            match_dt = datetime.fromisoformat(utc_str.replace("Z", "+00:00"))
            if match_dt.date() != today_utc:
                continue
            home = teams.get("home", {}).get("name")
            away = teams.get("away", {}).get("name")
            league = f.get("league", {}).get("name")
            matches_output.append(
                f"⚽ {home} vs {away}\n   {league} - {match_dt.astimezone(COL_TZ).strftime('%I:%M %p')}"
            )

    except Exception as e:
        log.error(f"api-football error: {e}")

    return matches_output


# ----------------------------------------------------------
# TENNIS (modo amplio → sin filtrar Top10, sin filtros fuertes)
# ----------------------------------------------------------
def get_tennis_matches():
    matches_out = []

    try:
        url = f"https://api.api-tennis.com/tennis/?method=get_events&APIkey={API_TENNIS_KEY}"
        log.info("Fetching tennis matches from api.api-tennis.com (wide mode)...")

        r = requests.get(url, timeout=20)
        log.info(f"API-Tennis status: {r.status_code}")

        data = r.json()
        events = data.get("result", [])
        log.info(f"API-Tennis raw events count: {len(events)}")

        today_col = datetime.now(COL_TZ).date()

        for ev in events:
            try:
                p1 = ev.get("event_first_player")
                p2 = ev.get("event_second_player")
                time_str = ev.get("event_time")
                date_str = ev.get("event_date")
                tour = ev.get("event_tournament")

                if not date_str or not time_str:
                    continue

                dt = datetime.strptime(f"{date_str} {time_str}", "%Y-%m-%d %H:%M:%S")
                dt = dt.replace(tzinfo=ZoneInfo("UTC")).astimezone(COL_TZ)

                if dt.date() != today_col:
                    continue

                matches_out.append(f"🎾 {p1} vs {p2}\n   {tour} - {dt.strftime('%I:%M %p')}")
            except Exception as e:
                log.error(f"Error parsing tennis event: {e}")

    except Exception as e:
        log.error(f"Tennis API error: {e}")

    return matches_out


# ----------------------------------------------------------
# UFC (amplio: mostrar todos los próximos eventos)
# ----------------------------------------------------------
def get_mma_events():
    output = []
    try:
        url = f"https://www.thesportsdb.com/api/v1/json/{THE_SPORTS_DB_KEY}/eventsnextleague.php?id=3456"
        log.info("Fetching MMA events (wide mode)...")

        r = requests.get(url, timeout=20)
        data = r.json()
        events = data.get("events", [])
        log.info(f"UFC events found: {len(events)}")

        for e in events:
            fight = e.get("strEvent")
            date = e.get("dateEvent")
            time = e.get("strTime")
            output.append(f"🥋 {fight}\n   {date} {time}")

    except Exception as e:
        log.error(f"UFC API error: {e}")

    return output


# ----------------------------------------------------------
# Alias para compatibilidad con main.py
# ----------------------------------------------------------
get_ufc_events = get_mma_events
