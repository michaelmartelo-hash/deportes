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
TOKEN = os.getenv("TOKEN")  # Token del bot de Telegram
CHAT_ID = int(os.getenv("CHAT_ID"))  # ID de chat donde enviar los reportes

bot = Bot(token=TOKEN)

app = FastAPI()

logging.basicConfig(level=logging.INFO)


# ----------------------------
# FUNCIÓN PRINCIPAL DEL REPORTE
# ----------------------------
async def send_daily_report():
    """
    ENVÍA LA NOTIFICACIÓN DIARIA CON:
    - Partidos importantes de fútbol
    - Partidos top 10 de tenis
    - Eventos UFC del día
    - Probabilidades / predicciones
    """

    try:
        now = datetime.now(ZoneInfo("America/Bogota")).strftime("%Y-%m-%d %H:%M:%S")

        # Aquí colocarás tus llamadas a APIs reales.
        # Por ahora enviamos un mensaje básico para validar funcionamiento.

        message = (
            f"📊 *Reporte Deportivo*\n"
            f"🕒 Fecha/Hora Colombia: {now}\n\n"
            "⚽ Partidos importantes de fútbol:\n"
            "• (Aquí irán los partidos obtenidos de las APIs)\n\n"
            "🎾 Partidos de tenis (Top 10):\n"
            "• (Aquí irán los partidos con horarios)\n\n"
            "🥋 UFC hoy:\n"
            "• (Aquí irán las peleas principales)\n\n"
            "📈 Predicciones basadas en probabilidades y casas de apuestas:\n"
            "• (Aquí irán tus modelos)\n"
        )

        await asyncio.get_event_loop().run_in_executor(
            None, lambda: bot.send_message(
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
    # Horarios en hora de Colombia
    colombia_tz = "America/Bogota"

    # 8:00 AM
    scheduler.add_job(
        send_daily_report,
        trigger=CronTrigger(hour=8, minute=0, timezone=colombia_tz),
        name="report_8am"
    )

    # 2:00 PM
    scheduler.add_job(
        send_daily_report,
        trigger=CronTrigger(hour=14, minute=0, timezone=colombia_tz),
        name="report_2pm"
    )

    # 4:30 PM
    scheduler.add_job(
        send_daily_report,
        trigger=CronTrigger(hour=16, minute=30, timezone=colombia_tz),
        name="report_430pm"
    )

    # 8:00 PM
    scheduler.add_job(
        send_daily_report,
        trigger=CronTrigger(hour=20, minute=0, timezone=colombia_tz),
        name="report_8pm"
    )

    scheduler.start()
    logging.info("Scheduler iniciado.")


# ----------------------------
# FASTAPI ENDPOINTS
# ----------------------------
@app.get("/")
def home():
    return {"status": "ok", "message": "Sports Notifier Bot Running"}


# ----------------------------
# EVENTO AL INICIAR
# ----------------------------
@app.on_event("startup")
async def startup_event():
    start_scheduler()
    logging.info("Bot iniciado en Render.")


# ----------------------------
# SERVIDOR LOCAL
# ----------------------------
if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000)


@app.get("/")
def root():
    return {"status":"ok", "note":"Bot notifier running"}
