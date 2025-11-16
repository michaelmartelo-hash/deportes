# main.py
import os
import asyncio
import logging
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
import requests
from fastapi import FastAPI

# import providers (archivo providers.py)
from providers import (
    get_football_matches,
    get_tennis_matches,
    get_ufc_events,
)

# ---------------------------
# CONFIG / ENV
# ---------------------------
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("sports-notifier")

API_FOOTBALL_KEY = os.getenv("API_FOOTBALL_KEY")
FOOTBALL_DATA_API_KEY = os.getenv("FOOTBALL_DATA_API_KEY")  # football-data.org
API_TENNIS_KEY = os.getenv("API_TENNIS_KEY")
ODDS_API_KEY = os.getenv("ODDS_API_KEY")
THESPORTSDB_API_KEY = os.getenv("THESPORTSDB_API_KEY")

TELEGRAM_TOKEN = os.getenv("TOKEN")
TELEGRAM_CHAT_ID = os.getenv("CHAT_ID")  # keep as string for requests

# timezone
COLOMBIA = ZoneInfo("America/Bogota")

# ---------------------------
# FILTROS / TOP
# ---------------------------
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
# UTIL: escape HTML for Telegram y chunk
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
# BUILD REPORT (Habilitado)
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
# SEND TELEGRAM (Habilitado)
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
# MAIN TASK (Habilitado)
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
# FASTAPI (Habilitado)
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
# ENTRYPOINT LOCAL (Habilitado)
# ---------------------------
if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", 10000))
    uvicorn.run("main:app", host="0.0.0.0", port=port, log_level="info")

# ============================
# CODIGO ORIGINAL NO USADO
# ============================
# Las funciones norm(), tennis_in_top10(), escape_html(), chunk_message()
# y los sets FIFA_TOP20 y TOP10_ATP se conservan, pero podrían comentarse si no se usan.
# Ejemplo de comentario:
# # def norm(s):
# #     if not s:
# #         return ""
# #     return s.lower().replace("á","a").replace("é","e").replace("í","i").replace("ó","o").replace("ú","u").strip()
