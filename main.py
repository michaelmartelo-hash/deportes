import os
import requests
from fastapi import FastAPI
import uvicorn
from datetime import datetime
from zoneinfo import ZoneInfo

# ============================
# ENV VARIABLES
# ============================
TELEGRAM_TOKEN = os.getenv("TOKEN")
TELEGRAM_CHAT_ID = os.getenv("CHAT_ID")

API_FOOTBALL_KEY = os.getenv("API_FOOTBALL_KEY")
API_TENNIS_KEY = os.getenv("API_TENNIS_KEY")
ODDS_API_KEY = os.getenv("ODDS_API_KEY")

app = FastAPI()


# ============================
# HELPER: ENVIAR A TELEGRAM
# ============================
def send_telegram(msg: str):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    resp = requests.post(url, json={
        "chat_id": TELEGRAM_CHAT_ID,
        "text": msg,
        "parse_mode": "HTML"
    })
    print("Telegram response:", resp.text)
    return resp.status_code == 200


# ============================
# TENIS (TOP 10)
# ============================
def get_tennis_report():
    try:
        url = "https://v1.tennis.api-sports.io/fixtures"
        headers = {"x-apisports-key": API_TENNIS_KEY}

        r = requests.get(url, headers=headers)
        data = r.json()

        matches = []
        for m in data.get("response", []):
            try:
                rank_home = m["players"]["home"]["ranking"]
                rank_away = m["players"]["away"]["ranking"]

                if rank_home <= 10 or rank_away <= 10:
                    matches.append(m)
            except:
                continue

        if not matches:
            return "🎾 <b>Tenis</b>: No hay partidos del top 10 hoy.\n"

        msg = "🎾 <b>Tenis - Top 10 Hoy</b>\n"
        for m in matches:
            home = m["players"]["home"]["name"]
            away = m["players"]["away"]["name"]

            msg += f"• {home} vs {away}\n"

        return msg + "\n"

    except Exception as e:
        return f"🎾 Error tenis: {e}\n\n"


# ============================
# UFC
# ============================
def get_ufc_report():
    try:
        url = "https://api.the-odds-api.com/v4/sports/mma_mixed_martial_arts/events?apiKey=" + ODDS_API_KEY
        data = requests.get(url).json()

        if not data:
            return "🥊 <b>UFC</b>: No hay eventos hoy.\n"

        msg = "🥊 <b>Peleas UFC Hoy</b>\n"
        for event in data:
            for fight in event.get("competitors", []):
                pass

            msg += f"• {event['home_team']} vs {event['away_team']}\n"

        return msg + "\n"

    except Exception as e:
        return f"🥊 Error UFC: {e}\n\n"


# ============================
# FÚTBOL - Selecciones nacionales
# ============================
def get_soccer_report():
    try:
        url = "https://v3.football.api-sports.io/fixtures?date=" + datetime.now().strftime("%Y-%m-%d")
        headers = {"x-apisports-key": API_FOOTBALL_KEY}
        data = requests.get(url, headers=headers).json()

        matches = [
            m for m in data.get("response", [])
            if m["teams"]["home"]["name"] in ("Colombia", "Brazil", "Argentina", "Chile", "Ecuador", "Uruguay", "USA", "New Zealand")
            or m["teams"]["away"]["name"] in ("Colombia", "Brazil", "Argentina", "Chile", "Ecuador", "Uruguay", "USA", "New Zealand")
        ]

        if not matches:
            return "⚽ <b>Fútbol selecciones</b>: No hay partidos hoy.\n"

        msg = "⚽ <b>Partidos de Selecciones Hoy</b>\n"
        for m in matches:
            home = m["teams"]["home"]["name"]
            away = m["teams"]["away"]["name"]

            msg += f"• {home} vs {away}\n"

        return msg + "\n"

    except Exception as e:
        return f"⚽ Error fútbol: {e}\n\n"


# ============================
# PROBABILIDADES
# ============================
def get_probabilities():
    try:
        url = f"https://api.the-odds-api.com/v4/sports/soccer_international/odds?apiKey={ODDS_API_KEY}&regions=eu"
        data = requests.get(url).json()

        msg = "📊 <b>Probabilidades</b>\n"

        for event in data:
            try:
                home = event["home_team"]
                away = event["away_team"]
                odds = event["bookmakers"][0]["markets"][0]["outcomes"]

                for o in odds:
                    if o["name"] == home:
                        home_p = round(100 / o["price"], 1)
                    elif o["name"] == away:
                        away_p = round(100 / o["price"], 1)
                    else:
                        draw_p = round(100 / o["price"], 1)

                msg += f"• {home} vs {away}\n"
                msg += f"   - Local: {home_p}%\n"
                msg += f"   - Empate: {draw_p}%\n"
                msg += f"   - Visitante: {away_p}%\n\n"

            except:
                continue

        return msg + "\n"

    except Exception as e:
        return f"📊 Error probabilidades: {e}\n\n"


# ============================
# GENERAR REPORTE COMPLETO
# ============================
def generate_report():
    report = ""

    report += get_tennis_report()
    report += get_ufc_report()
    report += get_soccer_report()
    report += get_probabilities()

    return report


# ============================
# ENDPOINT PRINCIPAL
# ============================
@app.get("/run_report")
def run_report():
    report = generate_report()
    print("\n====== REPORTE ENVIADO ======\n")
    print(report)

    ok = send_telegram(report)

    if ok:
        return {"status": "Reporte enviado"}
    else:
        return {"status": "Error enviando Telegram"}


# ============================
# SERVER LOCAL
# ============================
if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=10000)
