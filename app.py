import os
import logging
import time
import asyncio
from datetime import datetime, time as datetime_time
from dotenv import load_dotenv
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes
import yfinance as yf
import pandas as pd
import numpy as np
import ta
import requests
from flask import Flask
import threading
from telegram.error import BadRequest, Conflict

load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN")
TWELVE_DATA_API_KEY = os.getenv("TWELVE_DATA_API_KEY", "")
ALPHA_VANTAGE_API_KEY = os.getenv("ALPHA_VANTAGE_API_KEY", "")

if not BOT_TOKEN:
    raise ValueError("BOT_TOKEN не задан")

logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

RENDER_URL = "https://mega-trade-bot.onrender.com"  # ЗАМЕНИ НА СВОЙ URL
CANDLE_LIMITS = {'1m': 1000, '5m': 800, '15m': 600, '1h': 400, '4h': 300}

# ==================== БАННЕРЫ И ИКОНКИ ====================
WELCOME_BANNER = 'https://i.ibb.co/3Yjk8G6s/IMG-1470.jpg'
SIGNAL_IMAGES = {
    'LONG': 'https://i.ibb.co/0yRzq6zq/IMG-1465.jpg',
    'SHORT': 'https://i.ibb.co/zHR8CvM7/IMG-1466.jpg',
    'HOLD': 'https://i.ibb.co/N22CvHZr/IMG-1467.jpg'
}
ASSET_ICONS = {
    "AUD/USD OTC": "🇦🇺", "EUR/USD OTC": "🇪🇺", "EUR/RUB OTC": "🇪🇺🇷🇺",
    "GBP/JPY OTC": "🇬🇧🇯🇵", "USD/CAD OTC": "🇺🇸🇨🇦", "USD/CHF OTC": "🇺🇸🇨🇭",
    "USD/JPY OTC": "🇺🇸🇯🇵", "GBP/USD OTC": "🇬🇧🇺🇸",
    "BTC/USD OTC": "₿", "ETH/USD OTC": "⟠", "LTC/USD OTC": "Ł",
    "XRP/USD OTC": "✕", "SOL/USD OTC": "◎",
    "Gold OTC": "🥇", "Silver OTC": "🥈", "Oil OTC": "🛢️", "Natural Gas OTC": "🔥",
    "AAPL OTC": "🍎", "TSLA OTC": "🚗", "GOOGL OTC": "🔍",
    "AMZN OTC": "📦", "MSFT OTC": "💻", "NVDA OTC": "🎮",
    "S&P 500 OTC": "📊", "NASDAQ OTC": "💹", "Dow Jones OTC": "🏛️", "Nikkei 225 OTC": "🗾"
}

# ==================== МАППИНГ ТАЙМФРЕЙМОВ ====================
YFINANCE_INTERVAL_MAP = {
    '5s': '1m', '10s': '1m', '15s': '1m', '30s': '1m',
    '1m': '1m', '2m': '2m', '3m': '5m', '4m': '5m',
    '5m': '5m', '6m': '15m', '8m': '15m', '10m': '15m',
    '15m': '15m', '20m': '30m', '25m': '30m', '30m': '30m',
    '45m': '1h', '1h': '1h', '2h': '1h', '3h': '1h', '4h': '1h'
}
TWELVEDATA_INTERVAL_MAP = {
    '5s': '1min', '10s': '1min', '15s': '1min', '30s': '1min',
    '1m': '1min', '2m': '1min', '3m': '5min', '4m': '5min',
    '5m': '5min', '6m': '15min', '8m': '15min', '10m': '15min',
    '15m': '15min', '20m': '30min', '25m': '30min', '30m': '30min',
    '45m': '1h', '1h': '1h', '2h': '4h', '3h': '4h', '4h': '4h'
}
BINANCE_INTERVAL_MAP = {
    '5s': '1m', '10s': '1m', '15s': '1m', '30s': '1m',
    '1m': '1m', '2m': '1m', '3m': '5m', '4m': '5m',
    '5m': '5m', '6m': '15m', '8m': '15m', '10m': '15m',
    '15m': '15m', '20m': '30m', '25m': '30m', '30m': '30m',
    '45m': '1h', '1h': '1h', '2h': '4h', '3h': '4h', '4h': '4h'
}
COMMODITY_SYMBOLS = ['Gold', 'Silver', 'Oil', 'Natural Gas']
INDEX_SYMBOLS = ['S&P 500', 'NASDAQ', 'Dow Jones', 'Nikkei 225']

FOREX_LIST = [
    'AUDUSD', 'EURUSD', 'EURGBP', 'EURJPY', 'GBPJPY', 'USDCAD', 'USDCHF',
    'USDJPY', 'GBPUSD', 'NZDUSD', 'EURCHF', 'GBPAUD', 'AUDJPY', 'CADJPY',
    'CHFJPY', 'EURNZD', 'GBPCAD', 'GBPNZD', 'NZDCAD', 'AUDCAD', 'AUDCHF',
    'GBPCHF', 'USDCNH', 'USDHKD', 'USDMXN', 'USDSEK', 'USDSGD', 'USDZAR'
]

def get_timeframe_from_duration(duration, asset_name):
    if duration.endswith('s'):
        seconds = int(duration[:-1])
    elif duration.endswith('m'):
        seconds = int(duration[:-1]) * 60
    elif duration.endswith('h'):
        seconds = int(duration[:-1]) * 3600
    else:
        seconds = 60

    is_commodity = any(comm in asset_name for comm in COMMODITY_SYMBOLS)
    is_index = any(idx in asset_name for idx in INDEX_SYMBOLS)
    is_forex = asset_name in FOREX_LIST

    if is_index or is_commodity or is_forex:
        if seconds <= 900:
            return '15m'
        else:
            return '1h'

    if seconds <= 60:
        return '1m'
    elif seconds <= 300:
        return '5m'
    elif seconds <= 900:
        return '15m'
    elif seconds <= 3600:
        return '1h'
    else:
        return '1h'

def get_candle_limit(timeframe):
    return CANDLE_LIMITS.get(timeframe, 300)

# ==================== КОНФИГУРАЦИЯ АКТИВОВ ====================
SYMBOL_CONFIG = {
    "S&P 500": {"twelvedata": "SPX", "yfinance": "^GSPC", "primary": "twelvedata"},
    "NASDAQ": {"twelvedata": "COMP", "yfinance": "^IXIC", "primary": "twelvedata"},
    "DOW JONES": {"twelvedata": "DJI", "yfinance": "^DJI", "primary": "yfinance"},
    "NIKKEI 225": {"twelvedata": "N225", "yfinance": "^N225", "primary": "yfinance"},
    "GOLD": {"twelvedata": "XAUUSD", "yfinance": "GC=F", "primary": "twelvedata"},
    "SILVER": {"twelvedata": "XAGUSD", "yfinance": "SI=F", "primary": "yfinance"},
    "OIL": {"twelvedata": "WTI", "yfinance": "CL=F", "primary": "yfinance"},
    "NATURAL GAS": {"twelvedata": "NG", "yfinance": "NG=F", "primary": "yfinance"}
}
STOCK_ALTERNATIVES = {
    "GOOGL": ["GOOG"], "AMZN": ["AMZN"], "AAPL": ["AAPL"],
    "TSLA": ["TSLA"], "MSFT": ["MSFT"], "NVDA": ["NVDA"]
}
CRYPTO_LIST = ['BTC', 'ETH', 'LTC', 'XRP', 'SOL', 'ADA', 'DOT', 'LINK', 'BNB']

# ==================== ФУНКЦИИ ПАТТЕРНОВ ====================
def detect_candle_patterns(df):
    if len(df) < 2:
        return {'engulfing': 0, 'hammer': 0, 'doji': 0}
    last = df.iloc[-1]
    prev = df.iloc[-2]
    body = abs(last['close'] - last['open'])
    upper_wick = last['high'] - max(last['close'], last['open'])
    lower_wick = min(last['close'], last['open']) - last['low']
    total_range = last['high'] - last['low']

    bullish_engulfing = (last['close'] > last['open'] and prev['close'] < prev['open'] and last['close'] > prev['open'] and last['open'] < prev['close'])
    bearish_engulfing = (last['close'] < last['open'] and prev['close'] > prev['open'] and last['close'] < prev['open'] and last['open'] > prev['close'])
    engulfing = 1 if bullish_engulfing else -1 if bearish_engulfing else 0

    hammer = 0
    if total_range > 0 and lower_wick > 2 * body and upper_wick < body * 0.3:
        hammer = 1 if last['close'] > last['open'] else -1

    doji = 1 if body < total_range * 0.1 else 0
    return {'engulfing': engulfing, 'hammer': hammer, 'doji': doji}

def detect_morning_star(df):
    if len(df) < 3:
        return 0
    c1, c2, c3 = df.iloc[-3], df.iloc[-2], df.iloc[-1]
    if c1['close'] >= c1['open']:
        return 0
    body2 = abs(c2['close'] - c2['open'])
    range2 = c2['high'] - c2['low']
    if range2 == 0 or body2 / range2 > 0.3 or c2['high'] > c1['low']:
        return 0
    if c3['close'] <= c3['open'] or c3['close'] < (c1['open'] + c1['close']) / 2:
        return 0
    return 1

def detect_evening_star(df):
    if len(df) < 3:
        return 0
    c1, c2, c3 = df.iloc[-3], df.iloc[-2], df.iloc[-1]
    if c1['close'] <= c1['open']:
        return 0
    body2 = abs(c2['close'] - c2['open'])
    range2 = c2['high'] - c2['low']
    if range2 == 0 or body2 / range2 > 0.3 or c2['low'] < c1['high']:
        return 0
    if c3['close'] >= c3['open'] or c3['close'] > (c1['open'] + c1['close']) / 2:
        return 0
    return 1

def detect_hanging_man(df):
    if len(df) < 1:
        return 0
    last = df.iloc[-1]
    body = abs(last['close'] - last['open'])
    lower_wick = min(last['close'], last['open']) - last['low']
    upper_wick = last['high'] - max(last['close'], last['open'])
    if lower_wick > 2 * body and upper_wick < body * 0.3:
        return -1
    return 0

def detect_shooting_star(df):
    if len(df) < 1:
        return 0
    last = df.iloc[-1]
    body = abs(last['close'] - last['open'])
    upper_wick = last['high'] - max(last['close'], last['open'])
    lower_wick = min(last['close'], last['open']) - last['low']
    if upper_wick > 2 * body and lower_wick < body * 0.3:
        return -1
    return 0

def detect_double_bottom(df, lookback=30, tolerance=0.02):
    if len(df) < lookback:
        return 0
    recent = df.iloc[-lookback:]
    lows = recent['low']
    min1 = lows.idxmin()
    if min1 + 5 >= len(lows):
        return 0
    min2 = lows[min1+5:].idxmin() if min1+5 < len(lows) else None
    if min2 is None:
        return 0
    if abs(df.loc[min1, 'low'] - df.loc[min2, 'low']) / df.loc[min1, 'low'] > tolerance:
        return 0
    max_between = df.loc[min1:min2, 'high'].max()
    if max_between < max(df.loc[min1, 'high'], df.loc[min2, 'high']) * 1.02:
        return 0
    neck = max_between
    if df['close'].iloc[-1] > neck:
        avg_vol = df['volume'].iloc[-20:].mean()
        if df['volume'].iloc[-1] > avg_vol * 1.2:
            return 2
        return 1
    return 0

def detect_double_top(df, lookback=30, tolerance=0.02):
    if len(df) < lookback:
        return 0
    recent = df.iloc[-lookback:]
    highs = recent['high']
    max1 = highs.idxmax()
    if max1 + 5 >= len(highs):
        return 0
    max2 = highs[max1+5:].idxmax() if max1+5 < len(highs) else None
    if max2 is None:
        return 0
    if abs(df.loc[max1, 'high'] - df.loc[max2, 'high']) / df.loc[max1, 'high'] > tolerance:
        return 0
    min_between = df.loc[max1:max2, 'low'].min()
    if min_between > min(df.loc[max1, 'low'], df.loc[max2, 'low']) * 0.98:
        return 0
    neck = min_between
    if df['close'].iloc[-1] < neck:
        avg_vol = df['volume'].iloc[-20:].mean()
        if df['volume'].iloc[-1] > avg_vol * 1.2:
            return -2
        return -1
    return 0

def detect_head_shoulders(df, lookback=40):
    if len(df) < lookback:
        return 0
    recent = df.iloc[-lookback:]
    highs = recent['high']
    peaks = []
    for i in range(5, len(highs)-5):
        if highs.iloc[i] == highs.iloc[i-5:i+5].max():
            peaks.append((i, highs.iloc[i]))
    if len(peaks) < 3:
        return 0
    p1, p2, p3 = peaks[-3], peaks[-2], peaks[-1]
    if p2[1] > p1[1] and p2[1] > p3[1]:
        if abs(p1[1] - p3[1]) / p1[1] > 0.03:
            return 0
        neck1 = df.iloc[p1[0]:p2[0]]['low'].min()
        neck2 = df.iloc[p2[0]:p3[0]]['low'].min()
        neck = (neck1 + neck2) / 2
        if df['close'].iloc[-1] < neck:
            avg_vol = df['volume'].iloc[-20:].mean()
            if df['volume'].iloc[-1] > avg_vol * 1.2:
                return -2
            return -1
    lows = recent['low']
    valleys = []
    for i in range(5, len(lows)-5):
        if lows.iloc[i] == lows.iloc[i-5:i+5].min():
            valleys.append((i, lows.iloc[i]))
    if len(valleys) < 3:
        return 0
    v1, v2, v3 = valleys[-3], valleys[-2], valleys[-1]
    if v2[1] < v1[1] and v2[1] < v3[1]:
        if abs(v1[1] - v3[1]) / v1[1] > 0.03:
            return 0
        neck1 = df.iloc[v1[0]:v2[0]]['high'].max()
        neck2 = df.iloc[v2[0]:v3[0]]['high'].max()
        neck = (neck1 + neck2) / 2
        if df['close'].iloc[-1] > neck:
            avg_vol = df['volume'].iloc[-20:].mean()
            if df['volume'].iloc[-1] > avg_vol * 1.2:
                return 2
            return 1
    return 0

def calculate_pivot_points(df):
    if len(df) < 2:
        return None
    high = df['high'].max()
    low = df['low'].min()
    close = df['close'].iloc[-1]
    pivot = (high + low + close) / 3
    r1 = 2 * pivot - low
    s1 = 2 * pivot - high
    r2 = pivot + (high - low)
    s2 = pivot - (high - low)
    return {'pivot': pivot, 'r1': r1, 'r2': r2, 's1': s1, 's2': s2}

def volume_analysis(df):
    if len(df) < 20:
        return 0
    avg_volume = df['volume'].iloc[-20:].mean()
    current_volume = df['volume'].iloc[-1]
    if current_volume > avg_volume * 1.5:
        return 1
    elif current_volume < avg_volume * 0.5:
        return -1
    return 0

def get_session(time_utc):
    hour = time_utc.hour
    if 0 <= hour < 8:
        return "ASIA"
    elif 8 <= hour < 14:
        return "LONDON"
    elif 14 <= hour < 22:
        return "NEW_YORK"
    else:
        return "OVERLAP"

# ==================== ФУНКЦИИ ПОЛУЧЕНИЯ ДАННЫХ ====================
async def fetch_market_data_async(symbol, timeframe, limit=300):
    tasks = []
    if TWELVE_DATA_API_KEY:
        tasks.append(asyncio.to_thread(fetch_twelvedata, symbol, timeframe, limit))
    tasks.append(asyncio.to_thread(fetch_yfinance, symbol, timeframe, limit))
    tasks.append(asyncio.to_thread(fetch_binance, symbol, timeframe, limit))
    for task in asyncio.as_completed(tasks):
        try:
            df = await task
            if df is not None and not df.empty:
                return df
        except Exception as e:
            logger.debug(f"Ошибка в одном из источников: {e}")
            continue
    raise Exception("Не удалось получить данные ни из одного источника")

def get_market_data(symbol, timeframe, limit=300):
    try:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        result = loop.run_until_complete(fetch_market_data_async(symbol, timeframe, limit))
        loop.close()
        return result
    except Exception as e:
        logger.error(f"Ошибка получения данных: {e}")
        raise

def fetch_yfinance(symbol, timeframe, limit, is_index=False):
    # Не добавляем =X для индексов, фьючерсов и спецсимволов
    if not symbol.startswith('^') and not symbol.endswith('=F') and not symbol.endswith('=X'):
        if not is_index:
            symbol = symbol + '=X'
    interval = YFINANCE_INTERVAL_MAP.get(timeframe, timeframe)
    if timeframe == '4h':
        interval = '1h'
    time.sleep(3)
    ticker = yf.Ticker(symbol)
    df = ticker.history(period='30d', interval=interval)
    if df.empty:
        raise Exception("Нет данных Yahoo")
    if timeframe == '4h':
        df = df.resample('4h').agg({'Open':'first','High':'max','Low':'min','Close':'last','Volume':'sum'}).dropna()
    df = df.iloc[-limit:]
    return df[['Open','High','Low','Close','Volume']].rename(columns={'Open':'open','High':'high','Low':'low','Close':'close','Volume':'volume'})

def fetch_binance(symbol, timeframe, limit):
    from binance.client import Client
    client = Client()
    interval = BINANCE_INTERVAL_MAP.get(timeframe, '1m')
    if timeframe == '4h':
        interval = '4h'
    klines = client.get_klines(symbol=symbol.upper(), interval=interval, limit=limit)
    if not klines:
        raise Exception("Нет данных Binance")
    df = pd.DataFrame(klines, columns=['timestamp','open','high','low','close','volume','ct','qav','trades','tbbav','tbqav','ignore'])
    for c in ['open','high','low','close','volume']:
        df[c] = df[c].astype(float)
    return df[['open','high','low','close','volume']]

def fetch_twelvedata(symbol, timeframe, limit):
    interval = TWELVEDATA_INTERVAL_MAP.get(timeframe, '5min')
    url = "https://api.twelvedata.com/time_series"
    params = {'symbol':symbol, 'interval':interval, 'outputsize':limit, 'apikey':TWELVE_DATA_API_KEY}
    resp = requests.get(url, params=params, timeout=15)
    data = resp.json()
    if 'values' not in data or len(data['values']) == 0:
        raise Exception("Нет данных Twelve Data")
    df = pd.DataFrame(data['values'])
    for col in ['open','high','low','close']:
        if col not in df.columns:
            raise Exception(f"Нет колонки {col}")
    if 'volume' not in df.columns:
        df['volume'] = 0
    df = df.rename(columns={'open':'open','high':'high','low':'low','close':'close','volume':'volume'})
    for c in ['open','high','low','close','volume']:
        df[c] = df[c].astype(float)
    df = df.iloc[::-1].reset_index(drop=True)
    return df[['open','high','low','close','volume']]

def fetch_alphavantage(symbol, timeframe, limit):
    interval = {'5s':'1min','10s':'1min','15s':'1min','30s':'1min',
                '1m':'1min','2m':'1min','3m':'5min','4m':'5min',
                '5m':'5min','6m':'15min','8m':'15min','10m':'15min',
                '15m':'15min','20m':'30min','25m':'30min','30m':'30min',
                '45m':'60min','1h':'60min','2h':'60min','3h':'60min','4h':'60min'}.get(timeframe, '5min')
    url = f"https://www.alphavantage.co/query?function=TIME_SERIES_INTRADAY&symbol={symbol}&interval={interval}&apikey={ALPHA_VANTAGE_API_KEY}&outputsize=full"
    resp = requests.get(url, timeout=15)
    data = resp.json()
    if 'Time Series' not in data:
        raise Exception("Нет данных Alpha Vantage")
    df = pd.DataFrame.from_dict(data['Time Series'], orient='index')
    df.index = pd.to_datetime(df.index)
    df = df.sort_index()
    df = df.rename(columns={'1. open':'open','2. high':'high','3. low':'low','4. close':'close','5. volume':'volume'})
    df = df[['open','high','low','close','volume']].astype(float)
    df = df.iloc[-limit:]
    return df

# ==================== ОСНОВНАЯ ЛОГИКА СИГНАЛА ====================
def compute_advanced_indicators(df):
    close = df['close']
    high = df['high']
    low = df['low']
    volume = df['volume']

    rsi = ta.momentum.RSIIndicator(close, 14).rsi().iloc[-1] if not pd.isna(ta.momentum.RSIIndicator(close, 14).rsi().iloc[-1]) else 50
    macd = ta.trend.MACD(close)
    macd_diff = macd.macd_diff().iloc[-1] if not pd.isna(macd.macd_diff().iloc[-1]) else 0
    macd_line = macd.macd().iloc[-1] if not pd.isna(macd.macd().iloc[-1]) else 0
    macd_signal = macd.macd_signal().iloc[-1] if not pd.isna(macd.macd_signal().iloc[-1]) else 0
    ema9 = ta.trend.EMAIndicator(close, 9).ema_indicator().iloc[-1] if not pd.isna(ta.trend.EMAIndicator(close, 9).ema_indicator().iloc[-1]) else close.iloc[-1]
    ema21 = ta.trend.EMAIndicator(close, 21).ema_indicator().iloc[-1] if not pd.isna(ta.trend.EMAIndicator(close, 21).ema_indicator().iloc[-1]) else close.iloc[-1]
    bb_high = ta.volatility.BollingerBands(close, 20, 2).bollinger_hband().iloc[-1] if not pd.isna(ta.volatility.BollingerBands(close, 20, 2).bollinger_hband().iloc[-1]) else close.iloc[-1]
    bb_low = ta.volatility.BollingerBands(close, 20, 2).bollinger_lband().iloc[-1] if not pd.isna(ta.volatility.BollingerBands(close, 20, 2).bollinger_lband().iloc[-1]) else close.iloc[-1]
    stoch = ta.momentum.StochasticOscillator(high, low, close, 14, 3)
    stoch_k = stoch.stoch().iloc[-1] if not pd.isna(stoch.stoch().iloc[-1]) else 50
    stoch_d = stoch.stoch_signal().iloc[-1] if not pd.isna(stoch.stoch_signal().iloc[-1]) else 50
    adx = ta.trend.ADXIndicator(high, low, close, 14).adx().iloc[-1] if not pd.isna(ta.trend.ADXIndicator(high, low, close, 14).adx().iloc[-1]) else 25

    high_9 = high.rolling(9).max().iloc[-1]
    low_9 = low.rolling(9).min().iloc[-1]
    tenkan = (high_9 + low_9) / 2
    high_26 = high.rolling(26).max().iloc[-1]
    low_26 = low.rolling(26).min().iloc[-1]
    kijun = (high_26 + low_26) / 2
    ichimoku = 1 if close.iloc[-1] > tenkan and close.iloc[-1] > kijun else -1 if close.iloc[-1] < tenkan and close.iloc[-1] < kijun else 0

    atr = ta.volatility.AverageTrueRange(high, low, close, 10).average_true_range().iloc[-1] if not pd.isna(ta.volatility.AverageTrueRange(high, low, close, 10).average_true_range().iloc[-1]) else close.iloc[-1]*0.01
    upper = (high.iloc[-1] + low.iloc[-1])/2 + 3*atr
    lower = (high.iloc[-1] + low.iloc[-1])/2 - 3*atr
    supertrend = 1 if close.iloc[-1] > upper else -1 if close.iloc[-1] < lower else 0

    vwap = (volume * (high + low + close) / 3).sum() / volume.sum() if volume.sum() > 0 else close.iloc[-1]
    vwap_signal = 1 if close.iloc[-1] > vwap else -1 if close.iloc[-1] < vwap else 0

    def hma(series, period=20):
        half = int(period/2)
        sqrt_p = int(np.sqrt(period))
        wma_half = series.rolling(half).apply(lambda x: np.sum(np.arange(1, half+1)*x)/np.sum(np.arange(1, half+1)) if len(x)==half else np.nan, raw=True)
        wma_full = series.rolling(period).apply(lambda x: np.sum(np.arange(1, period+1)*x)/np.sum(np.arange(1, period+1)) if len(x)==period else np.nan, raw=True)
        hma_series = 2*wma_half - wma_full
        hma_series = hma_series.rolling(sqrt_p).apply(lambda x: np.sum(np.arange(1, sqrt_p+1)*x)/np.sum(np.arange(1, sqrt_p+1)) if len(x)==sqrt_p else np.nan, raw=True)
        return hma_series.iloc[-1] if not pd.isna(hma_series.iloc[-1]) else close.iloc[-1]
    hma_value = hma(close, 20)
    hma_signal = 1 if close.iloc[-1] > hma_value else -1 if close.iloc[-1] < hma_value else 0

    stoch_rsi = ta.momentum.StochRSIIndicator(close, 14, 3, 3)
    stoch_rsi_k = stoch_rsi.stochrsi_k().iloc[-1] if not pd.isna(stoch_rsi.stochrsi_k().iloc[-1]) else 50
    stoch_rsi_d = stoch_rsi.stochrsi_d().iloc[-1] if not pd.isna(stoch_rsi.stochrsi_d().iloc[-1]) else 50
    stoch_rsi_signal = 1 if stoch_rsi_k < 20 and stoch_rsi_d < 20 else -1 if stoch_rsi_k > 80 and stoch_rsi_d > 80 else 0

    patterns = {
        'engulfing': detect_candle_patterns(df)['engulfing'],
        'hammer': detect_candle_patterns(df)['hammer'],
        'doji': detect_candle_patterns(df)['doji'],
        'morning_star': detect_morning_star(df),
        'evening_star': detect_evening_star(df),
        'hanging_man': detect_hanging_man(df),
        'shooting_star': detect_shooting_star(df),
        'double_bottom': detect_double_bottom(df),
        'double_top': detect_double_top(df),
        'head_shoulders': detect_head_shoulders(df)
    }

    pivots = calculate_pivot_points(df)
    volume_score = volume_analysis(df)
    session = get_session(datetime.utcnow())

    return {
        'rsi': rsi, 'macd_diff': macd_diff, 'macd_line': macd_line,
        'macd_signal': macd_signal, 'ema9': ema9, 'ema21': ema21,
        'bb_high': bb_high, 'bb_low': bb_low,
        'stoch_k': stoch_k, 'stoch_d': stoch_d, 'adx': adx,
        'ichimoku': ichimoku, 'supertrend': supertrend,
        'vwap': vwap_signal, 'hma': hma_signal,
        'stoch_rsi': stoch_rsi_signal,
        'last_close': close.iloc[-1], 'atr': atr,
        'patterns': patterns,
        'pivots': pivots,
        'volume_score': volume_score,
        'session': session
    }

def get_weighted_signal(indicators, timeframe='1h'):
    weights = {
        'rsi': 2, 'macd': 3, 'ema': 2, 'bollinger': 1, 'stoch': 1,
        'adx': 2, 'ichimoku': 2, 'supertrend': 2, 'vwap': 1, 'hma': 1,
        'stoch_rsi': 1,
        'engulfing': 1.5, 'hammer': 1, 'doji': 0.5,
        'morning_star': 1.5, 'evening_star': 1.5,
        'hanging_man': 1.5, 'shooting_star': 1.5,
        'double_bottom': 2, 'double_top': 2,
        'head_shoulders': 2.5
    }
    if timeframe in ['1m', '5m']:
        for key in ['engulfing', 'hammer', 'morning_star', 'evening_star', 'hanging_man', 'shooting_star', 'double_bottom', 'double_top', 'head_shoulders']:
            weights[key] *= 0.7

    votes_long, votes_short = 0, 0
    reasons = []

    if indicators['rsi'] < 30:
        votes_long += weights['rsi']
        reasons.append(f"RSI={indicators['rsi']:.1f} (перепроданность)")
    elif indicators['rsi'] > 70:
        votes_short += weights['rsi']
        reasons.append(f"RSI={indicators['rsi']:.1f} (перекупленность)")

    if indicators['macd_diff'] > 0 and indicators['macd_line'] > indicators['macd_signal']:
        votes_long += weights['macd']
        reasons.append("MACD бычье")
    elif indicators['macd_diff'] < 0 and indicators['macd_line'] < indicators['macd_signal']:
        votes_short += weights['macd']
        reasons.append("MACD медвежье")

    if indicators['ema9'] > indicators['ema21']:
        votes_long += weights['ema']
        reasons.append("EMA9 > EMA21")
    else:
        votes_short += weights['ema']
        reasons.append("EMA9 < EMA21")

    last = indicators['last_close']
    if last <= indicators['bb_low']:
        votes_long += weights['bollinger']
        reasons.append("Цена у нижней полосы")
    elif last >= indicators['bb_high']:
        votes_short += weights['bollinger']
        reasons.append("Цена у верхней полосы")

    if indicators['stoch_k'] < 20 and indicators['stoch_d'] < 20:
        votes_long += weights['stoch']
        reasons.append("Stoch перепродан")
    elif indicators['stoch_k'] > 80 and indicators['stoch_d'] > 80:
        votes_short += weights['stoch']
        reasons.append("Stoch перекуплен")

    if indicators['adx'] > 25:
        if indicators['ema9'] > indicators['ema21']:
            votes_long += weights['adx']
            reasons.append(f"ADX={indicators['adx']:.1f} (тренд вверх)")
        else:
            votes_short += weights['adx']
            reasons.append(f"ADX={indicators['adx']:.1f} (тренд вниз)")

    if indicators['ichimoku'] > 0:
        votes_long += weights['ichimoku']
        reasons.append("Ichimoku бычий")
    elif indicators['ichimoku'] < 0:
        votes_short += weights['ichimoku']
        reasons.append("Ichimoku медвежий")

    if indicators['supertrend'] > 0:
        votes_long += weights['supertrend']
        reasons.append("SuperTrend бычий")
    elif indicators['supertrend'] < 0:
        votes_short += weights['supertrend']
        reasons.append("SuperTrend медвежий")

    if indicators['vwap'] > 0:
        votes_long += weights['vwap']
        reasons.append("Цена выше VWAP")
    elif indicators['vwap'] < 0:
        votes_short += weights['vwap']
        reasons.append("Цена ниже VWAP")

    if indicators['hma'] > 0:
        votes_long += weights['hma']
        reasons.append("HMA бычий")
    elif indicators['hma'] < 0:
        votes_short += weights['hma']
        reasons.append("HMA медвежий")

    if indicators['stoch_rsi'] > 0:
        votes_long += weights['stoch_rsi']
        reasons.append("Stoch RSI бычий")
    elif indicators['stoch_rsi'] < 0:
        votes_short += weights['stoch_rsi']
        reasons.append("Stoch RSI медвежий")

    p = indicators['patterns']
    if p['engulfing'] == 1:
        votes_long += weights['engulfing']
        reasons.append("Бычье поглощение")
    elif p['engulfing'] == -1:
        votes_short += weights['engulfing']
        reasons.append("Медвежье поглощение")
    if p['hammer'] == 1:
        votes_long += weights['hammer']
        reasons.append("Молот (бычий)")
    elif p['hammer'] == -1:
        votes_short += weights['hammer']
        reasons.append("Молот (медвежий)")
    if p['doji'] == 1:
        votes_long += 0.5
        votes_short += 0.5
        reasons.append("Доджи (разворот)")
    if p['morning_star'] == 1:
        votes_long += weights['morning_star']
        reasons.append("Утренняя звезда (бычья)")
    if p['evening_star'] == 1:
        votes_short += weights['evening_star']
        reasons.append("Вечерняя звезда (медвежья)")
    if p['hanging_man'] == -1:
        votes_short += weights['hanging_man']
        reasons.append("Повешенный (медвежий)")
    if p['shooting_star'] == -1:
        votes_short += weights['shooting_star']
        reasons.append("Падающая звезда (медвежья)")
    if p['double_bottom'] == 2:
        votes_long += weights['double_bottom'] * 1.2
        reasons.append("Двойное дно (сильное, с объёмом)")
    elif p['double_bottom'] == 1:
        votes_long += weights['double_bottom']
        reasons.append("Двойное дно (бычье)")
    if p['double_top'] == -2:
        votes_short += weights['double_top'] * 1.2
        reasons.append("Двойная вершина (сильная, с объёмом)")
    elif p['double_top'] == -1:
        votes_short += weights['double_top']
        reasons.append("Двойная вершина (медвежья)")
    if p['head_shoulders'] == 2:
        votes_long += weights['head_shoulders'] * 1.2
        reasons.append("Перевёрнутые голова и плечи (сильные)")
    elif p['head_shoulders'] == 1:
        votes_long += weights['head_shoulders']
        reasons.append("Перевёрнутые голова и плечи (бычьи)")
    elif p['head_shoulders'] == -2:
        votes_short += weights['head_shoulders'] * 1.2
        reasons.append("Голова и плечи (сильные, с объёмом)")
    elif p['head_shoulders'] == -1:
        votes_short += weights['head_shoulders']
        reasons.append("Голова и плечи (медвежьи)")

    pivots = indicators['pivots']
    if pivots:
        if last <= pivots['s1']:
            votes_long += 1
            reasons.append(f"Цена у поддержки S1 ({pivots['s1']:.4f})")
        elif last >= pivots['r1']:
            votes_short += 1
            reasons.append(f"Цена у сопротивления R1 ({pivots['r1']:.4f})")
        if last <= pivots['s2']:
            votes_long += 1.5
            reasons.append(f"Цена у сильной поддержки S2 ({pivots['s2']:.4f})")
        elif last >= pivots['r2']:
            votes_short += 1.5
            reasons.append(f"Цена у сильного сопротивления R2 ({pivots['r2']:.4f})")

    volume_score = indicators['volume_score']
    if volume_score == 1:
        if votes_long > votes_short:
            votes_long += 1
            reasons.append("Объём подтверждает тренд")
        else:
            votes_short += 1
            reasons.append("Объём подтверждает тренд")
    elif volume_score == -1:
        if votes_long > votes_short:
            votes_short += 1
            reasons.append("Низкий объём – возможен разворот")
        else:
            votes_long += 1
            reasons.append("Низкий объём – возможен разворот")

    session = indicators['session']
    if session == "ASIA":
        reasons.append("Азиатская сессия (сниженная волатильность)")
    elif session == "LONDON":
        reasons.append("Лондонская сессия (высокая волатильность)")
    elif session == "NEW_YORK":
        reasons.append("Нью-Йоркская сессия (высокая волатильность)")

    if votes_long > votes_short and votes_long >= 5:
        signal = 'LONG'
        final_reason = f"Бычий перевес ({votes_long:.1f} vs {votes_short:.1f}). " + ", ".join(reasons)
    elif votes_short > votes_long and votes_short >= 5:
        signal = 'SHORT'
        final_reason = f"Медвежий перевес ({votes_short:.1f} vs {votes_long:.1f}). " + ", ".join(reasons)
    else:
        signal = 'HOLD'
        final_reason = f"Нет явного перевеса ({votes_long:.1f}L, {votes_short:.1f}S). " + ", ".join(reasons)

    return signal, final_reason

def get_multi_timeframe_alignment(asset, primary_tf):
    tf_list = ['1h', '4h']
    signals = []
    for tf in tf_list:
        if tf == primary_tf:
            continue
        try:
            df = get_market_data(asset, tf, limit=200)
            if df is not None and not df.empty:
                ind = compute_advanced_indicators(df)
                sig, _ = get_weighted_signal(ind)
                signals.append(sig)
            else:
                signals.append('HOLD')
        except:
            signals.append('HOLD')
    long_count = signals.count('LONG')
    short_count = signals.count('SHORT')
    return long_count, short_count

def calculate_risk_parameters(df, entry_price):
    try:
        atr = ta.volatility.AverageTrueRange(df['high'], df['low'], df['close'], 14).average_true_range().iloc[-1]
        if pd.isna(atr) or atr == 0:
            atr = df['close'].iloc[-1] * 0.01
        return {'stop_loss': entry_price - 2*atr, 'take_profit': entry_price + 3*atr, 'atr': atr}
    except:
        return {'stop_loss': entry_price * 0.98, 'take_profit': entry_price * 1.03, 'atr': entry_price * 0.01}

def generate_signal(asset, duration):
    timeframe = get_timeframe_from_duration(duration, asset)
    limit = get_candle_limit(timeframe)
    logger.info(f"Авто-таймфрейм: {timeframe}, лимит: {limit} для {duration} (актив: {asset})")

    clean_asset = asset.replace(" OTC", "").replace("/", "").strip()
    df = get_market_data(clean_asset, timeframe, limit=limit)
    if df is None or df.empty:
        return {'signal': 'HOLD', 'strength': 'WEAK', 'emoji': '⚪', 'reason': 'Нет данных', 'indicators': None, 'risk': None, 'timeframe': timeframe}

    ind = compute_advanced_indicators(df)
    primary_signal, reason = get_weighted_signal(ind, timeframe)

    long_tf, short_tf = get_multi_timeframe_alignment(clean_asset, timeframe)
    tf_boost = 0
    if primary_signal == 'LONG' and long_tf >= 2:
        tf_boost = 1
    elif primary_signal == 'SHORT' and short_tf >= 2:
        tf_boost = 1
    elif primary_signal == 'LONG' and short_tf >= 2:
        tf_boost = -1
    elif primary_signal == 'SHORT' and long_tf >= 2:
        tf_boost = -1

    if primary_signal == 'HOLD':
        final_signal = 'HOLD'
        strength = 'WEAK'
        emoji = '⚪'
    else:
        if tf_boost == 1:
            strength = 'STRONG'
            final_signal = primary_signal
        elif tf_boost == -1:
            strength = 'WEAK'
            final_signal = 'HOLD'
        else:
            strength = 'MEDIUM'
            final_signal = primary_signal

        if final_signal == 'LONG' and strength == 'STRONG':
            emoji = '🟢'
        elif final_signal == 'LONG' and strength == 'MEDIUM':
            emoji = '🟡'
        elif final_signal == 'LONG' and strength == 'WEAK':
            emoji = '🟠'
        elif final_signal == 'SHORT' and strength == 'STRONG':
            emoji = '🔴'
        elif final_signal == 'SHORT' and strength == 'MEDIUM':
            emoji = '🟠'
        elif final_signal == 'SHORT' and strength == 'WEAK':
            emoji = '🟡'
        else:
            emoji = '⚪'

    risk = calculate_risk_parameters(df, ind['last_close'])
    full_reason = f"{reason}\nТаймфрейм: {timeframe} (авто), свечей: {len(df)}\nМульти-ТФ: {long_tf} LONG, {short_tf} SHORT на 1H/4H"
    if tf_boost == 1:
        full_reason += " → усиление сигнала"
    elif tf_boost == -1:
        full_reason += " → противоречие, сигнал ослаблен"

    return {
        'signal': final_signal,
        'strength': strength,
        'emoji': emoji,
        'reason': full_reason,
        'indicators': ind,
        'risk': risk,
        'timeframe': timeframe
    }

# ==================== МЕНЮ ====================
CURRENCIES = ["AUD/USD OTC","EUR/USD OTC","EUR/RUB OTC","GBP/JPY OTC",
              "USD/CAD OTC","USD/CHF OTC","USD/JPY OTC","GBP/USD OTC"]
CRYPTO = ["BTC/USD OTC","ETH/USD OTC","LTC/USD OTC","XRP/USD OTC","SOL/USD OTC"]
COMMODITIES = ["Gold OTC","Silver OTC","Oil OTC","Natural Gas OTC"]
STOCKS = ["AAPL OTC","TSLA OTC","GOOGL OTC","AMZN OTC","MSFT OTC","NVDA OTC"]
INDICES = ["S&P 500 OTC","NASDAQ OTC","Dow Jones OTC","Nikkei 225 OTC"]

DURATIONS = ["5s","10s","15s","30s","1m","2m","3m","4m","5m","6m","8m","10m","15m","20m","25m","30m","45m","1h","2h","3h","4h"]

def build_keyboard(items, back=False, back_data=None, cols=2):
    keyboard = []
    row = []
    for item in items:
        row.append(InlineKeyboardButton(item, callback_data=item))
        if len(row) == cols:
            keyboard.append(row)
            row = []
    if row:
        keyboard.append(row)
    if back:
        keyboard.append([InlineKeyboardButton("🔙 Назад", callback_data=back_data or "back")])
    return InlineKeyboardMarkup(keyboard)

# ==================== ОБРАБОТЧИКИ ====================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = ("🚀 *Торговый бот-ассистент*\n\n"
            "Я анализирую рынок и даю сигналы по активам из Pocket Option.\n"
            "Нажми **GO!** чтобы начать.")
    keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("GO!", callback_data="go")]])
    await update.message.reply_photo(
        photo=WELCOME_BANNER,
        caption=text,
        parse_mode='Markdown',
        reply_markup=keyboard
    )

async def go(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    keyboard = [
        [InlineKeyboardButton("💱 Валюты", callback_data="currencies")],
        [InlineKeyboardButton("🪙 Криптовалюты", callback_data="crypto")],
        [InlineKeyboardButton("🛢️ Сырьевые", callback_data="commodities")],
        [InlineKeyboardButton("📈 Акции", callback_data="stocks")],
        [InlineKeyboardButton("📊 Индексы", callback_data="indices")]
    ]
    try:
        await query.message.delete()
    except:
        pass
    await update.effective_chat.send_message(
        "Выберите раздел:",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

async def section_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    section = query.data
    if section == "currencies":
        items, title = CURRENCIES, "💱 Валютные пары"
    elif section == "crypto":
        items, title = CRYPTO, "🪙 Криптовалюты"
    elif section == "commodities":
        items, title = COMMODITIES, "🛢️ Сырьевые товары"
    elif section == "stocks":
        items, title = STOCKS, "📈 Акции"
    elif section == "indices":
        items, title = INDICES, "📊 Индексы"
    else:
        await query.edit_message_text("Ошибка")
        return
    keyboard = build_keyboard(items, back=True, back_data="go")
    await query.edit_message_text(f"{title} (выберите актив):", reply_markup=keyboard)

async def asset_selected(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    asset = query.data
    if asset in ['go', 'currencies', 'crypto', 'commodities', 'stocks', 'indices']:
        return
    context.user_data['asset'] = asset
    icon = ASSET_ICONS.get(asset, "")
    text = f"{icon} *{asset}*\n\nВыберите время сделки:"
    keyboard = build_keyboard(DURATIONS, back=True, back_data="back_to_section")
    try:
        await query.edit_message_text(text, parse_mode='Markdown', reply_markup=keyboard)
    except BadRequest as e:
        if "Message is not modified" in str(e):
            pass
        else:
            raise

async def duration_selected(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if context.user_data.get('processing', False):
        await query.answer("⏳ Уже идёт анализ...")
        return
    context.user_data['processing'] = True

    try:
        await query.answer()
        duration = query.data
        if duration in ['back_to_asset', 'back_to_section', 'go', 'home']:
            return

        asset = context.user_data.get('asset')
        if not asset or asset in ['back_to_asset', 'back_to_section', 'go', 'home']:
            await query.edit_message_text("⚠️ Ошибка: выберите актив заново.")
            return

        context.user_data['duration'] = duration
        icon = ASSET_ICONS.get(asset, "")
        await query.edit_message_text(f"{icon} ⏳ Анализирую рынок...")

        clean_asset = asset.replace(" OTC", "").replace("/", "").strip()
        result = await asyncio.wait_for(
            asyncio.to_thread(generate_signal, clean_asset, duration),
            timeout=30.0
        )

        signal = result['signal']
        strength = result['strength']
        emoji = result['emoji']
        reason = result['reason']
        ind = result['indicators']
        risk = result['risk']
        price = ind['last_close']
        tf = result['timeframe']

        msg = (f"{emoji} *{signal}* ({strength})\n"
               f"{icon} Актив: {asset}\n"
               f"⏱ Таймфрейм: {tf} (авто)\n"
               f"⏳ Время сделки: {duration}\n"
               f"💰 Цена: {price:.4f}\n\n"
               f"📊 *Индикаторы:*\n"
               f"RSI: {ind['rsi']:.1f}\n"
               f"MACD: {ind['macd_diff']:.4f}\n"
               f"EMA9: {ind['ema9']:.4f}, EMA21: {ind['ema21']:.4f}\n"
               f"Stoch: K={ind['stoch_k']:.1f}, D={ind['stoch_d']:.1f}\n"
               f"ADX: {ind['adx']:.1f}\n"
               f"Ichimoku: {ind['ichimoku']}\n"
               f"SuperTrend: {ind['supertrend']}\n"
               f"VWAP: {ind['vwap']}\n"
               f"HMA: {ind['hma']}\n"
               f"Stoch RSI: {ind['stoch_rsi']}\n\n"
               f"🛡️ *Риск:*\n"
               f"Stop-Loss: {risk['stop_loss']:.4f}\n"
               f"Take-Profit: {risk['take_profit']:.4f}\n"
               f"ATR: {risk['atr']:.4f}\n\n"
               f"ℹ️ {reason}")

        keyboard = [
            [InlineKeyboardButton("🔄 Дай сигнал ещё раз", callback_data="resignal")],
            [InlineKeyboardButton("🏠 Назад в меню", callback_data="home")]
        ]

        image_url = SIGNAL_IMAGES.get(signal, SIGNAL_IMAGES['HOLD'])
        try:
            await query.message.delete()
        except:
            pass
        await update.effective_chat.send_photo(
            photo=image_url,
            caption=msg,
            parse_mode='Markdown',
            reply_markup=InlineKeyboardMarkup(keyboard)
        )

    except asyncio.TimeoutError:
        logger.error("Timeout in duration_selected")
        keyboard = [[InlineKeyboardButton("🏠 Назад в меню", callback_data="home")]]
        await update.effective_chat.send_message(
            "⏰ Превышено время ожидания. Попробуйте позже.",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
    except Exception as e:
        logger.error(f"duration_selected error: {e}")
        keyboard = [[InlineKeyboardButton("🏠 Назад в меню", callback_data="home")]]
        error_msg = f"❌ Ошибка: {str(e)}"
        if "Нет данных" in str(e) or "No data" in str(e):
            error_msg = f"❌ Для {asset} на таймфрейме {timeframe} нет данных. Попробуйте выбрать больший таймфрейм (например, 15m или 1h)."
        await update.effective_chat.send_message(
            error_msg,
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
    finally:
        context.user_data['processing'] = False

async def resignal(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if context.user_data.get('processing', False):
        await query.answer("⏳ Уже идёт анализ...")
        return
    context.user_data['processing'] = True

    try:
        await query.answer()
        asset = context.user_data.get('asset')
        duration = context.user_data.get('duration')
        if not asset or not duration:
            await query.edit_message_text("Ошибка: данные потеряны. Начните заново /start")
            return
        if asset in ['back_to_asset', 'back_to_section', 'go', 'home']:
            await query.edit_message_text("Ошибка: выберите актив заново.")
            return

        icon = ASSET_ICONS.get(asset, "")
        try:
            await query.message.delete()
        except:
            pass
        temp_msg = await update.effective_chat.send_message(f"{icon} ⏳ Анализирую рынок...")

        clean_asset = asset.replace(" OTC", "").replace("/", "").strip()
        result = await asyncio.wait_for(
            asyncio.to_thread(generate_signal, clean_asset, duration),
            timeout=30.0
        )

        signal = result['signal']
        strength = result['strength']
        emoji = result['emoji']
        reason = result['reason']
        ind = result['indicators']
        risk = result['risk']
        price = ind['last_close']
        tf = result['timeframe']

        msg = (f"{emoji} *{signal}* ({strength})\n"
               f"{icon} Актив: {asset}\n"
               f"⏱ Таймфрейм: {tf} (авто)\n"
               f"⏳ Время сделки: {duration}\n"
               f"💰 Цена: {price:.4f}\n\n"
               f"📊 *Индикаторы:*\n"
               f"RSI: {ind['rsi']:.1f}\n"
               f"MACD: {ind['macd_diff']:.4f}\n"
               f"EMA9: {ind['ema9']:.4f}, EMA21: {ind['ema21']:.4f}\n"
               f"Stoch: K={ind['stoch_k']:.1f}, D={ind['stoch_d']:.1f}\n"
               f"ADX: {ind['adx']:.1f}\n"
               f"Ichimoku: {ind['ichimoku']}\n"
               f"SuperTrend: {ind['supertrend']}\n"
               f"VWAP: {ind['vwap']}\n"
               f"HMA: {ind['hma']}\n"
               f"Stoch RSI: {ind['stoch_rsi']}\n\n"
               f"🛡️ *Риск:*\n"
               f"Stop-Loss: {risk['stop_loss']:.4f}\n"
               f"Take-Profit: {risk['take_profit']:.4f}\n"
               f"ATR: {risk['atr']:.4f}\n\n"
               f"ℹ️ {reason}")

        keyboard = [
            [InlineKeyboardButton("🔄 Дай сигнал ещё раз", callback_data="resignal")],
            [InlineKeyboardButton("🏠 Назад в меню", callback_data="home")]
        ]

        image_url = SIGNAL_IMAGES.get(signal, SIGNAL_IMAGES['HOLD'])
        await update.effective_chat.send_photo(
            photo=image_url,
            caption=msg,
            parse_mode='Markdown',
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        try:
            await temp_msg.delete()
        except:
            pass

    except asyncio.TimeoutError:
        logger.error("Timeout in resignal")
        keyboard = [[InlineKeyboardButton("🏠 Назад в меню", callback_data="home")]]
        await update.effective_chat.send_message(
            "⏰ Превышено время ожидания. Попробуйте позже.",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
    except Exception as e:
        logger.error(f"resignal error: {e}")
        keyboard = [[InlineKeyboardButton("🏠 Назад в меню", callback_data="home")]]
        await update.effective_chat.send_message(
            f"❌ Ошибка: {str(e)}",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
    finally:
        context.user_data['processing'] = False

async def back_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    back_to = query.data
    if back_to == "back_to_section":
        await go(update, context)
    elif back_to == "back_to_asset":
        asset = context.user_data.get('asset')
        if asset:
            await asset_selected(update, context)
        else:
            await go(update, context)
    elif back_to == "go":
        await go(update, context)
    elif back_to == "home":
        await go(update, context)
    else:
        await go(update, context)

async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logger.error(f"Update {update} caused error {context.error}")

# ==================== ЗАПУСК ====================
def run_bot():
    while True:
        try:
            app = Application.builder().token(BOT_TOKEN).build()
            app.add_handler(CommandHandler("start", start))
            app.add_handler(CallbackQueryHandler(go, pattern="^go$"))
            app.add_handler(CallbackQueryHandler(section_handler, pattern="^(currencies|crypto|commodities|stocks|indices)$"))
            app.add_handler(CallbackQueryHandler(asset_selected, pattern="^(" + "|".join(CURRENCIES+CRYPTO+COMMODITIES+STOCKS+INDICES) + ")$"))
            app.add_handler(CallbackQueryHandler(duration_selected, pattern="^(" + "|".join(DURATIONS) + ")$"))
            app.add_handler(CallbackQueryHandler(resignal, pattern="^resignal$"))
            app.add_handler(CallbackQueryHandler(back_handler, pattern="^(back_to_section|back_to_asset|go|home)$"))
            app.add_error_handler(error_handler)

            logger.info("Бот запущен!")
            app.run_polling(allowed_updates=Update.ALL_TYPES)
            break
        except Conflict as e:
            logger.warning(f"Conflict: {e}. Перезапуск через 10 секунд...")
            time.sleep(10)
            continue
        except Exception as e:
            logger.error(f"Бот упал с ошибкой: {e}. Перезапуск через 10 секунд...")
            time.sleep(10)
            continue

def main():
    flask_app = Flask(__name__)
    @flask_app.route('/')
    def home():
        return "Bot is running!"

    def run_flask():
        flask_app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 10000)))

    threading.Thread(target=run_flask, daemon=True).start()
    logger.info("Flask запущен")

    def keep_alive():
        while True:
            try:
                requests.get(RENDER_URL, timeout=5)
                logger.info("✅ Self-ping успешен")
            except Exception as e:
                logger.warning(f"❌ Self-ping ошибка: {e}")
            time.sleep(60)

    threading.Thread(target=keep_alive, daemon=True).start()
    run_bot()

if __name__ == "__main__":
    main()