# models.py
import math
import numpy as np

def elo_winprob(r_a, r_b):
    """Probabilidad esperada ELO simple (football/tennis)"""
    return 1.0 / (1 + 10 ** ((r_b - r_a) / 400.0))

def odds_to_prob(decimal_odd):
    """Convierte cuota decimal a probabilidad implícita (sin vig)"""
    return 1.0 / decimal_odd

def normalize_probs_from_odds(odds):
    """Dado dict {'home':odd, 'away':odd, 'draw':odd?}, devuelve probabilidades normalizadas quitando vig"""
    inv = {k: 1.0 / v for k, v in odds.items() if v and v > 0}
    s = sum(inv.values())
    probs = {k: inv[k] / s for k in inv}
    return probs

def combine_probs(model_prob, market_prob, w_model=0.4):
    """Combina prob del modelo y del mercado. w_model = peso del modelo"""
    w_market = 1 - w_model
    combined = {}
    for k in set(model_prob) | set(market_prob):
        combined[k] = model_prob.get(k, 0) * w_model + market_prob.get(k, 0) * w_market
    # renormalizar
    s = sum(combined.values())
    if s > 0:
        for k in combined:
            combined[k] /= s
    return combined
