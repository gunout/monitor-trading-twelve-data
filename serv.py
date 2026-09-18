#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from flask import Flask, render_template, jsonify, request, send_from_directory
from flask_cors import CORS
from flask_socketio import SocketIO, emit
from datetime import datetime, timedelta
import pandas as pd
import numpy as np
import os
import pytz
import logging
import time
import threading
from dotenv import load_dotenv
from twelvedata import TDClient
from sklearn.linear_model import LinearRegression
from sklearn.preprocessing import PolynomialFeatures
from sklearn.pipeline import make_pipeline
import warnings
warnings.filterwarnings('ignore')

load_dotenv()
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__, static_folder='static', template_folder='templates')
app.config['SECRET_KEY'] = 'trading-monitor-secret-key'
CORS(app)
socketio = SocketIO(app, cors_allowed_origins="*", async_mode='threading')

# ============================================================
# CONFIGURATION TWELVE DATA
# ============================================================
TWELVE_DATA_API_KEY = os.getenv("TWELVE_DATA_API_KEY")
if not TWELVE_DATA_API_KEY:
    raise ValueError("Cle Twelve Data manquante ! Cree un .env avec TWELVE_DATA_API_KEY=ta_cle")

td = TDClient(apikey=TWELVE_DATA_API_KEY)
US_TIMEZONE = pytz.timezone('America/New_York')

# ============================================================
# CACHES
# ============================================================
price_cache = {}
candles_cache = {}
insights_cache = {}
fundamental_cache = {}

PRICE_CACHE_DURATION = 600
CANDLES_CACHE_DURATION = 3600
INSIGHTS_CACHE_DURATION = 600
FUNDAMENTAL_CACHE_DURATION = 86400

rate_limiter = {
    'last_calls': [],
    'max_per_minute': 5,
    'min_interval': 12
}

rate_lock = threading.Lock()

def rate_limit_wait():
    with rate_lock:
        now = time.time()
        if rate_limiter['last_calls']:
            time_since_last = now - rate_limiter['last_calls'][-1]
            if time_since_last < rate_limiter['min_interval']:
                wait = rate_limiter['min_interval'] - time_since_last
                logger.info(f"Attente intervalle min {wait:.1f}s")
                time.sleep(wait)
                now = time.time()
        rate_limiter['last_calls'] = [t for t in rate_limiter['last_calls'] if now - t < 60]
        if len(rate_limiter['last_calls']) >= rate_limiter['max_per_minute']:
            wait_time = 60 - (now - rate_limiter['last_calls'][0]) + 1
            if wait_time > 0 and wait_time < 45:
                logger.info(f"Rate limit, attente {wait_time:.1f}s")
                time.sleep(wait_time)
            elif wait_time >= 45:
                logger.warning(f"Rate limit critique ({wait_time:.0f}s), skip")
                return False
        rate_limiter['last_calls'].append(time.time())
        return True

def get_cached(cache_dict, key, duration):
    if key in cache_dict:
        data, ts = cache_dict[key]
        if (datetime.now() - ts).total_seconds() < duration:
            return data
    return None

def set_cached(cache_dict, key, data):
    cache_dict[key] = (data, datetime.now())

def safe_float(v, default=0.0):
    try:
        if pd.isna(v) or v is None:
            return default
        return float(v)
    except:
        return default

# ============================================================
# MAP SYMBOLES
# ============================================================
SYMBOL_MAP = {
    '^GSPC': 'SPY', '^DJI': 'DIA', '^IXIC': 'QQQ',
    '^FCHI': 'EWQ', '^GDAXI': 'EWG', '^N225': 'EWJ', '^FTSE': 'EWU',
    'BTC-USD': 'BTC/USD', 'ETH-USD': 'ETH/USD', 'SOL-USD': 'SOL/USD',
    'EURUSD=X': 'EUR/USD', 'GBPUSD=X': 'GBP/USD', 'USDJPY=X': 'USD/JPY',
    'ML.PA': 'MC', 'SAN.PA': 'SAN', 'OR.PA': 'OR', 'AI.PA': 'AI',
}

def to_twelvedata_symbol(symbol):
    return SYMBOL_MAP.get(symbol, symbol)

# ============================================================
# ASSETS
# ============================================================
ASSETS = {
    'GLD': {'name': 'Or', 'exchange': 'NYSE', 'category': 'Commodites', 'icon': '🥇', 'color': '#ffd700'},
    'SLV': {'name': 'Argent', 'exchange': 'NYSE', 'category': 'Commodites', 'icon': '🥈', 'color': '#c0c0c0'},
    'USO': {'name': 'Petrole WTI', 'exchange': 'NYSE', 'category': 'Commodites', 'icon': '🛢️', 'color': '#ff6b00'},
    'BTC-USD': {'name': 'Bitcoin', 'exchange': 'CRYPTO', 'category': 'Crypto', 'icon': '₿', 'color': '#ffaa00'},
    'ETH-USD': {'name': 'Ethereum', 'exchange': 'CRYPTO', 'category': 'Crypto', 'icon': '⟠', 'color': '#627eea'},
    'SOL-USD': {'name': 'Solana', 'exchange': 'CRYPTO', 'category': 'Crypto', 'icon': '◎', 'color': '#9945ff'},
    'EURUSD=X': {'name': 'EUR/USD', 'exchange': 'FOREX', 'category': 'Forex', 'icon': '🇪🇺🇺🇸', 'color': '#002395'},
    'GBPUSD=X': {'name': 'GBP/USD', 'exchange': 'FOREX', 'category': 'Forex', 'icon': '🇬🇧🇺🇸', 'color': '#012169'},
    'USDJPY=X': {'name': 'USD/JPY', 'exchange': 'FOREX', 'category': 'Forex', 'icon': '🇺🇸🇯🇵', 'color': '#bc002d'},
    'AAPL': {'name': 'Apple', 'exchange': 'NASDAQ', 'category': 'US Stocks', 'icon': '🍎', 'color': '#555555'},
    'MSFT': {'name': 'Microsoft', 'exchange': 'NASDAQ', 'category': 'US Stocks', 'icon': '💻', 'color': '#00a4ef'},
    'GOOGL': {'name': 'Alphabet', 'exchange': 'NASDAQ', 'category': 'US Stocks', 'icon': '🔍', 'color': '#4285f4'},
    'NVDA': {'name': 'NVIDIA', 'exchange': 'NASDAQ', 'category': 'US Stocks', 'icon': '🎮', 'color': '#76b900'},
    'TSLA': {'name': 'Tesla', 'exchange': 'NASDAQ', 'category': 'US Stocks', 'icon': '🚗', 'color': '#cc0000'},
    'AMZN': {'name': 'Amazon', 'exchange': 'NASDAQ', 'category': 'US Stocks', 'icon': '📦', 'color': '#ff9900'},
    'META': {'name': 'Meta', 'exchange': 'NASDAQ', 'category': 'US Stocks', 'icon': '📱', 'color': '#1877f2'},
    'JPM': {'name': 'JPMorgan', 'exchange': 'NYSE', 'category': 'US Stocks', 'icon': '🏦', 'color': '#003399'},
    'ML.PA': {'name': 'LVMH', 'exchange': 'Euronext', 'category': 'Paris Stocks', 'icon': '👔', 'color': '#000000'},
    'SAN.PA': {'name': 'Sanofi', 'exchange': 'Euronext', 'category': 'Paris Stocks', 'icon': '💊', 'color': '#005eb8'},
    'OR.PA': {'name': "L'Oreal", 'exchange': 'Euronext', 'category': 'Paris Stocks', 'icon': '💄', 'color': '#000000'},
    'AI.PA': {'name': 'Air Liquide', 'exchange': 'Euronext', 'category': 'Paris Stocks', 'icon': '💨', 'color': '#0050a0'},
    '^GSPC': {'name': 'S&P 500 (SPY)', 'exchange': 'INDEX', 'category': 'INDICES', 'icon': '📈', 'color': '#000000'},
    '^DJI': {'name': 'Dow Jones (DIA)', 'exchange': 'INDEX', 'category': 'INDICES', 'icon': '📈', 'color': '#1a237e'},
    '^IXIC': {'name': 'Nasdaq (QQQ)', 'exchange': 'INDEX', 'category': 'INDICES', 'icon': '📈', 'color': '#0066cc'},
    '^FCHI': {'name': 'France (EWQ)', 'exchange': 'INDEX', 'category': 'INDICES', 'icon': '🇫🇷', 'color': '#002395'},
    '^GDAXI': {'name': 'Allemagne (EWG)', 'exchange': 'INDEX', 'category': 'INDICES', 'icon': '🇩🇪', 'color': '#dd0000'},
    '^N225': {'name': 'Japon (EWJ)', 'exchange': 'INDEX', 'category': 'INDICES', 'icon': '🇯🇵', 'color': '#bc002d'},
    '^FTSE': {'name': 'UK (EWU)', 'exchange': 'INDEX', 'category': 'INDICES', 'icon': '🇬🇧', 'color': '#012169'},
    'SPY': {'name': 'S&P 500 ETF', 'exchange': 'NYSE', 'category': 'FUNDS', 'icon': '📊', 'color': '#0050b0'},
    'QQQ': {'name': 'Nasdaq 100 ETF', 'exchange': 'NASDAQ', 'category': 'FUNDS', 'icon': '📈', 'color': '#0066cc'},
    'DIA': {'name': 'Dow Jones ETF', 'exchange': 'NYSE', 'category': 'FUNDS', 'icon': '📊', 'color': '#1a237e'},
}

# ============================================================
# INDICATEURS TECHNIQUES
# ============================================================
def calculate_sma(data, period):
    if len(data) < period:
        return [None] * len(data)
    result = []
    for i in range(len(data)):
        if i < period - 1:
            result.append(None)
        else:
            result.append(sum(data[i-period+1:i+1]) / period)
    return result

def calculate_ema(data, period):
    if len(data) < period:
        return [None] * len(data)
    k = 2 / (period + 1)
    result = [data[0]]
    for i in range(1, len(data)):
        result.append(data[i] * k + result[-1] * (1 - k))
    return result

def calculate_rsi(data, period=14):
    if len(data) < period + 1:
        return [None] * len(data)
    result = [None] * len(data)
    gains = []
    losses = []
    for i in range(1, len(data)):
        diff = data[i] - data[i-1]
        gains.append(max(diff, 0))
        losses.append(max(-diff, 0))
    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period
    result[period] = 100 if avg_loss == 0 else 100 - (100 / (1 + avg_gain / avg_loss))
    for i in range(period, len(gains)):
        avg_gain = (avg_gain * (period - 1) + gains[i]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i]) / period
        result[i+1] = 100 if avg_loss == 0 else 100 - (100 / (1 + avg_gain / avg_loss))
    return result

def calculate_macd(data, fast=12, slow=26, signal=9):
    if len(data) < slow:
        return {'macd': [None] * len(data), 'signal': [None] * len(data), 'histogram': [None] * len(data)}
    ema_fast = calculate_ema(data, fast)
    ema_slow = calculate_ema(data, slow)
    macd_line = [ema_fast[i] - ema_slow[i] if ema_fast[i] is not None and ema_slow[i] is not None else None for i in range(len(data))]
    macd_clean = [x for x in macd_line if x is not None]
    signal_line = calculate_ema(macd_clean, signal) if macd_clean else []
    signal_full = [None] * len(data)
    idx = 0
    for i in range(len(data)):
        if macd_line[i] is not None:
            if idx < len(signal_line):
                signal_full[i] = signal_line[idx]
            idx += 1
    histogram = [macd_line[i] - signal_full[i] if macd_line[i] is not None and signal_full[i] is not None else None for i in range(len(data))]
    return {'macd': macd_line, 'signal': signal_full, 'histogram': histogram}

def calculate_bollinger(data, period=20, std_mult=2):
    if len(data) < period:
        return {'upper': [None] * len(data), 'middle': [None] * len(data), 'lower': [None] * len(data)}
    sma = calculate_sma(data, period)
    upper = []
    lower = []
    for i in range(len(data)):
        if sma[i] is None:
            upper.append(None)
            lower.append(None)
        else:
            std = np.std(data[i-period+1:i+1])
            upper.append(sma[i] + std_mult * std)
            lower.append(sma[i] - std_mult * std)
    return {'upper': upper, 'middle': sma, 'lower': lower}

def calculate_atr(high, low, close, period=14):
    if len(close) < period + 1:
        return [None] * len(close)
    tr = []
    for i in range(1, len(close)):
        tr.append(max(high[i] - low[i], abs(high[i] - close[i-1]), abs(low[i] - close[i-1])))
    atr = [None] * len(close)
    atr[period] = sum(tr[:period]) / period
    for i in range(period, len(tr)):
        atr[i+1] = (atr[i] * (period - 1) + tr[i]) / period
    return atr

def calculate_stochastic(high, low, close, k_period=14, d_period=3):
    if len(close) < k_period:
        return {'k': [None] * len(close), 'd': [None] * len(close)}
    k_values = [None] * len(close)
    for i in range(k_period - 1, len(close)):
        high_max = max(high[i-k_period+1:i+1])
        low_min = min(low[i-k_period+1:i+1])
        k_values[i] = 50 if high_max == low_min else ((close[i] - low_min) / (high_max - low_min)) * 100
    d_values = [None] * len(close)
    for i in range(k_period - 1 + d_period - 1, len(close)):
        valid_k = [k for k in k_values[i-d_period+1:i+1] if k is not None]
        if valid_k:
            d_values[i] = sum(valid_k) / len(valid_k)
    return {'k': k_values, 'd': d_values}

def calculate_volatility(data, period=20):
    if len(data) < period + 1:
        return 0
    returns = []
    for i in range(len(data) - period, len(data)):
        if i > 0 and data[i-1] != 0:
            returns.append((data[i] - data[i-1]) / data[i-1])
    if len(returns) < 2:
        return 0
    return np.std(returns) * np.sqrt(252) * 100

def calculate_all_indicators(candles):
    if not candles or len(candles) < 20:
        return {}
    
    close = [c['close'] for c in candles]
    high = [c['high'] for c in candles]
    low = [c['low'] for c in candles]
    current_price = close[-1] if close else 0
    
    indicators = {}
    indicators['sma_20'] = calculate_sma(close, 20)
    indicators['sma_50'] = calculate_sma(close, 50)
    indicators['sma_200'] = calculate_sma(close, 200)
    indicators['ema_12'] = calculate_ema(close, 12)
    indicators['ema_26'] = calculate_ema(close, 26)
    indicators['rsi'] = calculate_rsi(close, 14)
    macd = calculate_macd(close)
    indicators['macd'] = macd['macd']
    indicators['macd_signal'] = macd['signal']
    indicators['macd_histogram'] = macd['histogram']
    bb = calculate_bollinger(close)
    indicators['bb_upper'] = bb['upper']
    indicators['bb_middle'] = bb['middle']
    indicators['bb_lower'] = bb['lower']
    sto = calculate_stochastic(high, low, close)
    indicators['stoch_k'] = sto['k']
    indicators['stoch_d'] = sto['d']
    indicators['atr'] = calculate_atr(high, low, close)
    indicators['volatility'] = calculate_volatility(close)
    indicators['momentum'] = ((close[-1] - close[-10]) / close[-10]) * 100 if len(close) >= 10 else 0
    indicators['current_price'] = current_price
    indicators['last_rsi'] = indicators['rsi'][-1] if indicators['rsi'] and indicators['rsi'][-1] is not None else None
    indicators['last_macd'] = indicators['macd'][-1] if indicators['macd'] and indicators['macd'][-1] is not None else None
    indicators['last_macd_signal'] = indicators['macd_signal'][-1] if indicators['macd_signal'] and indicators['macd_signal'][-1] is not None else None
    indicators['last_sma_20'] = indicators['sma_20'][-1] if indicators['sma_20'] and indicators['sma_20'][-1] is not None else None
    indicators['last_sma_50'] = indicators['sma_50'][-1] if indicators['sma_50'] and indicators['sma_50'][-1] is not None else None
    indicators['last_sma_200'] = indicators['sma_200'][-1] if indicators['sma_200'] and indicators['sma_200'][-1] is not None else None
    indicators['last_stoch_k'] = indicators['stoch_k'][-1] if indicators['stoch_k'] and indicators['stoch_k'][-1] is not None else None
    indicators['last_stoch_d'] = indicators['stoch_d'][-1] if indicators['stoch_d'] and indicators['stoch_d'][-1] is not None else None
    indicators['last_bb_upper'] = indicators['bb_upper'][-1] if indicators['bb_upper'] and indicators['bb_upper'][-1] is not None else None
    indicators['last_bb_middle'] = indicators['bb_middle'][-1] if indicators['bb_middle'] and indicators['bb_middle'][-1] is not None else None
    indicators['last_bb_lower'] = indicators['bb_lower'][-1] if indicators['bb_lower'] and indicators['bb_lower'][-1] is not None else None
    indicators['last_atr'] = indicators['atr'][-1] if indicators['atr'] and indicators['atr'][-1] is not None else None

    signals = []
    score = 0
    
    if indicators['last_rsi'] is not None:
        if indicators['last_rsi'] < 30:
            signals.append({'type': 'buy', 'indicator': 'RSI', 'value': f"{indicators['last_rsi']:.1f}", 'message': 'Zone de survente'})
            score += 15
        elif indicators['last_rsi'] > 70:
            signals.append({'type': 'sell', 'indicator': 'RSI', 'value': f"{indicators['last_rsi']:.1f}", 'message': 'Zone de surachat'})
            score -= 15
    
    if indicators['last_macd'] is not None and indicators['last_macd_signal'] is not None and len(indicators['macd']) > 1:
        prev_macd = indicators['macd'][-2]
        prev_signal = indicators['macd_signal'][-2]
        if prev_macd is not None and prev_signal is not None:
            if prev_macd < prev_signal and indicators['last_macd'] > indicators['last_macd_signal']:
                signals.append({'type': 'buy', 'indicator': 'MACD', 'value': f"{indicators['last_macd']:.3f}", 'message': 'Croisement haussier'})
                score += 15
            elif prev_macd > prev_signal and indicators['last_macd'] < indicators['last_macd_signal']:
                signals.append({'type': 'sell', 'indicator': 'MACD', 'value': f"{indicators['last_macd']:.3f}", 'message': 'Croisement baissier'})
                score -= 15
    
    if indicators['last_sma_20'] is not None and indicators['last_sma_50'] is not None:
        prev_sma20 = indicators['sma_20'][-2] if len(indicators['sma_20']) > 1 else None
        prev_sma50 = indicators['sma_50'][-2] if len(indicators['sma_50']) > 1 else None
        if prev_sma20 is not None and prev_sma50 is not None:
            if prev_sma20 < prev_sma50 and indicators['last_sma_20'] > indicators['last_sma_50']:
                signals.append({'type': 'buy', 'indicator': 'SMA', 'value': 'Golden Cross', 'message': 'Croisement haussier'})
                score += 12
            elif prev_sma20 > prev_sma50 and indicators['last_sma_20'] < indicators['last_sma_50']:
                signals.append({'type': 'sell', 'indicator': 'SMA', 'value': 'Death Cross', 'message': 'Croisement baissier'})
                score -= 12
    
    if indicators['last_stoch_k'] is not None and indicators['last_stoch_d'] is not None:
        if indicators['last_stoch_k'] < 20 and indicators['last_stoch_d'] < 20:
            signals.append({'type': 'buy', 'indicator': 'Stochastic', 'value': f"K:{indicators['last_stoch_k']:.1f}", 'message': 'Survente'})
            score += 10
        elif indicators['last_stoch_k'] > 80 and indicators['last_stoch_d'] > 80:
            signals.append({'type': 'sell', 'indicator': 'Stochastic', 'value': f"K:{indicators['last_stoch_k']:.1f}", 'message': 'Surachat'})
            score -= 10
    
    if indicators['last_bb_lower'] is not None and indicators['last_bb_upper'] is not None:
        if current_price <= indicators['last_bb_lower'] * 1.01:
            signals.append({'type': 'buy', 'indicator': 'Bollinger', 'value': f"${current_price:.2f}", 'message': 'Bande inf.'})
            score += 8
        elif current_price >= indicators['last_bb_upper'] * 0.99:
            signals.append({'type': 'sell', 'indicator': 'Bollinger', 'value': f"${current_price:.2f}", 'message': 'Bande sup.'})
            score -= 8
    
    if indicators['momentum'] > 5:
        signals.append({'type': 'buy', 'indicator': 'Momentum', 'value': f"{indicators['momentum']:.1f}%", 'message': 'Haussier'})
        score += 8
    elif indicators['momentum'] < -5:
        signals.append({'type': 'sell', 'indicator': 'Momentum', 'value': f"{indicators['momentum']:.1f}%", 'message': 'Baissier'})
        score -= 8
    
    if score > 20:
        recommendation = 'ACHAT'
        confidence = min(95, 50 + abs(score) * 0.8)
    elif score < -20:
        recommendation = 'VENTE'
        confidence = min(95, 50 + abs(score) * 0.8)
    else:
        recommendation = 'NEUTRE'
        confidence = 50 + (abs(score) / 2)
    confidence = min(95, max(15, confidence))
    
    if indicators['last_atr'] is not None and indicators['last_atr'] > 0:
        indicators['stop_loss'] = current_price - 2 * indicators['last_atr']
        indicators['take_profit'] = current_price + 2 * indicators['last_atr']
    else:
        indicators['stop_loss'] = current_price * 0.975
        indicators['take_profit'] = current_price * 1.05
    
    indicators['signals'] = signals
    indicators['recommendation'] = recommendation
    indicators['confidence'] = confidence
    indicators['score'] = score
    indicators['buy_signals'] = sum(1 for s in signals if s['type'] == 'buy')
    indicators['sell_signals'] = sum(1 for s in signals if s['type'] == 'sell')
    indicators['is_strong_signal'] = (score > 30 or score < -30) and confidence > 70
    
    indicators['ia_recommendation'] = recommendation
    indicators['ia_confidence'] = confidence
    indicators['ia_probabilities'] = {
        'vente': max(0, 50 - score),
        'neutre': max(0, 50 - abs(score) / 2),
        'achat': max(0, 50 + score)
    }
    total = sum(indicators['ia_probabilities'].values())
    if total > 0:
        for k in indicators['ia_probabilities']:
            indicators['ia_probabilities'][k] = (indicators['ia_probabilities'][k] / total) * 100
    
    try:
        if len(close) >= 30:
            x = np.arange(len(close)).reshape(-1, 1)
            y = np.array(close).reshape(-1, 1)
            model = make_pipeline(PolynomialFeatures(2), LinearRegression())
            model.fit(x, y)
            future = np.arange(len(close), len(close) + 5).reshape(-1, 1)
            predictions = model.predict(future).flatten()
            indicators['predictions'] = [float(p) for p in predictions]
        else:
            indicators['predictions'] = [current_price] * 5
    except:
        indicators['predictions'] = [current_price] * 5
    
    return indicators

# ============================================================
# FONCTIONS TWELVE DATA
# ============================================================
def fetch_price_twelvedata(symbol):
    td_symbol = to_twelvedata_symbol(symbol)
    if not rate_limit_wait():
        return None
    try:
        r = td.price(symbol=td_symbol).as_json()
        if r and r.get('price'):
            return safe_float(r['price'])
    except Exception as e:
        logger.warning(f"Erreur price {symbol}: {str(e)[:80]}")
    return None

def fetch_candles_twelvedata(symbol, period='1d'):
    td_symbol = to_twelvedata_symbol(symbol)
    if not rate_limit_wait():
        return None
    
    interval_map = {'1d': '1min', '5d': '5min', '1mo': '30min', '3mo': '1h', '6mo': '1day', '1y': '1day'}
    outputsize_map = {'1d': 390, '5d': 200, '1mo': 200, '3mo': 500, '6mo': 180, '1y': 252}
    
    interval = interval_map.get(period, '1day')
    outputsize = outputsize_map.get(period, 100)
    
    try:
        # PAS de timezone parameter (payant)
        ts = td.time_series(
            symbol=td_symbol,
            interval=interval,
            outputsize=outputsize
        ).as_json()
        
        if not ts:
            logger.warning(f"Reponse vide pour {symbol} ({td_symbol})")
            return None
        
        if isinstance(ts, dict):
            logger.warning(f"Reponse API est un dict (erreur) pour {symbol}: {str(ts)[:120]}")
            return None
        
        # ACCEPTER tuple ET list !
        if not isinstance(ts, (list, tuple)):
            logger.warning(f"Reponse type inattendu pour {symbol}: {type(ts)}")
            return None
        
        candles = []
        for row in reversed(ts):
            try:
                dt_str = row.get('datetime', '')
                if ' ' in dt_str:
                    dt = datetime.strptime(dt_str, '%Y-%m-%d %H:%M:%S')
                else:
                    dt = datetime.strptime(dt_str, '%Y-%m-%d')
                dt = pytz.utc.localize(dt).astimezone(US_TIMEZONE)
                
                candles.append({
                    'time': int(dt.timestamp()),
                    'open': safe_float(row.get('open', 0)),
                    'high': safe_float(row.get('high', 0)),
                    'low': safe_float(row.get('low', 0)),
                    'close': safe_float(row.get('close', 0)),
                    'volume': safe_float(row.get('volume', 0))
                })
            except Exception:
                continue
        
        if not candles:
            logger.warning(f"Aucune bougie valide pour {symbol}")
            return None
        
        logger.info(f"OK {symbol} ({td_symbol}) {period}: {len(candles)} bougies")
        return candles
    except Exception as e:
        logger.warning(f"Erreur candles {symbol}: {str(e)[:120]}")
        return None

# ============================================================
# FALLBACK FONDAMENTAL
# ============================================================
FUNDAMENTAL_FALLBACK = {
    'GLD': {'sector': 'Commodity', 'industry': 'Precious Metals', 'pe_ratio': 'N/A', 'dividend_yield': 0, 'market_cap': 65000000000, 'beta': 0.2},
    'SLV': {'sector': 'Commodity', 'industry': 'Precious Metals', 'pe_ratio': 'N/A', 'dividend_yield': 0, 'market_cap': 15000000000, 'beta': 0.4},
    'USO': {'sector': 'Commodity', 'industry': 'Energy', 'pe_ratio': 'N/A', 'dividend_yield': 0, 'market_cap': 3000000000, 'beta': 1.5},
    'BTC-USD': {'sector': 'Cryptocurrency', 'industry': 'Digital Asset', 'pe_ratio': 'N/A', 'dividend_yield': 0, 'market_cap': 1000000000000, 'beta': 2.5},
    'ETH-USD': {'sector': 'Cryptocurrency', 'industry': 'Digital Asset', 'pe_ratio': 'N/A', 'dividend_yield': 0, 'market_cap': 350000000000, 'beta': 2.0},
    'SOL-USD': {'sector': 'Cryptocurrency', 'industry': 'Digital Asset', 'pe_ratio': 'N/A', 'dividend_yield': 0, 'market_cap': 50000000000, 'beta': 2.2},
    'EURUSD=X': {'sector': 'Forex', 'industry': 'Currency', 'pe_ratio': 'N/A', 'dividend_yield': 0, 'market_cap': 'N/A', 'beta': 0.1},
    'GBPUSD=X': {'sector': 'Forex', 'industry': 'Currency', 'pe_ratio': 'N/A', 'dividend_yield': 0, 'market_cap': 'N/A', 'beta': 0.2},
    'USDJPY=X': {'sector': 'Forex', 'industry': 'Currency', 'pe_ratio': 'N/A', 'dividend_yield': 0, 'market_cap': 'N/A', 'beta': 0.15},
    'AAPL': {'sector': 'Technology', 'industry': 'Consumer Electronics', 'pe_ratio': 28.5, 'dividend_yield': 0.005, 'market_cap': 2800000000000, 'beta': 1.2},
    'MSFT': {'sector': 'Technology', 'industry': 'Software', 'pe_ratio': 32.0, 'dividend_yield': 0.008, 'market_cap': 2500000000000, 'beta': 0.9},
    'GOOGL': {'sector': 'Technology', 'industry': 'Internet', 'pe_ratio': 25.0, 'dividend_yield': 0, 'market_cap': 1600000000000, 'beta': 1.05},
    'NVDA': {'sector': 'Technology', 'industry': 'Semiconductors', 'pe_ratio': 45.0, 'dividend_yield': 0.001, 'market_cap': 1800000000000, 'beta': 1.5},
    'TSLA': {'sector': 'Automotive', 'industry': 'Electric Vehicles', 'pe_ratio': 60.0, 'dividend_yield': 0, 'market_cap': 800000000000, 'beta': 2.0},
    'AMZN': {'sector': 'Consumer', 'industry': 'E-commerce', 'pe_ratio': 35.0, 'dividend_yield': 0, 'market_cap': 1800000000000, 'beta': 1.2},
    'META': {'sector': 'Technology', 'industry': 'Social Media', 'pe_ratio': 22.0, 'dividend_yield': 0, 'market_cap': 1000000000000, 'beta': 1.3},
    'JPM': {'sector': 'Financial', 'industry': 'Banking', 'pe_ratio': 12.0, 'dividend_yield': 0.025, 'market_cap': 500000000000, 'beta': 1.1},
    'ML.PA': {'sector': 'Luxury', 'industry': 'Consumer Goods', 'pe_ratio': 28.0, 'dividend_yield': 0.015, 'market_cap': 400000000000, 'beta': 0.9},
    'SAN.PA': {'sector': 'Healthcare', 'industry': 'Pharmaceuticals', 'pe_ratio': 16.0, 'dividend_yield': 0.035, 'market_cap': 120000000000, 'beta': 0.6},
    'OR.PA': {'sector': 'Consumer', 'industry': 'Cosmetics', 'pe_ratio': 32.0, 'dividend_yield': 0.012, 'market_cap': 250000000000, 'beta': 0.7},
    'AI.PA': {'sector': 'Industrials', 'industry': 'Chemicals', 'pe_ratio': 20.0, 'dividend_yield': 0.02, 'market_cap': 100000000000, 'beta': 0.8},
    '^GSPC': {'sector': 'Index', 'industry': 'US Equity', 'pe_ratio': 'N/A', 'dividend_yield': 0.015, 'market_cap': 'N/A', 'beta': 1.0},
    '^DJI': {'sector': 'Index', 'industry': 'US Equity', 'pe_ratio': 'N/A', 'dividend_yield': 0.02, 'market_cap': 'N/A', 'beta': 0.9},
    '^IXIC': {'sector': 'Index', 'industry': 'US Equity', 'pe_ratio': 'N/A', 'dividend_yield': 0.005, 'market_cap': 'N/A', 'beta': 1.2},
    '^FCHI': {'sector': 'Index', 'industry': 'French Equity', 'pe_ratio': 'N/A', 'dividend_yield': 0.03, 'market_cap': 'N/A', 'beta': 0.8},
    '^GDAXI': {'sector': 'Index', 'industry': 'German Equity', 'pe_ratio': 'N/A', 'dividend_yield': 0.025, 'market_cap': 'N/A', 'beta': 0.9},
    '^N225': {'sector': 'Index', 'industry': 'Japanese Equity', 'pe_ratio': 'N/A', 'dividend_yield': 0.02, 'market_cap': 'N/A', 'beta': 0.7},
    '^FTSE': {'sector': 'Index', 'industry': 'UK Equity', 'pe_ratio': 'N/A', 'dividend_yield': 0.035, 'market_cap': 'N/A', 'beta': 0.8},
    'SPY': {'sector': 'ETF', 'industry': 'Index Fund', 'pe_ratio': 'N/A', 'dividend_yield': 0.015, 'market_cap': 450000000000, 'beta': 1.0},
    'QQQ': {'sector': 'ETF', 'industry': 'Index Fund', 'pe_ratio': 'N/A', 'dividend_yield': 0.006, 'market_cap': 200000000000, 'beta': 1.2},
    'DIA': {'sector': 'ETF', 'industry': 'Index Fund', 'pe_ratio': 'N/A', 'dividend_yield': 0.02, 'market_cap': 30000000000, 'beta': 0.9},
}

# ============================================================
# ROUTES
# ============================================================
@app.route('/static/<path:filename>')
def static_files(filename):
    return send_from_directory('static', filename)

@app.route('/favicon.ico')
def favicon():
    return '', 204

@app.route('/api/clear-cache')
def clear_cache():
    price_cache.clear()
    candles_cache.clear()
    insights_cache.clear()
    fundamental_cache.clear()
    rate_limiter['last_calls'] = []
    return jsonify({'status': 'ok'})

@app.route('/api/trading/<symbol>')
def get_trading(symbol):
    try:
        cached = get_cached(candles_cache, f"trading_{symbol}", CANDLES_CACHE_DURATION)
        if cached:
            return jsonify(cached)
        
        info = ASSETS.get(symbol, {
            'name': symbol, 'exchange': 'Market',
            'category': 'Autre', 'icon': '📈', 'color': '#33ff33'
        })
        
        result = {
            'symbol': symbol,
            'name': info.get('name', symbol),
            'exchange': info.get('exchange', 'Market'),
            'currency': 'USD',
            'category': info.get('category', 'Autre'),
            'icon': info.get('icon', '📈'),
            'color': info.get('color', '#33ff33'),
            'data': {}
        }
        
        for period in ['1d']:
            try:
                candles = fetch_candles_twelvedata(symbol, period)
                if not candles:
                    continue
                
                indicators = calculate_all_indicators(candles)
                close = [c['close'] for c in candles]
                high = [c['high'] for c in candles]
                low = [c['low'] for c in candles]
                
                result['data'][period] = {
                    'candles': candles,
                    'indicators': indicators,
                    'stats': {
                        'current_price': close[-1],
                        'change': close[-1] - close[-2] if len(close) > 1 else 0,
                        'change_percent': ((close[-1] - close[-2]) / close[-2] * 100) if len(close) > 1 and close[-2] != 0 else 0,
                        'high': max(high),
                        'low': min(low),
                        'volume': sum(c.get('volume', 0) for c in candles),
                        'open': close[0]
                    }
                }
            except Exception as e:
                logger.warning(f"Erreur {period} {symbol}: {e}")
                continue
        
        if not result['data']:
            return jsonify({'error': f'Aucune donnee pour {symbol}'}), 404
        
        if result['data'] and '1d' in result['data']:
            result['indicators'] = result['data']['1d']['indicators']
            result['fundamental'] = FUNDAMENTAL_FALLBACK.get(symbol, {})
            result['pe_ratio'] = result['fundamental'].get('pe_ratio', 'N/A')
            result['dividend_yield'] = result['fundamental'].get('dividend_yield', 'N/A')
            result['market_cap'] = result['fundamental'].get('market_cap', 0)
            result['sector'] = result['fundamental'].get('sector', 'N/A')
            result['beta'] = result['fundamental'].get('beta', 'N/A')
        
        set_cached(candles_cache, f"trading_{symbol}", result)
        return jsonify(result)
        
    except Exception as e:
        logger.error(f"Erreur trading {symbol}: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/insights/<symbol>')
def get_insights(symbol):
    return get_trading(symbol)

@app.route('/api/fundamental/<symbol>')
def get_fundamental(symbol):
    try:
        result = dict(FUNDAMENTAL_FALLBACK.get(symbol, {
            'sector': 'N/A', 'industry': 'N/A', 'pe_ratio': 'N/A',
            'dividend_yield': 'N/A', 'market_cap': 0, 'beta': 'N/A'
        }))
        result['symbol'] = symbol
        result['name'] = ASSETS.get(symbol, {}).get('name', symbol)
        return jsonify(result)
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/watchlist')
def get_watchlist():
    try:
        cached = get_cached(price_cache, "watchlist", PRICE_CACHE_DURATION)
        if cached:
            return jsonify(cached)
        
        results = []
        for symbol in ASSETS.keys():
            try:
                price = fetch_price_twelvedata(symbol)
                if price is None:
                    continue
                
                info = ASSETS.get(symbol, {})
                results.append({
                    'symbol': symbol,
                    'name': info.get('name', symbol),
                    'price': price,
                    'changePercent': 0,
                    'change': 0,
                    'currency': 'USD',
                    'category': info.get('category', 'Autre'),
                    'icon': info.get('icon', '📈'),
                    'sector': info.get('category', 'N/A')
                })
            except Exception as e:
                logger.warning(f"Watchlist {symbol}: {e}")
                continue
        
        set_cached(price_cache, "watchlist", results)
        return jsonify(results)
        
    except Exception as e:
        logger.error(f"Erreur watchlist: {e}")
        return jsonify([])

@app.route('/api/top-performers')
def get_top_performers():
    try:
        watchlist = get_cached(price_cache, "watchlist", PRICE_CACHE_DURATION)
        if watchlist:
            return jsonify(watchlist[:10])
        return jsonify([])
    except Exception as e:
        return jsonify([])

@app.route('/api/compare')
def compare_assets():
    try:
        symbols = request.args.get('symbols', '').split(',')
        if not symbols or len(symbols) < 2:
            return jsonify({'error': 'Au moins 2 symboles requis'}), 400
        
        results = []
        for symbol in symbols[:3]:
            try:
                candles = fetch_candles_twelvedata(symbol, '1mo')
                if not candles or len(candles) < 2:
                    continue
                
                close = [c['close'] for c in candles]
                current = close[-1]
                start = close[0]
                performance = ((current - start) / start) * 100
                returns = np.diff(close) / np.array(close[:-1])
                volatility = float(np.std(returns) * np.sqrt(252) * 100)
                
                info = ASSETS.get(symbol, {})
                results.append({
                    'symbol': symbol,
                    'name': info.get('name', symbol),
                    'current_price': current,
                    'performance': performance,
                    'volatility': volatility,
                    'icon': info.get('icon', '📈'),
                    'color': info.get('color', '#33ff33')
                })
            except Exception as e:
                logger.warning(f"Compare {symbol}: {e}")
                continue
        
        return jsonify(results)
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/export-csv/<symbol>')
def export_csv(symbol):
    try:
        candles = fetch_candles_twelvedata(symbol, '3mo')
        if not candles:
            return jsonify({'error': 'Pas de donnees'}), 404
        
        df = pd.DataFrame(candles)
        df['Date'] = pd.to_datetime(df['time'], unit='s').dt.strftime('%Y-%m-%d %H:%M:%S')
        df = df[['Date', 'open', 'high', 'low', 'close', 'volume']]
        df.columns = ['Date', 'Open', 'High', 'Low', 'Close', 'Volume']
        
        csv_data = df.to_csv(index=False)
        return csv_data, 200, {
            'Content-Type': 'text/csv',
            'Content-Disposition': f'attachment; filename={symbol}_data.csv'
        }
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/market-status')
def market_status():
    now = datetime.now(US_TIMEZONE)
    is_open = now.weekday() < 5 and 9 <= now.hour <= 16
    return jsonify({
        'status': 'open' if is_open else 'closed',
        'label': 'Ouvert' if is_open else 'Ferme',
        'icon': '🟢' if is_open else '🔴',
        'time': now.strftime('%H:%M:%S')
    })

@app.route('/')
def index():
    return render_template('monitor.html')

@socketio.on('connect')
def handle_connect():
    logger.info("Client connecte")
    emit('connected', {'status': 'connected', 'timestamp': datetime.now().isoformat()})

if __name__ == '__main__':
    os.makedirs('templates', exist_ok=True)
    os.makedirs('static/js', exist_ok=True)
    os.makedirs('static/css', exist_ok=True)

    print("=" * 70)
    print("TRADING MONITOR - TWELVE DATA (REAL-TIME)")
    print("=" * 70)
    print("http://localhost:5001")
    print("=" * 70)
    print(f"Cle API: {TWELVE_DATA_API_KEY[:8]}...")
    print(f"{len(ASSETS)} actifs disponibles")
    print("=" * 70)
    print("Rate limit: 5 req/min + intervalle min 12s")
    print("Fix: tuple accepte dans isinstance")
    print("=" * 70)

    socketio.run(app, host='0.0.0.0', port=5001, debug=False, use_reloader=False, allow_unsafe_werkzeug=True)