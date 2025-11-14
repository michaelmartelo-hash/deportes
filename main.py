# main.py
import os
import asyncio
import logging
from datetime import datetime
from zoneinfo import ZoneInfo

import requests
from fastapi import FastAPI
from telegram import Bot
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

# ----------------------------
# CONFIGURACIÓN
# ----------------------------
TOKEN = os.getenv("TOKEN")
CHAT_ID = int(os.getenv("CHAT_ID"))

bot = Bot(token=TOKEN)

app = FastAPI()

logging.basicConfig(level=logging.INFO)


# ----------------------------
# FUNCIÓN PRINCIPAL DEL REPORTE
# ----------------------------
async def send_daily_report():
    try:
        now = datetime.now(ZoneInfo("America/Bogota")).strftime("%Y-%m-%d %H:%M:%S")

        message = (
            f"📊 *Reporte Deportivo*\n"
            f"🕒 Fecha/Hora Colombia: {now}\n\n"
            "⚽ Partidos importantes de fútbol:\n"
            "• (Próximamente API real)\n\n"
            "🎾 Partidos de tenis (Top 10):\n"
            "• (Próximamente API real)\n\n"
            "🥋 UFC hoy:\n"
            "• (Próximamente API real)\n\n"
            "📈 Predicciones:\n"
            "• (Próximamente modelos reales)\n"
        )

        # Ejecutar send_message sin bloquear
        await asyncio.get_event_loop().run_in_executor(
            None,
            lambda: bot.send_message(
                chat_id=CHAT_ID,
                text=message,
                parse_mode="Markdown"
            )
        )

        logging.info("Reporte enviado correctamente.")

    except Exception as e:
        logging.error(f"ERROR enviando reporte: {e}")


# ----------------------------
# INICIALIZAR SCHEDULER
# ----------------------------
scheduler = AsyncIOScheduler()


def start_scheduler():
    colombia_tz = "America/Bogota"

    scheduler.add_job(send_daily_report, CronTrigger(hour=8, minute=0, timezone=colombia_tz), name="report_8am")
    scheduler.add_job(send_daily_report, CronTrigger(hour=14, minute=0, timezone=colombia_tz), name="report_2pm")
    scheduler.add_job(send_daily_report, CronTrigger(hour=16, minute=30, timezone=colombia_tz), name="report_430pm")
    scheduler.add_job(send_daily_report, CronTrigger(hour=20, minute=0, timezone=colombia_tz), name="report_8pm")

    scheduler.start()
    logging.info("Scheduler iniciado.")


# ----------------------------
# FASTAPI ENDPOINTS
# ----------------------------
@app.get("/")
def home():
    return {"status": "ok", "message": "Sports Notifier Bot Running"}


@app.get("/run_report")
async def manual_trigger():
    """Para ejecutar el reporte manualmente (o desde BetterStack / Render Cron Jobs)"""
    await send_daily_report()
    return {"status": "ok"}


# ----------------------------
# EVENTO AL INICIAR
# ----------------------------
@app.on_event("startup")
async def startup_event():
    start_scheduler()
    logging.info("Bot iniciado en Render.")
