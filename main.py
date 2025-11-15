import os
import asyncio
import logging
from datetime import datetime
from zoneinfo import ZoneInfo

import requests
from fastapi import FastAPI
from telegram import Bot

# -------------------------------------
# CONFIGURACIÓN
# -------------------------------------
API_FOOTBALL_KEY = os.getenv("API_FOOTBALL_KEY")
API_TENNIS_KEY = os.getenv("API_TENNIS_KEY")
ODDS_API_KEY = os.getenv("ODDS_API_KEY")

TOKEN = os.getenv("TOKEN")
CHAT_ID = int(os.getenv("CHAT_ID"))

bot = Bot(token=TOKEN)
app = FastAPI()

logging.basicConfig(level=logging.INFO)

COLOMBIA_TZ = ZoneInfo("America/Bogota")

# -------------------------------------
# TOP 20 FIFA (para filtrar selecciones)
# -------------------------------------
FIFA_TOP20 = [
    "Argentina", "Francia", "Inglaterra", "Bélgica", "Brasil",
    "Países Bajos", "Portugal", "España", "Italia", "Croacia",
    "EE.UU.", "Colombia", "México", "Marruecos", "Alemania",
    "Suiza", "Uruguay", "Dinamarca", "Japón", "Senegal"
]

# -------------------------------------
# OBTENER PROBABILIDADES DESDE ODDS API
# -------------------------------------
def get_probabilities(team1, team2, sport, match_id):
    try:
        url = f"https://api.the-odds-api.com/v4/sports/{sport}/odds"
        params = {
            "apiKey": ODDS_API_KEY,
            "regions": "us",
            "markets": "h2h"
        }
        r = requests.get(url, params=params)
        data = r.json()

        for event in data:
            if event["id"] == match_id:
                outcomes = event["bookmakers"][0]["markets"][0]["outcomes"]
                prob1 = 1 / float(outcomes[0]["price"])
                prob2 = 1 / float(outcomes[1]["price"])
                total = prob1 + prob2
                prob1 = round(prob1 / total * 100, 1)
                prob2 = round(prob2 / total * 100, 1)
                return prob1, prob2
    except:
        return None, None

    return None, None

# -------------------------------------
# FUTBOL (API-FOOTBALL)
# Solo partidos entre selecciones nacionales top 20 FIFA
# -------------------------------------
def get_football_matches():
    headers = {"x-apisports-key": API_FOOTBALL_KEY}
    url = "https://v3.football.api-sports.io/fixtures"

    today = datetime.now(COLOMBIA_TZ).strftime("%Y-%m-%d")

    params = {"date": today}

    r = requests.get(url, headers=headers, params=params)
    data = r.json()

    matches = []

    if "response" not in data:
        return matches

    for m in data["response"]:
        home = m["teams"]["home"]["name"]
        away = m["teams"]["away"]["name"]

        # Filtrar SOLO selecciones en Top 20 FIFA
        if home in FIFA_TOP20 or away in FIFA_TOP20:
            match_id = str(m["fixture"]["id"])
            prob1, prob2 = get_probabilities(home, away, "soccer", match_id)

            hour_col = datetime.fromisoformat(
                m["fixture"]["date"].replace("Z", "+00:00")
            ).astimezone(COLOMBIA_TZ).strftime("%H:%M")

            matches.append({
                "home": home,
                "away": away,
                "time": hour_col,
                "prob1": prob1,
                "prob2": prob2
            })

    return matches

# -------------------------------------
# TENIS (API-TENNIS)
# Solo TOP 10 ATP
# -------------------------------------
TOP10_ATP = [
    "Novak Djokovic", "Carlos Alcaraz", "Jannik Sinner", "Alexander Zverev",
    "Daniil Medvedev", "Holger Rune", "Andrey Rublev", "Casper Ruud",
    "Hubert Hurkacz", "Grigor Dimitrov"
]

def get_tennis_matches():
    url = f"https://api.tennisapi.com/v1/matches?date=today&key={API_TENNIS_KEY}"

    r = requests.get(url)
    data = r.json()

    matches = []

    if "data" not in data:
        return matches

    for m in data["data"]:
        p1 = m["player1"]
        p2 = m["player2"]

        if p1 in TOP10_ATP or p2 in TOP10_ATP:
            match_id = str(m["id"])

            prob1, prob2 = get_probabilities(p1, p2, "tennis", match_id)

            time = datetime.fromtimestamp(m["time"]).astimezone(COLOMBIA_TZ).strftime("%H:%M")

            matches.append({
                "p1": p1,
                "p2": p2,
                "time": time,
                "prob1": prob1,
                "prob2": prob2
            })

    return matches

# -------------------------------------
# UFC (SOLO UFC)
# -------------------------------------
def get_ufc_events():
    url = f"https://api.the-odds-api.com/v4/sports/mma_mixed_martial_arts/events?apiKey={ODDS_API_KEY}"
    r = requests.get(url)
    data = r.json()

    fights = []

    for event in data:
        if "ufc" not in event["sport_title"].lower():
            continue  # descartar PFL, Bellator, etc

        for fight in event["bookmakers"][0]["markets"][0]["outcomes"]:
            pass  # solo estructura

        for f in event.get("fights", []):
            fighter1 = f["fighter1"]["name"]
            fighter2 = f["fighter2"]["name"]
            start = datetime.fromisoformat(event["commence_time"].replace("Z", "+00:00"))
            time = start.astimezone(COLOMBIA_TZ).strftime("%H:%M")

            prob1, prob2 = get_probabilities(fighter1, fighter2, "mma_mixed_martial_arts", event["id"])

            fights.append({
                "f1": fighter1,
                "f2": fighter2,
                "time": time,
                "prob1": prob1,
                "prob2": prob2
            })

    return fights[:5]  # solo las 5 principales

# -------------------------------------
# FUNCION PRINCIPAL DEL REPORTE
# -------------------------------------
async def send_daily_report():
    try:
        now = datetime.now(COLOMBIA_TZ).strftime("%Y-%m-%d %H:%M")

        football = get_football_matches()
        tennis = get_tennis_matches()
        ufc = get_ufc_events()

        msg = f"📊 *Reporte Deportivo*\n🕒 *Hora Colombia:* {now}\n\n"

        # FUTBOL
        msg += "⚽ *Partidos de selecciones (Top 20 FIFA)*\n"
        if football:
            for m in football:
                msg += f"• {m['home']} vs {m['away']} — {m['time']}h\n"
                if m['prob1']:
                    msg += f"   Prob: {m['home']} {m['prob1']}% — {m['away']} {m['prob2']}%\n"
        else:
            msg += "No hay partidos importantes hoy.\n"
        msg += "\n"

        # TENIS
        msg += "🎾 *Tenis (Top 10 ATP)*\n"
        if tennis:
            for m in tennis:
                msg += f"• {m['p1']} vs {m['p2']} — {m['time']}h\n"
                if m['prob1']:
                    msg += f"   Prob: {m['p1']} {m['prob1']}% — {m['p2']} {m['prob2']}%\n"
        else:
            msg += "No hay partidos relevantes hoy.\n"
        msg += "\n"

        # UFC
        msg += "🥋 *UFC — Cartelera principal*\n"
        if ufc:
            for f in ufc:
                msg += f"• {f['f1']} vs {f['f2']} — {f['time']}h\n"
                if f['prob1']:
                    msg += f"   Prob: {f['f1']} {f['prob1']}% — {f['f2']} {f['prob2']}%\n"
        else:
            msg += "No hay eventos UFC hoy.\n"

        await asyncio.get_event_loop().run_in_executor(
            None, lambda: bot.send_message(chat_id=CHAT_ID, text=msg, parse_mode="Markdown")
        )

        logging.info("Reporte enviado correctamente.")

    except Exception as e:
        logging.error(f"ERROR en reporte: {e}")

# -------------------------------------
# ENDPOINT PARA CRON DE RENDER
# -------------------------------------
@app.get("/run_report")
async def manual_report():
    asyncio.create_task(send_daily_report())
    return {"status": "Reporte enviado"}

@app.get("/")
def home():
    return {"status": "OK", "msg": "Sports Notifier Running"}


