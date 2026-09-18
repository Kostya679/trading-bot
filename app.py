import os
import logging
import time
import asyncio
import threading
from datetime import datetime, timezone, timedelta
from dotenv import load_dotenv
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes
import yfinance as yf
import pandas as pd
import numpy as np
import ta
import requests
from flask import Flask, request

try:
    import psycopg2
    from psycopg2.extras import RealDictCursor
    PSYCOPG_OK = True
except ImportError:
    PSYCOPG_OK = False

load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN")
TWELVE_DATA_API_KEY = os.getenv("TWELVE_DATA_API_KEY", "")
ALPHA_VANTAGE_API_KEY = os.getenv("ALPHA_VANTAGE_API_KEY", "")
DATABASE_URL = os.getenv("DATABASE_URL", "")

if not BOT_TOKEN:
    raise ValueError("BOT_TOKEN не задан")

logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

RENDER_URL = "https://mega-trade-bot.onrender.com"
CANDLE_LIMITS = {'1m': 1000, '5m': 800, '15m': 600, '1h': 400, '4h': 300}

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
    'AUDUSD', 'EURUSD', 'EURRUB', 'EURGBP', 'EURJPY', 'GBPJPY', 'USDCAD', 'USDCHF',
    'USDJPY', 'GBPUSD', 'NZDUSD', 'EURCHF', 'GBPAUD', 'AUDJPY', 'CADJPY',
    'CHFJPY', 'EURNZD', 'GBPCAD', 'GBPNZD', 'NZDCAD', 'AUDCAD', 'AUDCHF',
    'GBPCHF', 'USDCNH', 'USDHKD', 'USDMXN', 'USDSEK', 'USDSGD', 'USDZAR'
]

def duration_to_seconds(duration):
    if duration.endswith('s'):
        return int(duration[:-1])
    elif duration.endswith('m'):
        return int(duration[:-1]) * 60
    elif duration.endswith('h'):
        return int(duration[:-1]) * 3600
    return 60

def get_timeframe_from_duration(duration, asset_name):
    seconds = duration_to_seconds(duration)
    is_commodity = any(comm in asset_name for comm in COMMODITY_SYMBOLS)
    is_index = any(idx in asset_name for idx in INDEX_SYMBOLS)
    is_forex = asset_name in FOREX_LIST
    if is_index or is_commodity or is_forex:
        return '15m' if seconds <= 900 else '1h'
    if seconds <= 60:
        return '1m'
    elif seconds <= 300:
        return '5m'
    elif seconds <= 900:
        return '15m'
    elif seconds <= 3600:
        return '1h'
    return '1h'

def get_candle_limit(timeframe):
    return CANDLE_LIMITS.get(timeframe, 300)

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

def get_yfinance_symbol(symbol):
    norm = symbol.replace(" ", "").upper()
    for key, config in SYMBOL_CONFIG.items():
        if key.replace(" ", "").upper() == norm:
            return config['yfinance']
    if norm in [c + 'USD' for c in CRYPTO_LIST]:
        return None
    if norm in FOREX_LIST:
        return norm + '=X'
    if norm in STOCK_ALTERNATIVES:
        return norm
    return symbol

# ==================== БАЗА ДАННЫХ ====================
def get_db():
    return psycopg2.connect(DATABASE_URL, cursor_factory=RealDictCursor)

def init_db():
    if not DATABASE_URL or not PSYCOPG_OK:
        logger.warning("БД не настроена — статистика отключена")
        return
    conn = get_db()
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS signals (
            id SERIAL PRIMARY KEY,
            user_id BIGINT NOT NULL,
            asset VARCHAR(50) NOT NULL,
            direction VARCHAR(10) NOT NULL,
            timeframe VARCHAR(10) NOT NULL,
            duration VARCHAR(10) NOT NULL,
            entry_price DOUBLE PRECISION NOT NULL,
            strength VARCHAR(10),
            created_at TIMESTAMPTZ DEFAULT NOW(),
            check_at TIMESTAMPTZ NOT NULL,
            result VARCHAR(10),
            exit_price DOUBLE PRECISION,
            checked_at TIMESTAMPTZ
        );
    """)
    cur.execute("CREATE INDEX IF NOT EXISTS idx_signals_user ON signals(user_id, created_at);")
    cur.execute("""
        CREATE TABLE IF NOT EXISTS user_cycles (
            user_id BIGINT PRIMARY KEY,
            first_signal_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            last_sent_10_at TIMESTAMPTZ,
            last_sent_30_at TIMESTAMPTZ,
            last_sent_180_at TIMESTAMPTZ
        );
    """)
    conn.commit()
    cur.close()
    conn.close()
    logger.info("✅ База данных инициализирована")

def save_signal(user_id, asset, direction, timeframe, duration, entry_price, strength):
    if not DATABASE_URL or not PSYCOPG_OK:
        return None
    if direction not in ('LONG', 'SHORT'):
        return None
    try:
        user_id = int(user_id)
        asset = str(asset)
        direction = str(direction)
        timeframe = str(timeframe)
        duration = str(duration)
        entry_price = float(entry_price)
        strength = str(strength)
        check_at = datetime.now(timezone.utc) + timedelta(seconds=duration_to_seconds(duration))
        conn = get_db()
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO signals (user_id, asset, direction, timeframe, duration, entry_price, strength, check_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s) RETURNING id
        """, (user_id, asset, direction, timeframe, duration, entry_price, strength, check_at))
        signal_id = cur.fetchone()['id']
        cur.execute("""
            INSERT INTO user_cycles (user_id) VALUES (%s)
            ON CONFLICT (user_id) DO NOTHING
        """, (user_id,))
        conn.commit()
        cur.close()
        conn.close()
        logger.info(f"💾 Сигнал #{signal_id} сохранён: {asset} {direction} {duration} @ {entry_price}")
        return signal_id
    except Exception as e:
        logger.error(f"save_signal error: {e}")
        return None

def get_signal(signal_id, user_id=None):
    try:
        conn = get_db()
        cur = conn.cursor()
        if user_id:
            cur.execute("SELECT * FROM signals WHERE id = %s AND user_id = %s", (int(signal_id), int(user_id)))
        else:
            cur.execute("SELECT * FROM signals WHERE id = %s", (int(signal_id),))
        row = cur.fetchone()
        cur.close()
        conn.close()
        return row
    except Exception as e:
        logger.error(f"get_signal error: {e}")
        return None

def rate_signal(signal_id, result):
    try:
        conn = get_db()
        cur = conn.cursor()
        cur.execute("UPDATE signals SET result = %s, checked_at = NOW() WHERE id = %s", (str(result), int(signal_id)))
        conn.commit()
        cur.close()
        conn.close()
        return True
    except Exception as e:
        logger.error(f"rate_signal error: {e}")
        return False

def get_user_cycle(user_id):
    if not DATABASE_URL or not PSYCOPG_OK:
        return None
    try:
        conn = get_db()
        cur = conn.cursor()
        cur.execute("SELECT * FROM user_cycles WHERE user_id = %s", (int(user_id),))
        row = cur.fetchone()
        cur.close()
        conn.close()
        return row
    except Exception as e:
        logger.error(f"get_user_cycle error: {e}")
        return None

def update_last_sent(user_id, period):
    try:
        col = {10: 'last_sent_10_at', 30: 'last_sent_30_at', 180: 'last_sent_180_at'}[period]
        conn = get_db()
        cur = conn.cursor()
        cur.execute(f"UPDATE user_cycles SET {col} = NOW() WHERE user_id = %s", (int(user_id),))
        conn.commit()
        cur.close()
        conn.close()
    except Exception as e:
        logger.error(f"update_last_sent error: {e}")

def get_user_stats(user_id, days):
    conn = get_db()
    cur = conn.cursor()
    cur.execute("""
        SELECT
            COUNT(*) FILTER (WHERE result IN ('WIN', 'LOSS')) AS total,
            COUNT(*) FILTER (WHERE result = 'WIN') AS wins,
            COUNT(*) FILTER (WHERE result = 'LOSS') AS losses,
            COUNT(*) FILTER (WHERE result = 'SKIP') AS skipped,
            COUNT(*) FILTER (WHERE result IS NULL) AS pending
        FROM signals WHERE user_id = %s AND created_at >= NOW() - (%s * INTERVAL '1 day')
    """, (int(user_id), int(days)))
    overall = cur.fetchone()
    cur.execute("""
        SELECT asset, COUNT(*) FILTER (WHERE result = 'WIN') AS wins,
            COUNT(*) FILTER (WHERE result = 'LOSS') AS losses,
            COUNT(*) FILTER (WHERE result IN ('WIN','LOSS')) AS total
        FROM signals WHERE user_id = %s AND created_at >= NOW() - (%s * INTERVAL '1 day') AND result IN ('WIN','LOSS')
        GROUP BY asset ORDER BY total DESC LIMIT 5
    """, (int(user_id), int(days)))
    by_asset = cur.fetchall()
    cur.execute("""
        SELECT timeframe, COUNT(*) FILTER (WHERE result = 'WIN') AS wins,
            COUNT(*) FILTER (WHERE result = 'LOSS') AS losses,
            COUNT(*) FILTER (WHERE result IN ('WIN','LOSS')) AS total
        FROM signals WHERE user_id = %s AND created_at >= NOW() - (%s * INTERVAL '1 day') AND result IN ('WIN','LOSS')
        GROUP BY timeframe ORDER BY total DESC
    """, (int(user_id), int(days)))
    by_tf = cur.fetchall()
    cur.execute("""
        SELECT strength, COUNT(*) FILTER (WHERE result = 'WIN') AS wins,
            COUNT(*) FILTER (WHERE result = 'LOSS') AS losses,
            COUNT(*) FILTER (WHERE result IN ('WIN','LOSS')) AS total
        FROM signals WHERE user_id = %s AND created_at >= NOW() - (%s * INTERVAL '1 day') AND result IN ('WIN','LOSS')
        GROUP BY strength
    """, (int(user_id), int(days)))
    by_strength = cur.fetchall()
    cur.execute("""
        SELECT direction, COUNT(*) FILTER (WHERE result = 'WIN') AS wins,
            COUNT(*) FILTER (WHERE result = 'LOSS') AS losses,
            COUNT(*) FILTER (WHERE result IN ('WIN','LOSS')) AS total
        FROM signals WHERE user_id = %s AND created_at >= NOW() - (%s * INTERVAL '1 day') AND result IN ('WIN','LOSS')
        GROUP BY direction
    """, (int(user_id), int(days)))
    by_dir = cur.fetchall()
    cur.close()
    conn.close()
    return {'overall': overall, 'by_asset': by_asset, 'by_tf': by_tf,
            'by_strength': by_strength, 'by_dir': by_dir}

def format_remaining(delta):
    total = int(delta.total_seconds())
    if total <= 0:
        return "меньше минуты"
    days = total // 86400
    hours = (total % 86400) // 3600
    minutes = (total % 3600) // 60
    parts = []
    if days > 0:
        parts.append(f"{days}д")
    if hours > 0:
        parts.append(f"{hours}ч")
    if minutes > 0:
        parts.append(f"{minutes}м")
    return " ".join(parts) if parts else "меньше минуты"

def progress_bar(percent, length=15):
    filled = int(length * percent / 100)
    return "█" * filled + "░" * (length - filled)

def build_report_text(user_id, days, period_label):
    stats = get_user_stats(user_id, days)
    overall = stats['overall']
    total = overall['total'] or 0
    wins = overall['wins'] or 0
    losses = overall['losses'] or 0
    skipped = overall['skipped'] or 0
    pending = overall['pending'] or 0
    winrate = (wins / total * 100) if total > 0 else 0
    lines = [f"🏆 *Отчёт за {period_label}*", ""]
    if total == 0:
        lines.append("_За этот период пока нет оценённых сделок._")
        if pending > 0:
            lines.append(f"_Есть {pending} неоценённых сигналов._")
        return "\n".join(lines)
    lines.append("📊 *ОБЩАЯ СТАТИСТИКА*")
    lines.append(f"Оценённых сделок: *{total}*")
    lines.append(f"✅ Побед: *{wins}*")
    lines.append(f"❌ Поражений: *{losses}*")
    lines.append(f"🎯 Винрейт: *{winrate:.1f}%*")
    if skipped > 0:
        lines.append(f"⚪️ Пропущено: *{skipped}*")
    if pending > 0:
        lines.append(f"⏳ Не оценено: *{pending}*")
    lines.append("")
    if stats['by_asset']:
        lines.append("🎯 *ПО АКТИВАМ*")
        for row in stats['by_asset']:
            t = row['total'] or 0
            w = row['wins'] or 0
            wr = (w / t * 100) if t > 0 else 0
            lines.append(f"• {row['asset']}: {wr:.0f}% ({w}/{t})")
        lines.append("")
    if stats['by_tf']:
        lines.append("⏱ *ПО ТАЙМФРЕЙМАМ*")
        for row in stats['by_tf']:
            t = row['total'] or 0
            w = row['wins'] or 0
            wr = (w / t * 100) if t > 0 else 0
            lines.append(f"• {row['timeframe']}: {wr:.0f}% ({w}/{t})")
        lines.append("")
    if stats['by_strength']:
        lines.append("💪 *ПО СИЛЕ*")
        for row in stats['by_strength']:
            t = row['total'] or 0
            w = row['wins'] or 0
            wr = (w / t * 100) if t > 0 else 0
            lines.append(f"• {row['strength']}: {wr:.0f}% ({w}/{t})")
        lines.append("")
    if stats['by_dir']:
        lines.append("📈 *ПО НАПРАВЛЕНИЮ*")
        for row in stats['by_dir']:
            t = row['total'] or 0
            w = row['wins'] or 0
            wr = (w / t * 100) if t > 0 else 0
            lines.append(f"• {row['direction']}: {wr:.0f}% ({w}/{t})")
        lines.append("")
    if winrate >= 70:
        lines.append("💡 Отличный результат! Следи за просадками и не увеличивай ставку после серии побед.")
    elif winrate >= 60:
        lines.append("💡 Хороший результат. Обрати внимание на активы с низким винрейтом.")
    elif winrate >= 50:
        lines.append("💡 Средний результат. Тестируй разные таймфреймы и активы.")
    else:
        lines.append("💡 Результат ниже среднего. Проанализируй слабые активы и снизь риск.")
    text = "\n".join(lines)
    if len(text) > 4000:
        text = text[:4000] + "\n..."
    return text

# ==================== ПАТТЕРНЫ ====================
def detect_candle_patterns(df):
    if len(df) < 2:
        return {'engulfing': 0, 'hammer': 0, 'doji': 0}
    last = df.iloc[-1]
    prev = df.iloc[-2]
    body = abs(last['close'] - last['open'])
    upper_wick = last['high'] - max(last['close'], last['open'])
    lower_wick = min(last['close'], last['open']) - last['low']
    total_range = last['high'] - last['low']
    bull_eng = (last['close'] > last['open'] and prev['close'] < prev['open'] and last['close'] > prev['open'] and last['open'] < prev['close'])
    bear_eng = (last['close'] < last['open'] and prev['close'] > prev['open'] and last['close'] < prev['open'] and last['open'] > prev['close'])
    engulfing = 1 if bull_eng else -1 if bear_eng else 0
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
    min1_pos = lows.values.argmin()
    if min1_pos + 5 >= len(lows):
        return 0
    second_part = lows.iloc[min1_pos+5:]
    if len(second_part) == 0:
        return 0
    min2_pos = second_part.values.argmin() + (min1_pos+5)
    if abs(lows.iloc[min1_pos] - lows.iloc[min2_pos]) / lows.iloc[min1_pos] > tolerance:
        return 0
    max_between = recent['high'].iloc[min1_pos:min2_pos+1].max()
    if max_between < max(lows.iloc[min1_pos], lows.iloc[min2_pos]) * 1.02:
        return 0
    if df['close'].iloc[-1] > max_between:
        avg_vol = df['volume'].iloc[-20:].mean()
        return 2 if df['volume'].iloc[-1] > avg_vol * 1.2 else 1
    return 0

def detect_double_top(df, lookback=30, tolerance=0.02):
    if len(df) < lookback:
        return 0
    recent = df.iloc[-lookback:]
    highs = recent['high']
    max1_pos = highs.values.argmax()
    if max1_pos + 5 >= len(highs):
        return 0
    second_part = highs.iloc[max1_pos+5:]
    if len(second_part) == 0:
        return 0
    max2_pos = second_part.values.argmax() + (max1_pos+5)
    if abs(highs.iloc[max1_pos] - highs.iloc[max2_pos]) / highs.iloc[max1_pos] > tolerance:
        return 0
    min_between = recent['low'].iloc[max1_pos:max2_pos+1].min()
    if min_between > min(highs.iloc[max1_pos], highs.iloc[max2_pos]) * 0.98:
        return 0
    if df['close'].iloc[-1] < min_between:
        avg_vol = df['volume'].iloc[-20:].mean()
        return -2 if df['volume'].iloc[-1] > avg_vol * 1.2 else -1
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
    if len(peaks) >= 3:
        p1, p2, p3 = peaks[-3], peaks[-2], peaks[-1]
        if p2[1] > p1[1] and p2[1] > p3[1] and abs(p1[1] - p3[1]) / p1[1] <= 0.03:
            neck = (recent['low'].iloc[p1[0]:p2[0]].min() + recent['low'].iloc[p2[0]:p3[0]].min()) / 2
            if df['close'].iloc[-1] < neck:
                avg_vol = df['volume'].iloc[-20:].mean()
                return -2 if df['volume'].iloc[-1] > avg_vol * 1.2 else -1
    lows = recent['low']
    valleys = []
    for i in range(5, len(lows)-5):
        if lows.iloc[i] == lows.iloc[i-5:i+5].min():
            valleys.append((i, lows.iloc[i]))
    if len(valleys) >= 3:
        v1, v2, v3 = valleys[-3], valleys[-2], valleys[-1]
        if v2[1] < v1[1] and v2[1] < v3[1] and abs(v1[1] - v3[1]) / v1[1] <= 0.03:
            neck = (recent['high'].iloc[v1[0]:v2[0]].max() + recent['high'].iloc[v2[0]:v3[0]].max()) / 2
            if df['close'].iloc[-1] > neck:
                avg_vol = df['volume'].iloc[-20:].mean()
                return 2 if df['volume'].iloc[-1] > avg_vol * 1.2 else 1
    return 0

def calculate_pivot_points(df):
    if len(df) < 2:
        return None
    high = df['high'].max()
    low = df['low'].min()
    close = df['close'].iloc[-1]
    pivot = (high + low + close) / 3
    return {'pivot': pivot, 'r1': 2*pivot - low, 's1': 2*pivot - high,
            'r2': pivot + (high - low), 's2': pivot - (high - low)}

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
    return "OVERLAP"

# ==================== ДАННЫЕ ====================
async def fetch_market_data_async(symbol, timeframe, limit=300):
    tasks = []
    if TWELVE_DATA_API_KEY:
        td_symbol = symbol
        for key, config in SYMBOL_CONFIG.items():
            if key.replace(" ", "").upper() == symbol.upper():
                td_symbol = config['twelvedata']
                break
        tasks.append(("twelvedata", asyncio.ensure_future(asyncio.to_thread(fetch_twelvedata, td_symbol, timeframe, limit))))
    yf_symbol = get_yfinance_symbol(symbol)
    if yf_symbol:
        tasks.append(("yahoo", asyncio.ensure_future(asyncio.to_thread(fetch_yfinance, yf_symbol, timeframe, limit))))
    if symbol.upper() in [c + 'USD' for c in CRYPTO_LIST]:
        tasks.append(("binance", asyncio.ensure_future(asyncio.to_thread(fetch_binance, symbol, timeframe, limit))))
    errors = []
    for name, task in tasks:
        try:
            df = await task
            if df is not None and not df.empty:
                logger.info(f"✅ Источник {name} сработал для {symbol}")
                return df
        except Exception as e:
            logger.warning(f"❌ Источник {name} упал для {symbol}: {e}")
            errors.append(f"{name}: {e}")
    raise Exception(f"Все источники упали: {errors}")

async def get_market_data_async(symbol, timeframe, limit=300):
    try:
        return await fetch_market_data_async(symbol, timeframe, limit)
    except Exception as e:
        logger.error(f"Ошибка получения данных: {e}")
        raise

def fetch_yfinance(symbol, timeframe, limit, retries=3):
    interval = YFINANCE_INTERVAL_MAP.get(timeframe, timeframe)
    # Yahoo имеет ограничения по периоду для разных интервалов
    if interval == '1m':
        period = '7d'
    elif interval in ('2m', '5m', '15m', '30m'):
        period = '60d'
    else:
        period = '730d'
    if timeframe == '4h':
        interval = '1h'
        period = '730d'
    for attempt in range(retries):
        try:
            time.sleep(3)
            ticker = yf.Ticker(symbol)
            df = ticker.history(period=period, interval=interval)
            if df.empty:
                raise Exception("Нет данных Yahoo")
            if timeframe == '4h':
                df = df.resample('4h').agg({'Open':'first','High':'max','Low':'min','Close':'last','Volume':'sum'}).dropna()
            df = df.iloc[-limit:]
            return df[['Open','High','Low','Close','Volume']].rename(columns={'Open':'open','High':'high','Low':'low','Close':'close','Volume':'volume'})
        except Exception as e:
            if '401' in str(e) or '429' in str(e):
                time.sleep(5 * (attempt + 1))
                continue
            raise
    raise Exception("Yahoo недоступен")

def fetch_binance(symbol, timeframe, limit):
    try:
        from binance.client import Client
    except ImportError:
        raise Exception("python-binance не установлен")
    client = Client()
    interval = BINANCE_INTERVAL_MAP.get(timeframe, '1m')
    if timeframe == '4h':
        interval = '4h'
    if symbol.upper().endswith('USD'):
        base = symbol.upper()[:-3]
        symbol_binance = base + 'USDT'
    else:
        symbol_binance = symbol.upper()
    klines = client.get_klines(symbol=symbol_binance, interval=interval, limit=limit)
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
    for c in ['open','high','low','close','volume']:
        df[c] = df[c].astype(float)
    df = df.iloc[::-1].reset_index(drop=True)
    return df[['open','high','low','close','volume']]

# ==================== ИНДИКАТОРЫ ====================
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
        'pivots': calculate_pivot_points(df),
        'volume_score': volume_analysis(df),
        'session': get_session(datetime.now(timezone.utc))
    }

def get_weighted_signal(indicators, timeframe='1h'):
    weights = {
        'rsi': 2, 'macd': 3, 'ema': 2, 'bollinger': 1, 'stoch': 1,
        'adx': 2, 'ichimoku': 2, 'supertrend': 2, 'vwap': 1, 'hma': 1,
        'stoch_rsi': 1,
        'engulfing': 1.5, 'hammer': 1, 'doji': 0.5,
        'morning_star': 1.5, 'evening_star': 1.5,
        'hanging_man': 1.5, 'shooting_star': 1.5,
        'double_bottom': 2, 'double_top': 2, 'head_shoulders': 2.5
    }
    if timeframe in ['1m', '5m']:
        for key in ['engulfing', 'hammer', 'morning_star', 'evening_star', 'hanging_man', 'shooting_star', 'double_bottom', 'double_top', 'head_shoulders']:
            weights[key] *= 0.7
    vl, vs, reasons = 0, 0, []
    if indicators['rsi'] < 30:
        vl += weights['rsi']
        reasons.append(f"RSI={indicators['rsi']:.1f} (перепроданность)")
    elif indicators['rsi'] > 70:
        vs += weights['rsi']
        reasons.append(f"RSI={indicators['rsi']:.1f} (перекупленность)")
    if indicators['macd_diff'] > 0 and indicators['macd_line'] > indicators['macd_signal']:
        vl += weights['macd']
        reasons.append("MACD бычье")
    elif indicators['macd_diff'] < 0 and indicators['macd_line'] < indicators['macd_signal']:
        vs += weights['macd']
        reasons.append("MACD медвежье")
    if indicators['ema9'] > indicators['ema21']:
        vl += weights['ema']
        reasons.append("EMA9 > EMA21")
    else:
        vs += weights['ema']
        reasons.append("EMA9 < EMA21")
    last = indicators['last_close']
    if last <= indicators['bb_low']:
        vl += weights['bollinger']
        reasons.append("Цена у нижней полосы")
    elif last >= indicators['bb_high']:
        vs += weights['bollinger']
        reasons.append("Цена у верхней полосы")
    if indicators['stoch_k'] < 20 and indicators['stoch_d'] < 20:
        vl += weights['stoch']
        reasons.append("Stoch перепродан")
    elif indicators['stoch_k'] > 80 and indicators['stoch_d'] > 80:
        vs += weights['stoch']
        reasons.append("Stoch перекуплен")
    if indicators['adx'] > 25:
        if indicators['ema9'] > indicators['ema21']:
            vl += weights['adx']
            reasons.append(f"ADX={indicators['adx']:.1f} (тренд вверх)")
        else:
            vs += weights['adx']
            reasons.append(f"ADX={indicators['adx']:.1f} (тренд вниз)")
    if indicators['ichimoku'] > 0:
        vl += weights['ichimoku']
        reasons.append("Ichimoku бычий")
    elif indicators['ichimoku'] < 0:
        vs += weights['ichimoku']
        reasons.append("Ichimoku медвежий")
    if indicators['supertrend'] > 0:
        vl += weights['supertrend']
        reasons.append("SuperTrend бычий")
    elif indicators['supertrend'] < 0:
        vs += weights['supertrend']
        reasons.append("SuperTrend медвежий")
    if indicators['vwap'] > 0:
        vl += weights['vwap']
        reasons.append("Цена выше VWAP")
    elif indicators['vwap'] < 0:
        vs += weights['vwap']
        reasons.append("Цена ниже VWAP")
    if indicators['hma'] > 0:
        vl += weights['hma']
        reasons.append("HMA бычий")
    elif indicators['hma'] < 0:
        vs += weights['hma']
        reasons.append("HMA медвежий")
    if indicators['stoch_rsi'] > 0:
        vl += weights['stoch_rsi']
        reasons.append("Stoch RSI бычий")
    elif indicators['stoch_rsi'] < 0:
        vs += weights['stoch_rsi']
        reasons.append("Stoch RSI медвежий")
    p = indicators['patterns']
    if p['engulfing'] == 1:
        vl += weights['engulfing']
        reasons.append("Бычье поглощение")
    elif p['engulfing'] == -1:
        vs += weights['engulfing']
        reasons.append("Медвежье поглощение")
    if p['hammer'] == 1:
        vl += weights['hammer']
        reasons.append("Молот (бычий)")
    elif p['hammer'] == -1:
        vs += weights['hammer']
        reasons.append("Молот (медвежий)")
    if p['doji'] == 1:
        vl += 0.5
        vs += 0.5
        reasons.append("Доджи")
    if p['morning_star'] == 1:
        vl += weights['morning_star']
        reasons.append("Утренняя звезда")
    if p['evening_star'] == 1:
        vs += weights['evening_star']
        reasons.append("Вечерняя звезда")
    if p['hanging_man'] == -1:
        vs += weights['hanging_man']
        reasons.append("Повешенный")
    if p['shooting_star'] == -1:
        vs += weights['shooting_star']
        reasons.append("Падающая звезда")
    if p['double_bottom'] == 2:
        vl += weights['double_bottom'] * 1.2
        reasons.append("Двойное дно (сильное)")
    elif p['double_bottom'] == 1:
        vl += weights['double_bottom']
        reasons.append("Двойное дно")
    if p['double_top'] == -2:
        vs += weights['double_top'] * 1.2
        reasons.append("Двойная вершина (сильная)")
    elif p['double_top'] == -1:
        vs += weights['double_top']
        reasons.append("Двойная вершина")
    if p['head_shoulders'] == 2:
        vl += weights['head_shoulders'] * 1.2
        reasons.append("Перевёрнутые голова и плечи")
    elif p['head_shoulders'] == 1:
        vl += weights['head_shoulders']
        reasons.append("Перевёрнутые голова и плечи")
    elif p['head_shoulders'] == -2:
        vs += weights['head_shoulders'] * 1.2
        reasons.append("Голова и плечи (сильные)")
    elif p['head_shoulders'] == -1:
        vs += weights['head_shoulders']
        reasons.append("Голова и плечи")
    pivots = indicators['pivots']
    if pivots:
        if last <= pivots['s1']:
            vl += 1
            reasons.append("У поддержки S1")
        elif last >= pivots['r1']:
            vs += 1
            reasons.append("У сопротивления R1")
        if last <= pivots['s2']:
            vl += 1.5
            reasons.append("У сильной поддержки S2")
        elif last >= pivots['r2']:
            vs += 1.5
            reasons.append("У сильного сопротивления R2")
    vscore = indicators['volume_score']
    if vscore == 1:
        if vl > vs:
            vl += 1
            reasons.append("Объём подтверждает")
        else:
            vs += 1
            reasons.append("Объём подтверждает")
    elif vscore == -1:
        if vl > vs:
            vs += 1
            reasons.append("Низкий объём")
        else:
            vl += 1
            reasons.append("Низкий объём")
    if indicators['session'] == "ASIA":
        reasons.append("Азиатская сессия")
    elif indicators['session'] == "LONDON":
        reasons.append("Лондонская сессия")
    elif indicators['session'] == "NEW_YORK":
        reasons.append("Нью-Йоркская сессия")
    if vl > vs and vl >= 5:
        signal = 'LONG'
        final_reason = f"Бычий перевес ({vl:.1f} vs {vs:.1f}). " + ", ".join(reasons)
    elif vs > vl and vs >= 5:
        signal = 'SHORT'
        final_reason = f"Медвежий перевес ({vs:.1f} vs {vl:.1f}). " + ", ".join(reasons)
    else:
        signal = 'HOLD'
        final_reason = f"Нет явного перевеса ({vl:.1f}L, {vs:.1f}S). " + ", ".join(reasons)
    return signal, final_reason

async def get_multi_timeframe_alignment(asset, primary_tf):
    tf_list = ['1h', '4h']
    signals = []
    for tf in tf_list:
        if tf == primary_tf:
            continue
        try:
            df = await get_market_data_async(asset, tf, limit=200)
            if df is not None and not df.empty:
                ind = compute_advanced_indicators(df)
                sig, _ = get_weighted_signal(ind)
                signals.append(sig)
            else:
                signals.append('HOLD')
        except:
            signals.append('HOLD')
    return signals.count('LONG'), signals.count('SHORT')

def calculate_risk_parameters(df, entry_price):
    try:
        atr = ta.volatility.AverageTrueRange(df['high'], df['low'], df['close'], 14).average_true_range().iloc[-1]
        if pd.isna(atr) or atr == 0:
            atr = df['close'].iloc[-1] * 0.01
        return {'stop_loss': entry_price - 2*atr, 'take_profit': entry_price + 3*atr, 'atr': atr}
    except:
        return {'stop_loss': entry_price * 0.98, 'take_profit': entry_price * 1.03, 'atr': entry_price * 0.01}

async def generate_signal(asset, duration, user_id=None):
    timeframe = get_timeframe_from_duration(duration, asset)
    limit = get_candle_limit(timeframe)
    logger.info(f"Авто-таймфрейм: {timeframe}, лимит: {limit} для {duration} (актив: {asset})")
    clean_asset = asset.replace(" OTC", "").replace("/", "").strip()
    df = await get_market_data_async(clean_asset, timeframe, limit=limit)
    if df is None or df.empty:
        return {'signal': 'HOLD', 'strength': 'WEAK', 'emoji': '⚪', 'reason': 'Нет данных', 'indicators': None, 'risk': None, 'timeframe': timeframe, 'signal_id': None}
    ind = compute_advanced_indicators(df)
    primary_signal, reason = get_weighted_signal(ind, timeframe)
    long_tf, short_tf = await get_multi_timeframe_alignment(clean_asset, timeframe)
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
    risk = calculate_risk_parameters(df, float(ind['last_close']))
    full_reason = f"{reason}\nТаймфрейм: {timeframe} (авто), свечей: {len(df)}\nМульти-ТФ: {long_tf} LONG, {short_tf} SHORT на 1H/4H"
    if tf_boost == 1:
        full_reason += " → усиление"
    elif tf_boost == -1:
        full_reason += " → противоречие, ослаблен"
    signal_id = None
    if user_id and final_signal in ('LONG', 'SHORT'):
        signal_id = save_signal(user_id, clean_asset, final_signal, timeframe, duration, float(ind['last_close']), strength)
    return {
        'signal': final_signal, 'strength': strength, 'emoji': emoji,
        'reason': full_reason, 'indicators': ind, 'risk': risk, 'timeframe': timeframe,
        'signal_id': signal_id
    }

# ==================== ФОНОВАЯ ЗАДАЧА: АВТООТПРАВКА ОТЧЁТОВ ====================
async def check_periodic_reports():
    while True:
        await asyncio.sleep(600)
        try:
            if not DATABASE_URL or not PSYCOPG_OK:
                continue
            conn = get_db()
            cur = conn.cursor()
            cur.execute("SELECT * FROM user_cycles")
            cycles = cur.fetchall()
            cur.close()
            conn.close()
            now = datetime.now(timezone.utc)
            for c in cycles:
                uid = int(c['user_id'])
                first_sig = c['first_signal_at']
                for period in (10, 30, 180):
                    col = {10: 'last_sent_10_at', 30: 'last_sent_30_at', 180: 'last_sent_180_at'}[period]
                    last = c[col]
                    base = last if last else first_sig
                    if (now - base).total_seconds() >= period * 86400:
                        stats = get_user_stats(uid, period)
                        if (stats['overall']['total'] or 0) > 0:
                            label = "10 дней" if period == 10 else "месяц" if period == 30 else "полгода"
                            text = build_report_text(uid, period, label)
                            try:
                                await application.bot.send_message(chat_id=uid, text=text, parse_mode='Markdown')
                                update_last_sent(uid, period)
                                logger.info(f"📤 Отчёт {period}d отправлен user {uid}")
                            except Exception as e:
                                logger.warning(f"Не удалось отправить отчёт {period}d для {uid}: {e}")
        except Exception as e:
            logger.error(f"check_periodic_reports error: {e}")

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

def build_main_menu():
    keyboard = [
        [InlineKeyboardButton("💱 Валюты", callback_data="currencies")],
        [InlineKeyboardButton("🪙 Криптовалюты", callback_data="crypto")],
        [InlineKeyboardButton("🛢️ Сырьевые", callback_data="commodities")],
        [InlineKeyboardButton("📈 Акции", callback_data="stocks")],
        [InlineKeyboardButton("📊 Индексы", callback_data="indices")],
        [InlineKeyboardButton("✅👾🏆 Мои сделки", callback_data="my_trades")]
    ]
    return InlineKeyboardMarkup(keyboard)

# ==================== ОБРАБОТЧИКИ ====================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = ("🚀 *Торговый бот-ассистент*\n\n"
            "Я анализирую рынок и даю сигналы по активам из Pocket Option.\n"
            "Нажми **GO!** чтобы начать.")
    keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("GO!", callback_data="go")]])
    await update.message.reply_photo(photo=WELCOME_BANNER, caption=text, parse_mode='Markdown', reply_markup=keyboard)

async def go(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    try:
        await query.message.delete()
    except:
        pass
    await update.effective_chat.send_message("Выберите раздел:", reply_markup=build_main_menu())

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
    if asset in ['go', 'currencies', 'crypto', 'commodities', 'stocks', 'indices', 'my_trades']:
        return
    context.user_data['asset'] = asset
    icon = ASSET_ICONS.get(asset, "")
    text = f"{icon} *{asset}*\n\nВыберите время сделки:"
    keyboard = build_keyboard(DURATIONS, back=True, back_data="back_to_section")
    try:
        await query.edit_message_text(text, parse_mode='Markdown', reply_markup=keyboard)
    except Exception as e:
        if "Message is not modified" not in str(e):
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
            await query.edit_message_text("⚠️ Выберите актив заново.")
            return
        context.user_data['duration'] = duration
        icon = ASSET_ICONS.get(asset, "")
        await query.edit_message_text(f"{icon} ⏳ Анализирую рынок...")
        clean_asset = asset.replace(" OTC", "").replace("/", "").strip()
        user_id = update.effective_user.id
        result = await asyncio.wait_for(generate_signal(clean_asset, duration, user_id=user_id), timeout=60.0)
        await send_signal_result(update, context, result, asset, duration, icon)
    except asyncio.TimeoutError:
        await update.effective_chat.send_message("⏰ Превышено время.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🏠 Назад", callback_data="home")]]))
    except Exception as e:
        logger.error(f"duration_selected error: {e}")
        msg = f"❌ Ошибка: {str(e)}"
        if "Нет данных" in str(e) or "No data" in str(e):
            msg = f"❌ Для {asset} нет данных. Попробуйте больший ТФ."
        await update.effective_chat.send_message(msg, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🏠 Назад", callback_data="home")]]))
    finally:
        context.user_data['processing'] = False

async def send_signal_result(update, context, result, asset, duration, icon):
    signal = result['signal']
    strength = result['strength']
    emoji = result['emoji']
    reason = result['reason']
    ind = result['indicators']
    risk = result['risk']
    price = ind['last_close']
    tf = result['timeframe']
    signal_id = result.get('signal_id')
    msg = (f"{emoji} *{signal}* ({strength})\n"
           f"{icon} Актив: {asset}\n"
           f"⏱ Таймфрейм: {tf} (авто)\n"
           f"⏳ Время сделки: {duration}\n"
           f"💰 Цена (реальная биржа): {price:.4f}\n\n"
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
    if "OTC" in asset:
        msg += "\n\n⚠️ _Цены Pocket Option (OTC) могут отличаться от реального рынка._"

    if signal in ('LONG', 'SHORT') and signal_id:
        context.user_data['last_signal_id'] = signal_id
        keyboard = [
            [InlineKeyboardButton("✅ WIN", callback_data=f"rate_win_{signal_id}"),
             InlineKeyboardButton("❌ LOSS", callback_data=f"rate_loss_{signal_id}"),
             InlineKeyboardButton("⚪️ Пропустил", callback_data=f"rate_skip_{signal_id}")],
            [InlineKeyboardButton("🔄 Дай сигнал ещё раз", callback_data="resignal")],
            [InlineKeyboardButton("🏠 Назад в меню", callback_data="home")]
        ]
    else:
        context.user_data['last_signal_id'] = None
        keyboard = [
            [InlineKeyboardButton("🔄 Дай сигнал ещё раз", callback_data="resignal")],
            [InlineKeyboardButton("🏠 Назад в меню", callback_data="home")]
        ]
    image_url = SIGNAL_IMAGES.get(signal, SIGNAL_IMAGES['HOLD'])
    try:
        await update.callback_query.message.delete()
    except:
        pass
    await update.effective_chat.send_photo(photo=image_url, caption=msg, parse_mode='Markdown', reply_markup=InlineKeyboardMarkup(keyboard))

# ==================== ОЦЕНКА СИГНАЛА ====================
async def handle_rating(update, context, result_type):
    query = update.callback_query
    user_id = update.effective_user.id
    try:
        signal_id = int(query.data.split("_")[-1])
    except:
        await query.answer("Ошибка данных сигнала.", show_alert=True)
        return
    row = get_signal(signal_id, user_id)
    if row is None:
        await query.answer("Сигнал не найден.", show_alert=True)
        return
    if row['result'] is not None:
        await query.answer("Вы уже оценили этот сигнал 👍", show_alert=True)
        return
    now = datetime.now(timezone.utc)
    check_at = row['check_at']
    if check_at.tzinfo is None:
        check_at = check_at.replace(tzinfo=timezone.utc)
    if now < check_at:
        await query.answer("Ваше время ещё не прошло! Голосуйте честно 👌", show_alert=True)
        return
    if not rate_signal(signal_id, result_type):
        await query.answer("Ошибка записи. Попробуйте позже.", show_alert=True)
        return
    try:
        await query.edit_message_reply_markup(reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("🔄 Дай сигнал ещё раз", callback_data="resignal")],
            [InlineKeyboardButton("🏠 Назад в меню", callback_data="home")]
        ]))
    except:
        pass
    context.user_data['last_signal_id'] = None
    if result_type == 'WIN':
        await query.answer("Победа записана! 🎉", show_alert=True)
    elif result_type == 'LOSS':
        await query.answer("Убыток записан. В следующий раз повезёт! 💪", show_alert=True)
    else:
        await query.answer("Спасибо, пропуск учтён 😚", show_alert=True)

async def rate_win(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await handle_rating(update, context, 'WIN')

async def rate_loss(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await handle_rating(update, context, 'LOSS')

async def rate_skip(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await handle_rating(update, context, 'SKIP')

# ==================== RESIGNAL / BACK ====================
async def resignal(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    last_id = context.user_data.get('last_signal_id')
    if last_id:
        row = get_signal(last_id)
        if row and row['result'] is None:
            check_at = row['check_at']
            if check_at.tzinfo is None:
                check_at = check_at.replace(tzinfo=timezone.utc)
            if datetime.now(timezone.utc) >= check_at:
                await query.answer("Вы не оценили сигнал 😔 Оцените его перед следующим.", show_alert=True)
                return
    if context.user_data.get('processing', False):
        await query.answer("⏳ Уже идёт анализ...")
        return
    context.user_data['processing'] = True
    try:
        await query.answer()
        asset = context.user_data.get('asset')
        duration = context.user_data.get('duration')
        if not asset or not duration:
            await query.edit_message_text("Ошибка: начните заново /start")
            return
        icon = ASSET_ICONS.get(asset, "")
        try:
            await query.message.delete()
        except:
            pass
        temp_msg = await update.effective_chat.send_message(f"{icon} ⏳ Анализирую рынок...")
        clean_asset = asset.replace(" OTC", "").replace("/", "").strip()
        user_id = update.effective_user.id
        result = await asyncio.wait_for(generate_signal(clean_asset, duration, user_id=user_id), timeout=60.0)
        await send_signal_result(update, context, result, asset, duration, icon)
        try:
            await temp_msg.delete()
        except:
            pass
    except asyncio.TimeoutError:
        await update.effective_chat.send_message("⏰ Превышено время.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🏠 Назад", callback_data="home")]]))
    except Exception as e:
        logger.error(f"resignal error: {e}")
        await update.effective_chat.send_message(f"❌ Ошибка: {str(e)}", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🏠 Назад", callback_data="home")]]))
    finally:
        context.user_data['processing'] = False

async def back_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    back_to = query.data
    if back_to in ('back_to_section', 'back_to_asset', 'go', 'home'):
        last_id = context.user_data.get('last_signal_id')
        if last_id:
            row = get_signal(last_id)
            if row and row['result'] is None:
                check_at = row['check_at']
                if check_at.tzinfo is None:
                    check_at = check_at.replace(tzinfo=timezone.utc)
                if datetime.now(timezone.utc) >= check_at:
                    await query.answer("Вы не оценили сигнал 😔", show_alert=True)
                    return
    await query.answer()
    if back_to == "back_to_section":
        await go(update, context)
    elif back_to == "back_to_asset":
        asset = context.user_data.get('asset')
        if asset:
            await asset_selected(update, context)
        else:
            await go(update, context)
    else:
        await go(update, context)

# ==================== МОИ СДЕЛКИ ====================
async def my_trades_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    if not DATABASE_URL or not PSYCOPG_OK:
        await query.edit_message_text("⚠️ Статистика временно недоступна.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Назад", callback_data="go")]]))
        return
    cycle = get_user_cycle(user_id)
    if cycle is None:
        text = (
            "📊 *Мои сделки ✅👾🏆*\n\n"
            "Этот раздел показывает статистику ваших сделок.\n\n"
            "⚠️ *Отсчёт ещё не начался.*\n"
            "Получите первый сигнал (LONG/SHORT) — и цикл запустится.\n\n"
            "📅 Отчёты будут доступны:\n"
            "• *каждые 10 дней* — краткий срез\n"
            "• *каждые 30 дней* — месячный срез\n"
            "• *каждые 180 дней* — полугодовой срез\n\n"
            "Бот сам пришлёт отчёты, а также вы сможете открыть их здесь."
        )
        await query.edit_message_text(text, parse_mode='Markdown',
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Назад", callback_data="go")]]))
        return
    now = datetime.now(timezone.utc)
    first = cycle['first_signal_at']
    lines = ["📊 *Мои сделки ✅👾🏆*", "",
             "Этот раздел показывает статистику ваших сделок.",
             "Бот автоматически присылает отчёты по расписанию.",
             ""]
    buttons = []
    for period, label, col in [
        (10, "10 дней", 'last_sent_10_at'),
        (30, "месяц", 'last_sent_30_at'),
        (180, "полгода", 'last_sent_180_at'),
    ]:
        last_sent = cycle[col]
        base = last_sent if last_sent else first
        target = base + timedelta(days=period)
        if now >= target:
            lines.append(f"✅ *Отчёт за {label}* — готов")
            buttons.append([InlineKeyboardButton(f"📊 Статистика за {label}", callback_data=f"report_{period}")])
        else:
            remaining = target - now
            elapsed = now - base
            total_sec = (target - base).total_seconds()
            percent = min(100, max(0, (elapsed.total_seconds() / total_sec) * 100))
            bar = progress_bar(percent, 15)
            lines.append(f"⏳ *Отчёт за {label}* — через {format_remaining(remaining)}")
            lines.append(f"`{bar}` {percent:.0f}%")
            stats = get_user_stats(user_id, period)
            if (stats['overall']['total'] or 0) > 0:
                buttons.append([InlineKeyboardButton(f"📊 Статистика за {label} (текущая)", callback_data=f"report_{period}")])
    lines.append("")
    lines.append(f"📅 Первый сигнал: {first.strftime('%d.%m.%Y %H:%M')}")
    buttons.append([InlineKeyboardButton("🔙 Назад", callback_data="go")])
    text = "\n".join(lines)
    await query.edit_message_text(text, parse_mode='Markdown', reply_markup=InlineKeyboardMarkup(buttons))

async def report_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    period = int(query.data.split("_")[1])
    labels = {10: "10 дней", 30: "месяц", 180: "полгода"}
    text = build_report_text(user_id, period, labels[period])
    await query.edit_message_text(text, parse_mode='Markdown',
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 К моим сделкам", callback_data="my_trades")]]))

async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logger.error(f"Update {update} caused error {context.error}")

# ==================== ЗАПУСК ====================
app = Flask(__name__)
application = None
main_loop = None

@app.route('/')
def home():
    return "Bot is running!"

@app.route('/telegram', methods=['POST'])
def telegram_webhook():
    if application is None or main_loop is None:
        return 'Application not initialized', 500
    update = Update.de_json(request.get_json(force=True), application.bot)
    future = asyncio.run_coroutine_threadsafe(application.process_update(update), main_loop)
    future.result()
    return 'ok'

async def setup_webhook():
    global application
    application = Application.builder().token(BOT_TOKEN).build()
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CallbackQueryHandler(go, pattern="^go$"))
    application.add_handler(CallbackQueryHandler(section_handler, pattern="^(currencies|crypto|commodities|stocks|indices)$"))
    application.add_handler(CallbackQueryHandler(asset_selected, pattern="^(" + "|".join(CURRENCIES+CRYPTO+COMMODITIES+STOCKS+INDICES) + ")$"))
    application.add_handler(CallbackQueryHandler(duration_selected, pattern="^(" + "|".join(DURATIONS) + ")$"))
    application.add_handler(CallbackQueryHandler(rate_win, pattern="^rate_win_\\d+$"))
    application.add_handler(CallbackQueryHandler(rate_loss, pattern="^rate_loss_\\d+$"))
    application.add_handler(CallbackQueryHandler(rate_skip, pattern="^rate_skip_\\d+$"))
    application.add_handler(CallbackQueryHandler(resignal, pattern="^resignal$"))
    application.add_handler(CallbackQueryHandler(my_trades_handler, pattern="^my_trades$"))
    application.add_handler(CallbackQueryHandler(report_handler, pattern="^report_(10|30|180)$"))
    application.add_handler(CallbackQueryHandler(back_handler, pattern="^(back_to_section|back_to_asset|go|home)$"))
    application.add_error_handler(error_handler)
    await application.initialize()
    await application.bot.set_webhook(url=f"{RENDER_URL}/telegram")
    logger.info(f"Webhook установлен: {RENDER_URL}/telegram")
    init_db()
    asyncio.create_task(check_periodic_reports())

def start_loop(loop):
    asyncio.set_event_loop(loop)
    loop.run_forever()

def keep_alive():
    while True:
        try:
            requests.get(RENDER_URL, timeout=5)
            logger.info("✅ Self-ping")
        except Exception as e:
            logger.warning(f"❌ Self-ping: {e}")
        time.sleep(300)

def main():
    global main_loop
    main_loop = asyncio.new_event_loop()
    loop_thread = threading.Thread(target=start_loop, args=(main_loop,), daemon=True)
    loop_thread.start()
    asyncio.run_coroutine_threadsafe(setup_webhook(), main_loop).result()
    threading.Thread(target=keep_alive, daemon=True).start()
    port = int(os.environ.get('PORT', 10000))
    app.run(host='0.0.0.0', port=port, use_reloader=False)

if __name__ == "__main__":
    main()
