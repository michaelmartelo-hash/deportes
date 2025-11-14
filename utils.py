# utils.py
from datetime import datetime
import pytz
from dateutil import parser

COLOMBIA = pytz.timezone("America/Bogota")

def to_colombia(dt_str, src_tz='UTC'):
    # dt_str puede ser ISO; convertir a zona Colombia y devolver string legible
    dt = parser.isoparse(dt_str) if isinstance(dt_str, str) else dt_str
    if dt.tzinfo is None:
        dt = pytz.timezone(src_tz).localize(dt)
    return dt.astimezone(COLOMBIA)

def fmt_time_col(dt):
    dtc = to_colombia(dt)
    return dtc.strftime("%Y-%m-%d %H:%M")
