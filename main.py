# main.py
import os
import logging
from fastapi import FastAPI
from apscheduler.schedulers.background import BackgroundScheduler
from datetime import datetime, time, timedelta
import pytz
from providers import gather_daily_events
from telegram import Bot

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("tele_notifier")

# CONFIG desde variables de entorno (ponerlas en Render)
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")        # int
TIMEZONE = os.getenv("TZ", "America/Bogota")
SCHEDULE_HOUR = int(os.getenv("SCHEDULE_HOUR", "8"))    # 8 => 08:00

bot = Bot(token=TELEGRAM_TOKEN)
app = FastAPI()

def send_message(text: str):
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        logger.error("Faltan credenciales de Telegram")
        return
    bot.send_message(chat_id=int(TELEGRAM_CHAT_ID), text=text, parse_mode="HTML")

def job_send_daily():
    """
    Esta función se ejecuta a las 08:00 America/Bogota y:
     - llama a providers.gather_daily_events()
     - recibe un texto formateado y lo envía por telegram
    """
    tz = pytz.timezone(TIMEZONE)
    now = datetime.now(tz)
    logger.info(f"Ejecutando job diario: {now.isoformat()}")
    try:
        message = gather_daily_events(now.date(), timezone=TIMEZONE)
        if not message:
            message = "No hay eventos relevantes para hoy."
        send_message(message)
    except Exception as e:
        logger.exception("Error en job_send_daily: %s", e)
        send_message(f"Error al obtener eventos diarios: {e}")

@app.on_event("startup")
def startup_event():
    # Scheduler que corre en background (útil en Render/Heroku)
    tz = pytz.timezone(TIMEZONE)
    scheduler = BackgroundScheduler(timezone=tz)
    # programar a las 08:00 todos los días
    scheduler.add_job(
        job_send_daily,
        trigger='cron',
        hour=SCHEDULE_HOUR,
        minute=0,
        id='daily_job',
        replace_existing=True
    )
    scheduler.start()
    logger.info("Scheduler iniciado. Job diario programado a %02d:00 %s", SCHEDULE_HOUR, TIMEZONE)

@app.get("/")
def root():
    return {"status":"ok", "note":"Bot notifier running"}
