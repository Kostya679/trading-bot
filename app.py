import os
import logging
import time
from datetime import datetime
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
from telegram.error import BadRequest

load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN")
TWELVE_DATA_API_KEY = os.getenv("TWELVE_DATA_API_KEY", "")
ALPHA_VANTAGE_API_KEY = os.getenv("ALPHA_VANTAGE_API_KEY", "")

if not BOT_TOKEN:
    raise ValueError("BOT_TOKEN не задан")

logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

# ==================== БАННЕРЫ ====================
BANNER_IMAGES = {
    'welcome': 'https://i.ibb.co/3Yjk8G6s/IMG-1470.jpg',
    'sections': 'https://i.ibb.co/wN0z4Vvy/IMG-1471.jpg'
}

# ==================== КАРТИНКИ ДЛЯ СИГНАЛОВ ====================
SIGNAL_IMAGES = {
    'LONG': 'https://i.ibb.co/0yRzq6zq/IMG-1465.jpg',
    'SHORT': 'https://i.ibb.co/zHR8CvM7/IMG-1466.jpg',
    'HOLD': 'https://i.ibb.co/N22CvHZr/IMG-1467.jpg'
}

# ==================== ИКОНКИ АКТИВОВ ====================
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
    if is_commodity:
        if seconds <= 900:
            return '15m'
        else:
            return '1h'
    else:
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
    return {'1m':500, '5m':400, '15m':300, '1h':200}.get(timeframe, 300)

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

FOREX_LIST = [
    'AUDUSD', 'EURUSD', 'EURGBP', 'EURJPY', 'GBPJPY', 'USDCAD', 'USDCHF',
    'USDJPY', 'GBPUSD', 'NZDUSD', 'EURCHF', 'GBPAUD', 'AUDJPY', 'CADJPY',
    'CHFJPY', 'EURNZD', 'GBPCAD', 'GBPNZD', 'NZDCAD', 'AUDCAD', 'AUDCHF',
    'GBPCHF', 'USDCNH', 'USDHKD', 'USDMXN', 'USDSEK', 'USDSGD', 'USDZAR'
]

CRYPTO_LIST = ['BTC', 'ETH', 'LTC', 'XRP', 'SOL', 'ADA', 'DOT', 'LINK', 'BNB']

# ==================== ФУНКЦИИ ПОЛУЧЕНИЯ ДАННЫХ ====================
def get_market_data(symbol, timeframe, limit=300):
    clean = symbol.upper().replace('=X', '').replace('_OTC', '').replace('USDT', '').replace('BUSD', '')
    clean = clean.replace('/', '')
    if clean in ['BACK_TO_ASSET', 'BACK_TO_SECTION', 'GO', 'HOME']:
        raise Exception("Служебная кнопка")

    is_crypto = any(clean.startswith(c) for c in CRYPTO_LIST)
    if is_crypto:
        base = next((c for c in CRYPTO_LIST if clean.startswith(c)), None)
        if base:
            try:
                symbol_binance = f"{base}USDT"
                logger.info(f"Крипто: {symbol_binance} через Binance")
                return fetch_binance(symbol_binance, timeframe, limit)
            except Exception as e:
                logger.warning(f"Binance ошибка: {e}")
                yf_sym = f"{base}-USD"
                try:
                    return fetch_yfinance(yf_sym, timeframe, limit)
                except:
                    pass
        raise Exception("Нет данных для криптовалюты")

    if clean in SYMBOL_CONFIG:
        cfg = SYMBOL_CONFIG[clean]
        primary = cfg.get('primary', 'twelvedata')
        if primary == 'twelvedata' and TWELVE_DATA_API_KEY:
            try:
                td_sym = cfg['twelvedata']
                return fetch_twelvedata(td_sym, timeframe, limit)
            except Exception as e:
                logger.warning(f"Twelve Data primary ошибка: {e}")
        if primary == 'yfinance':
            yf_sym = cfg['yfinance']
            try:
                return fetch_yfinance(yf_sym, timeframe, limit, is_index=True)
            except Exception as e:
                logger.warning(f"Yahoo primary ошибка: {e}")
        if primary == 'twelvedata' and cfg.get('yfinance'):
            try:
                yf_sym = cfg['yfinance']
                return fetch_yfinance(yf_sym, timeframe, limit, is_index=True)
            except Exception as e:
                logger.warning(f"Yahoo резерв ошибка: {e}")
        if ALPHA_VANTAGE_API_KEY:
            try:
                av_sym = cfg.get('twelvedata', clean)
                return fetch_alphavantage(av_sym, timeframe, limit)
            except Exception as e:
                logger.warning(f"Alpha Vantage ошибка: {e}")
        raise Exception("Нет данных для индекса/сырья")

    # Акции
    if TWELVE_DATA_API_KEY:
        try:
            return fetch_twelvedata(clean, timeframe, limit)
        except Exception as e:
            logger.warning(f"Twelve Data ошибка акции: {e}")
    yf_symbols = [clean] + STOCK_ALTERNATIVES.get(clean, [])
    for sym in yf_symbols:
        try:
            return fetch_yfinance(sym, timeframe, limit)
        except Exception as e:
            logger.warning(f"Yahoo ошибка {sym}: {e}")

    # Валюты
    if clean in FOREX_LIST:
        if TWELVE_DATA_API_KEY:
            try:
                td_sym = f"{clean[:3]}/{clean[3:]}" if len(clean)==6 else clean
                return fetch_twelvedata(td_sym, timeframe, limit)
            except Exception as e:
                logger.warning(f"Twelve Data валюты ошибка: {e}")
        yf_sym = f"{clean}=X"
        try:
            return fetch_yfinance(yf_sym, timeframe, limit)
        except Exception as e:
            logger.warning(f"Yahoo валюты ошибка: {e}")

    raise Exception("Нет данных")

def fetch_yfinance(symbol, timeframe, limit, is_index=False):
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

# ==================== РАСШИРЕННЫЕ ИНДИКАТОРЫ ====================
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

    return {
        'rsi': rsi, 'macd_diff': macd_diff, 'macd_line': macd_line,
        'macd_signal': macd_signal, 'ema9': ema9, 'ema21': ema21,
        'bb_high': bb_high, 'bb_low': bb_low,
        'stoch_k': stoch_k, 'stoch_d': stoch_d, 'adx': adx,
        'ichimoku': ichimoku, 'supertrend': supertrend,
        'vwap': vwap_signal, 'hma': hma_signal,
        'stoch_rsi': stoch_rsi_signal,
        'last_close': close.iloc[-1], 'atr': atr
    }

def get_weighted_signal(indicators):
    weights = {'rsi':2,'macd':3,'ema':2,'bollinger':1,'stoch':1,
               'adx':2,'ichimoku':2,'supertrend':2,'vwap':1,'hma':1,'stoch_rsi':1}
    votes_long, votes_short = 0, 0
    if indicators['rsi'] < 30: votes_long += weights['rsi']
    elif indicators['rsi'] > 70: votes_short += weights['rsi']
    if indicators['macd_diff'] > 0 and indicators['macd_line'] > indicators['macd_signal']:
        votes_long += weights['macd']
    elif indicators['macd_diff'] < 0 and indicators['macd_line'] < indicators['macd_signal']:
        votes_short += weights['macd']
    if indicators['ema9'] > indicators['ema21']:
        votes_long += weights['ema']
    else:
        votes_short += weights['ema']
    last = indicators['last_close']
    if last <= indicators['bb_low']:
        votes_long += weights['bollinger']
    elif last >= indicators['bb_high']:
        votes_short += weights['bollinger']
    if indicators['stoch_k'] < 20 and indicators['stoch_d'] < 20:
        votes_long += weights['stoch']
    elif indicators['stoch_k'] > 80 and indicators['stoch_d'] > 80:
        votes_short += weights['stoch']
    if indicators['adx'] > 25:
        if indicators['ema9'] > indicators['ema21']:
            votes_long += weights['adx']
        else:
            votes_short += weights['adx']
    if indicators['ichimoku'] > 0:
        votes_long += weights['ichimoku']
    elif indicators['ichimoku'] < 0:
        votes_short += weights['ichimoku']
    if indicators['supertrend'] > 0:
        votes_long += weights['supertrend']
    elif indicators['supertrend'] < 0:
        votes_short += weights['supertrend']
    if indicators['vwap'] > 0:
        votes_long += weights['vwap']
    elif indicators['vwap'] < 0:
        votes_short += weights['vwap']
    if indicators['hma'] > 0:
        votes_long += weights['hma']
    elif indicators['hma'] < 0:
        votes_short += weights['hma']
    if indicators['stoch_rsi'] > 0:
        votes_long += weights['stoch_rsi']
    elif indicators['stoch_rsi'] < 0:
        votes_short += weights['stoch_rsi']
    if votes_long > votes_short and votes_long >= 5:
        return 'LONG'
    elif votes_short > votes_long and votes_short >= 5:
        return 'SHORT'
    else:
        return 'HOLD'

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
                signals.append(get_weighted_signal(ind))
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
    primary_signal = get_weighted_signal(ind)

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
    reason = f"Таймфрейм: {timeframe} (авто), свечей: {len(df)}\nМульти-ТФ: {long_tf} LONG, {short_tf} SHORT на 1H/4H"
    if tf_boost == 1:
        reason += " → усиление сигнала"
    elif tf_boost == -1:
        reason += " → противоречие, сигнал ослаблен"

    return {
        'signal': final_signal,
        'strength': strength,
        'emoji': emoji,
        'reason': reason,
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

# ==================== ОБРАБОТЧИКИ (ИСПРАВЛЕННЫЕ) ====================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Приветственное сообщение с первой картинкой"""
    text = ("🚀 *Торговый бот-ассистент*\n\n"
            "Я анализирую рынок и даю сигналы по активам из Pocket Option.\n"
            "Нажми **GO!** чтобы начать.")
    keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("GO!", callback_data="go")]])
    await update.message.reply_photo(
        photo=BANNER_IMAGES['welcome'],
        caption=text,
        parse_mode='Markdown',
        reply_markup=keyboard
    )

async def go(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Экран выбора раздела со второй картинкой"""
    query = update.callback_query
    await query.answer()
    keyboard = [
        [InlineKeyboardButton("💱 Валюты", callback_data="currencies")],
        [InlineKeyboardButton("🪙 Криптовалюты", callback_data="crypto")],
        [InlineKeyboardButton("🛢️ Сырьевые", callback_data="commodities")],
        [InlineKeyboardButton("📈 Акции", callback_data="stocks")],
        [InlineKeyboardButton("📊 Индексы", callback_data="indices")]
    ]
    text = "Выберите раздел:"
    # Удаляем старое сообщение (с приветствием и первой картинкой)
    try:
        await query.message.delete()
    except:
        pass
    # Отправляем новое фото (второй баннер) с текстом и кнопками
    await update.effective_chat.send_photo(
        photo=BANNER_IMAGES['sections'],
        caption=text,
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

async def section_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка выбора раздела – удаляем фото и отправляем текстовое сообщение с активами"""
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
        await update.effective_chat.send_message("Ошибка")
        return
    keyboard = build_keyboard(items, back=True, back_data="go")
    # Удаляем фото с выбором раздела
    try:
        await query.message.delete()
    except:
        pass
    # Отправляем новое текстовое сообщение с кнопками
    await update.effective_chat.send_message(
        f"{title} (выберите актив):",
        reply_markup=keyboard
    )

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

async def timeframe_selected(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    tf = query.data
    if tf in ['back_to_section', 'back_to_asset', 'go', 'home']:
        return
    context.user_data['timeframe'] = tf
    text = f"✅ Таймфрейм *{tf}* выбран.\nТеперь выберите время сделки:"
    keyboard = build_keyboard(DURATIONS, back=True, back_data="back_to_asset")
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
        await query.answer("Уже обрабатываю...")
        return
    context.user_data['processing'] = True
    await query.answer()
    duration = query.data
    if duration in ['back_to_asset', 'back_to_section', 'go', 'home']:
        context.user_data['processing'] = False
        return

    asset = context.user_data.get('asset')
    if not asset or asset in ['back_to_asset', 'back_to_section', 'go', 'home']:
        await query.edit_message_text("⚠️ Ошибка: выберите актив заново.")
        context.user_data['processing'] = False
        return

    context.user_data['duration'] = duration
    icon = ASSET_ICONS.get(asset, "")
    await query.edit_message_text(f"{icon} ⏳ Анализирую рынок...")
    try:
        clean_asset = asset.replace(" OTC", "").replace("/", "").strip()
        result = generate_signal(clean_asset, duration)
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
        # Удаляем сообщение с выбором времени
        try:
            await query.message.delete()
        except:
            pass
        # Отправляем фото с сигналом
        await update.effective_chat.send_photo(
            photo=image_url,
            caption=msg,
            parse_mode='Markdown',
            reply_markup=InlineKeyboardMarkup(keyboard)
        )

    except Exception as e:
        logger.error(f"duration error: {e}")
        keyboard = [[InlineKeyboardButton("🏠 Назад в меню", callback_data="home")]]
        try:
            await query.edit_message_text(f"❌ Ошибка: {str(e)}", reply_markup=InlineKeyboardMarkup(keyboard))
        except BadRequest as ex:
            if "Message is not modified" in str(ex):
                pass
            else:
                raise
    finally:
        context.user_data['processing'] = False

async def resignal(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if context.user_data.get('processing', False):
        await query.answer("Уже обрабатываю...")
        return
    context.user_data['processing'] = True
    await query.answer()
    asset = context.user_data.get('asset')
    duration = context.user_data.get('duration')
    if not asset or not duration:
        await query.edit_message_text("Ошибка: данные потеряны. Начните заново /start")
        context.user_data['processing'] = False
        return
    if asset in ['back_to_asset', 'back_to_section', 'go', 'home']:
        await query.edit_message_text("Ошибка: выберите актив заново.")
        context.user_data['processing'] = False
        return

    icon = ASSET_ICONS.get(asset, "")
    await query.edit_message_text(f"{icon} ⏳ Анализирую рынок...")
    try:
        clean_asset = asset.replace(" OTC", "").replace("/", "").strip()
        result = generate_signal(clean_asset, duration)
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

    except Exception as e:
        logger.error(f"resignal error: {e}")
        keyboard = [[InlineKeyboardButton("🏠 Назад в меню", callback_data="home")]]
        try:
            await query.edit_message_text(f"❌ Ошибка: {str(e)}", reply_markup=InlineKeyboardMarkup(keyboard))
        except BadRequest as ex:
            if "Message is not modified" in str(ex):
                pass
            else:
                raise
    finally:
        context.user_data['processing'] = False

async def back_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    back_to = query.data
    if back_to == "back_to_section":
        # Возврат к выбору раздела – отправляем второй баннер
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
        # Возврат в главное меню – отправляем первый баннер
        try:
            await query.message.delete()
        except:
            pass
        text = ("🚀 *Торговый бот-ассистент*\n\n"
                "Я анализирую рынок и даю сигналы по активам из Pocket Option.\n"
                "Нажми **GO!** чтобы начать.")
        keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("GO!", callback_data="go")]])
        await update.effective_chat.send_photo(
            photo=BANNER_IMAGES['welcome'],
            caption=text,
            parse_mode='Markdown',
            reply_markup=keyboard
        )
    else:
        await go(update, context)

async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logger.error(f"Update {update} caused error {context.error}")

# ==================== ЗАПУСК ====================
def main():
    flask_app = Flask(__name__)
    @flask_app.route('/')
    def home():
        return "Bot is running!"
    def run_flask():
        flask_app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 10000)))
    threading.Thread(target=run_flask, daemon=True).start()
    logger.info("Flask запущен")

    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(go, pattern="^go$"))
    app.add_handler(CallbackQueryHandler(section_handler, pattern="^(currencies|crypto|commodities|stocks|indices)$"))
    app.add_handler(CallbackQueryHandler(asset_selected, pattern="^(" + "|".join(CURRENCIES+CRYPTO+COMMODITIES+STOCKS+INDICES) + ")$"))
    app.add_handler(CallbackQueryHandler(timeframe_selected, pattern="^(" + "|".join(TIMEFRAMES) + ")$"))
    app.add_handler(CallbackQueryHandler(duration_selected, pattern="^(" + "|".join(DURATIONS) + ")$"))
    app.add_handler(CallbackQueryHandler(resignal, pattern="^resignal$"))
    app.add_handler(CallbackQueryHandler(back_handler, pattern="^(back_to_section|back_to_asset|go|home)$"))
    app.add_error_handler(error_handler)

    logger.info("Бот запущен!")
    app.run_polling()

if __name__ == "__main__":
    main()
