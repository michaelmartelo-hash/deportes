# providers.py
import os
import requests
from models import elo_winprob, odds_to_prob, normalize_probs_from_odds, combine_probs
from utils import to_colombia, fmt_time_col
import pytz

# VARIABLES DE ENTORNO (poner en Render)
API_FOOTBALL_KEY = os.getenv("API_FOOTBALL_KEY")   # API-Football / api-sports
ODDS_API_KEY = os.getenv("ODDS_API_KEY")           # The Odds API
API_TENNIS_KEY = os.getenv("API_TENNIS_KEY")       # Opcional

HEADERS_FOOT = {"x-apisports-key": API_FOOTBALL_KEY} if API_FOOTBALL_KEY else {}

def fetch_fifa_top20():
    """
    Ejemplo simple: obtener Top-20 desde sitio de FIFA (o desde un proveedor).
    Aquí hacemos un placeholder: si tienes una API que devuelva rankings úsala.
    """
    # Puedes hacer scraping de inside.fifa.com o usar un endpoint si tu proveedor lo da.
    # Por simplicidad devolvemos None para que el caller use cached top20 o env var.
    return None

def fetch_football_fixtures_for_date(date_obj):
    """Usando API-Football obtener fixtures de la fecha y filtrar por competiciones."""
    url = "https://v3.football.api-sports.io/fixtures"
    params = {"date": date_obj.isoformat()}
    r = requests.get(url, headers=HEADERS_FOOT, params=params, timeout=20)
    r.raise_for_status()
    data = r.json()
    return data.get("response", [])

def fetch_odds_for_event_sportbook(league_sport_key, event_ids=None, sport='soccer'):
    """Consulta The Odds API para eventos (ejemplo)."""
    url = f"https://api.the-odds-api.com/v4/sports/{sport}/odds"
    params = {"apiKey": ODDS_API_KEY, "regions": "eu,us,uk", "markets": "h2h"}
    r = requests.get(url, params=params, timeout=10)
    if r.status_code != 200:
        return {}
    return r.json()

def gather_daily_events(date_obj, timezone="America/Bogota"):
    """
    Orquesta la búsqueda: fútbol (selecciones top20 + competiciones), tenis top10, UFC.
    Devuelve texto en HTML/Markdown para enviar por Telegram.
    """
    parts = []
    # 1) Fútbol
    try:
        fixtures = fetch_football_fixtures_for_date(date_obj)
    except Exception as e:
        fixtures = []
    # filtrar por competiciones: Champions League, LaLiga (Spain) y Premier League (England)
    important_competitions = {
        "UEFA Champions League": ["Champions League", "UEFA Champions League"],
        "LaLiga": ["LaLiga", "Primera Division", "LaLiga EA SPORTS", "Primera División"],
        "Premier League": ["Premier League"]
    }
    foot_lines = []
    for f in fixtures:
        league_name = f.get("league", {}).get("name", "")
        if any(k.lower() in league_name.lower() for group in important_competitions.values() for k in group):
            home = f["teams"]["home"]["name"]
            away = f["teams"]["away"]["name"]
            kickoff = f["fixture"]["date"]
            kickoff_local = fmt_time_col(kickoff)
            # intentamos obtener odds (simplificado)
            odds = {}  # placeholder, aquí invocarías fetch_odds_for_event_sportbook
            # simple model: usar ratings ficticios o ELO placeholder
            p_home = 0.5
            p_away = 0.5
            market_probs = normalize_probs_from_odds({"home":2.0, "away":2.5}) if odds else {"home":0.5, "away":0.5}
            combined = combine_probs({"home":p_home, "away":p_away}, market_probs, w_model=0.4)
            foot_lines.append(f"{league_name}: {home} vs {away} — {kickoff_local} (Prob: {combined})")
    if foot_lines:
        parts.append("<b>Fútbol (partidos importantes hoy):</b>\n" + "\n".join(foot_lines))

    # 2) Tenis (usa API-Tennis o provider)
    # Aquí hacemos una llamada de ejemplo a api-tennis si se configura la KEY.
    tennis_lines = []
    if os.getenv("API_TENNIS_KEY"):
        try:
            # Ejemplo: https://api-tennis.com/endpoint...
            pass
        except Exception:
            pass
    # Si hay lines:
    if tennis_lines:
        parts.append("<b>Tenis (Top10 hoy):</b>\n" + "\n".join(tennis_lines))

    # 3) UFC / MMA
    mma_lines = []
    # intentar obtener odds eventos mma desde The Odds API
    if ODDS_API_KEY:
        try:
            mma_odds = fetch_odds_for_event_sportbook("mma_mixed_martial_arts", sport='mma_mixed_martial_arts')
            # filtrar por fecha == date_obj
            # agregar las 5 peleas principales y probabilidades
        except Exception:
            mma_odds = []
    if mma_lines:
        parts.append("<b>UFC / MMA:</b>\n" + "\n".join(mma_lines))

    # unir y devolver
    if not parts:
        return "No hay eventos relevantes hoy."
    return "\n\n".join(parts)
