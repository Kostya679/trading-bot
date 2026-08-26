import os
import logging
import time
from datetime import datetime, timedelta
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
from transformers import pipeline
from newsapi import NewsApiClient
import warnings
warnings.filterwarnings('ignore')

# ==================== ЗАГРУЗКА ПЕРЕМЕННЫХ ====================
load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN")
TWELVE_DATA_API_KEY = os.getenv("TWELVE_DATA_API_KEY", "")
ALPHA_VANTAGE_API_KEY = os.getenv("ALPHA_VANTAGE_API_KEY", "")
NEWS_API_KEY = os.getenv("NEWS_API_KEY", "")

if not BOT_TOKEN:
    raise ValueError("BOT_TOKEN не задан")

logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

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

ALPHAVANTAGE_INTERVAL_MAP = {
    '5s': '1min', '10s': '1min', '15s': '1min', '30s': '1min',
    '1m': '1min', '2m': '1min', '3m': '5min', '4m': '5min',
    '5m': '5min', '6m': '15min', '8m': '15min', '10m': '15min',
    '15m': '15min', '20m': '30min', '25m': '30min', '30m': '30min',
    '45m': '60min', '1h': '60min', '2h': '60min', '3h': '60min', '4h': '60min'
}

BINANCE_INTERVAL_MAP = {
    '5s': '1m', '10s': '1m', '15s': '1m', '30s': '1m',
    '1m': '1m', '2m': '1m', '3m': '5m', '4m': '5m',
    '5m': '5m', '6m': '15m', '8m': '15m', '10m': '15m',
    '15m': '15m', '20m': '30m', '25m': '30m', '30m': '30m',
    '45m': '1h', '1h': '1h', '2h': '4h', '3h': '4h', '4h': '4h'
}

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
    "GOOGL": ["GOOG"],
    "AMZN": ["AMZN"],
    "AAPL": ["AAPL"],
    "TSLA": ["TSLA"],
    "MSFT": ["MSFT"],
    "NVDA": ["NVDA"]
}

FOREX_LIST = [
    'AUDUSD', 'EURUSD', 'EURGBP', 'EURJPY', 'GBPJPY', 'USDCAD', 'USDCHF',
    'USDJPY', 'GBPUSD', 'NZDUSD', 'EURCHF', 'GBPAUD', 'AUDJPY', 'CADJPY',
    'CHFJPY', 'EURNZD', 'GBPCAD', 'GBPNZD', 'NZDCAD', 'AUDCAD', 'AUDCHF',
    'GBPCHF', 'USDCNH', 'USDHKD', 'USDMXN', 'USDSEK', 'USDSGD', 'USDZAR'
]

CRYPTO_LIST = ['BTC', 'ETH', 'LTC', 'XRP', 'SOL', 'ADA', 'DOT', 'LINK', 'BNB']

# ==================== НОВОСТНОЙ АНАЛИЗ (СЕНТИМЕНТ) ====================
sentiment_pipeline = None
if NEWS_API_KEY:
    try:
        sentiment_pipeline = pipeline("sentiment-analysis", model="ProsusAI/finbert")
        news_client = NewsApiClient(api_key=NEWS_API_KEY)
        logger.info("FinBERT и NewsAPI инициализированы")
    except Exception as e:
        logger.warning(f"Ошибка инициализации FinBERT/NewsAPI: {e}")

def get_news_sentiment(symbol):
    """Получает тональность новостей по активу (Positive/Neutral/Negative) и коэффициент влияния"""
    if not sentiment_pipeline or not NEWS_API_KEY:
        return "NEUTRAL", 0.0
    try:
        # Ищем новости по символу
        news = news_client.get_everything(q=symbol, language='en', sort_by='relevancy', page_size=10)
        if not news['articles']:
            return "NEUTRAL", 0.0
        
        # Анализируем заголовки
        sentiments = []
        for article in news['articles'][:5]:
            if article['title']:
                result = sentiment_pipeline(article['title'])[0]
                label = result['label']
                score = result['score']
                if label == 'positive':
                    sentiments.append(1.0 * score)
                elif label == 'negative':
                    sentiments.append(-1.0 * score)
                else:
                    sentiments.append(0.0)
        
        if not sentiments:
            return "NEUTRAL", 0.0
        
        avg_sentiment = sum(sentiments) / len(sentiments)
        if avg_sentiment > 0.3:
            return "POSITIVE", avg_sentiment
        elif avg_sentiment < -0.3:
            return "NEGATIVE", avg_sentiment
        else:
            return "NEUTRAL", avg_sentiment
    except Exception as e:
        logger.warning(f"Ошибка получения новостей: {e}")
        return "NEUTRAL", 0.0

# ==================== РАСШИРЕННЫЙ ТЕХНИЧЕСКИЙ АНАЛИЗ ====================
def compute_advanced_indicators(df):
    """Вычисляет расширенный набор индикаторов (Ichimoku, SuperTrend, VWAP, HMA, Stochastic RSI)"""
    close = df['close']
    high = df['high']
    low = df['low']
    volume = df['volume']
    
    # Базовые индикаторы (уже были)
    rsi = ta.momentum.RSIIndicator(close, 14).rsi().iloc[-1]
    macd = ta.trend.MACD(close)
    macd_diff = macd.macd_diff().iloc[-1]
    macd_line = macd.macd().iloc[-1]
    macd_signal = macd.macd_signal().iloc[-1]
    ema9 = ta.trend.EMAIndicator(close, 9).ema_indicator().iloc[-1]
    ema21 = ta.trend.EMAIndicator(close, 21).ema_indicator().iloc[-1]
    bb_high = ta.volatility.BollingerBands(close, 20, 2).bollinger_hband().iloc[-1]
    bb_low = ta.volatility.BollingerBands(close, 20, 2).bollinger_lband().iloc[-1]
    stoch = ta.momentum.StochasticOscillator(high, low, close, 14, 3)
    stoch_k = stoch.stoch().iloc[-1]
    stoch_d = stoch.stoch_signal().iloc[-1]
    adx = ta.trend.ADXIndicator(high, low, close, 14).adx().iloc[-1]
    
    # ---- НОВЫЕ ИНДИКАТОРЫ ----
    # 1. Ichimoku (используем Tenkan-sen и Kijun-sen как упрощённый вариант)
    high_9 = high.rolling(9).max().iloc[-1]
    low_9 = low.rolling(9).min().iloc[-1]
    tenkan = (high_9 + low_9) / 2
    high_26 = high.rolling(26).max().iloc[-1]
    low_26 = low.rolling(26).min().iloc[-1]
    kijun = (high_26 + low_26) / 2
    ichimoku_signal = 1 if close.iloc[-1] > tenkan and close.iloc[-1] > kijun else -1 if close.iloc[-1] < tenkan and close.iloc[-1] < kijun else 0
    
    # 2. SuperTrend
    atr = ta.volatility.AverageTrueRange(high, low, close, 10).average_true_range().iloc[-1]
    multiplier = 3
    upper_band = (high.iloc[-1] + low.iloc[-1]) / 2 + multiplier * atr
    lower_band = (high.iloc[-1] + low.iloc[-1]) / 2 - multiplier * atr
    supertrend_signal = 1 if close.iloc[-1] > upper_band else -1 if close.iloc[-1] < lower_band else 0
    
    # 3. VWAP (используем накопленный объём, приближённо)
    vwap = (volume * (high + low + close) / 3).sum() / volume.sum() if volume.sum() > 0 else close.iloc[-1]
    vwap_signal = 1 if close.iloc[-1] > vwap else -1 if close.iloc[-1] < vwap else 0
    
    # 4. HMA (Hull Moving Average, период 20)
    def hma(series, period=20):
        half_period = int(period / 2)
        sqrt_period = int(np.sqrt(period))
        wma_half = series.rolling(half_period).apply(lambda x: np.sum(np.arange(1, half_period+1) * x) / np.sum(np.arange(1, half_period+1)))
        wma_full = series.rolling(period).apply(lambda x: np.sum(np.arange(1, period+1) * x) / np.sum(np.arange(1, period+1)))
        hma_series = 2 * wma_half - wma_full
        hma_series = hma_series.rolling(sqrt_period).apply(lambda x: np.sum(np.arange(1, sqrt_period+1) * x) / np.sum(np.arange(1, sqrt_period+1)))
        return hma_series
    hma_value = hma(close, 20).iloc[-1]
    hma_signal = 1 if close.iloc[-1] > hma_value else -1 if close.iloc[-1] < hma_value else 0
    
    # 5. Stochastic RSI
    stoch_rsi = ta.momentum.StochRSIIndicator(close, 14, 3, 3)
    stoch_rsi_k = stoch_rsi.stochrsi_k().iloc[-1] if not pd.isna(stoch_rsi.stochrsi_k().iloc[-1]) else 50
    stoch_rsi_d = stoch_rsi.stochrsi_d().iloc[-1] if not pd.isna(stoch_rsi.stochrsi_d().iloc[-1]) else 50
    stoch_rsi_signal = 1 if stoch_rsi_k < 20 and stoch_rsi_d < 20 else -1 if stoch_rsi_k > 80 and stoch_rsi_d > 80 else 0
    
    # 6. ADX (уже был, переиспользуем)
    adx_value = adx if not pd.isna(adx) else 25  # если нет данных, считаем нейтральным
    
    return {
        'rsi': rsi if not pd.isna(rsi) else 50,
        'macd_diff': macd_diff if not pd.isna(macd_diff) else 0,
        'macd_line': macd_line if not pd.isna(macd_line) else 0,
        'macd_signal': macd_signal if not pd.isna(macd_signal) else 0,
        'ema9': ema9 if not pd.isna(ema9) else close.iloc[-1],
        'ema21': ema21 if not pd.isna(ema21) else close.iloc[-1],
        'bb_high': bb_high if not pd.isna(bb_high) else close.iloc[-1],
        'bb_low': bb_low if not pd.isna(bb_low) else close.iloc[-1],
        'stoch_k': stoch_k if not pd.isna(stoch_k) else 50,
        'stoch_d': stoch_d if not pd.isna(stoch_d) else 50,
        'adx': adx_value,
        'ichimoku': ichimoku_signal,
        'supertrend': supertrend_signal,
        'vwap': vwap_signal,
        'hma': hma_signal,
        'stoch_rsi': stoch_rsi_signal,
        'last_close': close.iloc[-1]
    }

# ==================== МУЛЬТИТАЙМФРЕЙМОВЫЙ АНАЛИЗ ====================
def get_multi_timeframe_signal(asset, tf_primary='1h'):
    """Анализирует на 3 таймфреймах: 1D, 1H, 15m"""
    timeframes = ['1d', '1h', '15m']
    signals = []
    for tf in timeframes:
        try:
            df = get_market_data(asset, tf, limit=200)
            if df is not None and not df.empty:
                ind = compute_advanced_indicators(df)
                # Получаем предварительный сигнал (голосование)
                signal = get_weighted_signal(ind)
                signals.append(signal)
            else:
                signals.append('HOLD')
        except Exception as e:
            logger.warning(f"Ошибка на таймфрейме {tf}: {e}")
            signals.append('HOLD')
    
    # Если все три сонаправлены – сигнал сильный
    if signals[0] == signals[1] == signals[2] and signals[0] != 'HOLD':
        return f"{signals[0]} (STRONG, all TFs aligned)"
    # Если два совпадают – средний
    elif signals.count('LONG') >= 2:
        return "LONG (MEDIUM, 2/3 TFs aligned)"
    elif signals.count('SHORT') >= 2:
        return "SHORT (MEDIUM, 2/3 TFs aligned)"
    else:
        return "HOLD (WEAK, TFs disagree)"

# ==================== ВЗВЕШЕННОЕ ГОЛОСОВАНИЕ ====================
def get_weighted_signal(indicators):
    """Принимает решение на основе взвешенного голосования"""
    weights = {
        'rsi': 2,
        'macd': 3,
        'ema': 2,
        'bollinger': 1,
        'stoch': 1,
        'adx': 2,
        'ichimoku': 2,
        'supertrend': 2,
        'vwap': 1,
        'hma': 1,
        'stoch_rsi': 1
    }
    
    votes_long = 0
    votes_short = 0
    
    # RSI
    if indicators['rsi'] < 30:
        votes_long += weights['rsi']
    elif indicators['rsi'] > 70:
        votes_short += weights['rsi']
    
    # MACD
    if indicators['macd_diff'] > 0 and indicators['macd_line'] > indicators['macd_signal']:
        votes_long += weights['macd']
    elif indicators['macd_diff'] < 0 and indicators['macd_line'] < indicators['macd_signal']:
        votes_short += weights['macd']
    
    # EMA
    if indicators['ema9'] > indicators['ema21']:
        votes_long += weights['ema']
    else:
        votes_short += weights['ema']
    
    # Bollinger
    last = indicators['last_close']
    if last <= indicators['bb_low']:
        votes_long += weights['bollinger']
    elif last >= indicators['bb_high']:
        votes_short += weights['bollinger']
    
    # Stochastic
    if indicators['stoch_k'] < 20 and indicators['stoch_d'] < 20:
        votes_long += weights['stoch']
    elif indicators['stoch_k'] > 80 and indicators['stoch_d'] > 80:
        votes_short += weights['stoch']
    
    # ADX
    if indicators['adx'] > 25:
        if indicators['ema9'] > indicators['ema21']:
            votes_long += weights['adx']
        else:
            votes_short += weights['adx']
    
    # Ichimoku
    if indicators['ichimoku'] > 0:
        votes_long += weights['ichimoku']
    elif indicators['ichimoku'] < 0:
        votes_short += weights['ichimoku']
    
    # SuperTrend
    if indicators['supertrend'] > 0:
        votes_long += weights['supertrend']
    elif indicators['supertrend'] < 0:
        votes_short += weights['supertrend']
    
    # VWAP
    if indicators['vwap'] > 0:
        votes_long += weights['vwap']
    elif indicators['vwap'] < 0:
        votes_short += weights['vwap']
    
    # HMA
    if indicators['hma'] > 0:
        votes_long += weights['hma']
    elif indicators['hma'] < 0:
        votes_short += weights['hma']
    
    # Stochastic RSI
    if indicators['stoch_rsi'] > 0:
        votes_long += weights['stoch_rsi']
    elif indicators['stoch_rsi'] < 0:
        votes_short += weights['stoch_rsi']
    
    # Принимаем решение
    if votes_long > votes_short and votes_long >= 5:
        return 'LONG'
    elif votes_short > votes_long and votes_short >= 5:
        return 'SHORT'
    else:
        return 'HOLD'

# ==================== УПРАВЛЕНИЕ РИСКАМИ (ATR STOP-LOSS) ====================
def calculate_risk_parameters(df, entry_price):
    """Рассчитывает динамический стоп-лосс на основе ATR"""
    try:
        atr = ta.volatility.AverageTrueRange(df['high'], df['low'], df['close'], 14).average_true_range().iloc[-1]
        if pd.isna(atr) or atr == 0:
            atr = df['close'].iloc[-1] * 0.01  # 1% запасной вариант
        stop_loss = entry_price - 2 * atr
        take_profit = entry_price + 3 * atr
        risk_reward = 1.5  # соотношение риск/прибыль (1:1.5)
        return {
            'stop_loss': stop_loss,
            'take_profit': take_profit,
            'atr': atr,
            'risk_reward': risk_reward
        }
    except Exception as e:
        logger.warning(f"Ошибка расчёта риска: {e}")
        return {'stop_loss': entry_price * 0.98, 'take_profit': entry_price * 1.03, 'atr': entry_price * 0.01, 'risk_reward': 1.5}

# ==================== ФУНКЦИИ ПОЛУЧЕНИЯ ДАННЫХ (СОХРАНЯЕМ СТАРУЮ ЛОГИКУ) ====================
def get_market_data(symbol, timeframe, limit=100):
    # ... (здесь код функции get_market_data из предыдущей версии, она остаётся без изменений)
    # Для краткости я пропускаю полный код, но он должен быть вставлен сюда полностью
    pass

def fetch_yfinance(symbol, timeframe, limit, is_index=False):
    # ... (код из предыдущей версии)
    pass

def fetch_binance(symbol, timeframe, limit):
    # ... (код из предыдущей версии)
    pass

def fetch_twelvedata(symbol, timeframe, limit):
    # ... (код из предыдущей версии)
    pass

def fetch_alphavantage(symbol, timeframe, limit):
    # ... (код из предыдущей версии)
    pass

# ==================== ОСНОВНАЯ ЛОГИКА СИГНАЛА (С ИНТЕГРАЦИЕЙ ВСЕХ УЛУЧШЕНИЙ) ====================
def generate_signal(asset, timeframe):
    """
    Генерация сигнала с интеграцией:
    - мульти-таймфрейм
    - расширенные индикаторы
    - новостной сентимент
    - управление рисками
    """
    # 1. Получаем данные для основного таймфрейма
    df = get_market_data(asset, timeframe, limit=200)
    if df is None or df.empty:
        return {'signal': 'HOLD', 'reason': 'Нет данных', 'risk': None}
    
    # 2. Расчёт расширенных индикаторов
    indicators = compute_advanced_indicators(df)
    
    # 3. Мульти-таймфреймовый анализ (3 уровня)
    multi_signal = get_multi_timeframe_signal(asset, timeframe)
    
    # 4. Взвешенное голосование по основному таймфрейму
    primary_signal = get_weighted_signal(indicators)
    
    # 5. Новостной сентимент (если доступен)
    news_sentiment, sentiment_score = get_news_sentiment(asset)
    sentiment_correction = 0
    if sentiment_score > 0.3:
        sentiment_correction = 1  # позитивные новости усиливают LONG
    elif sentiment_score < -0.3:
        sentiment_correction = -1  # негативные усиливают SHORT
    
    # 6. Корректировка сигнала с учётом новостей
    if sentiment_correction == 1 and primary_signal == 'LONG':
        final_signal = 'LONG'
        strength = 'STRONG (sentiment positive)'
    elif sentiment_correction == -1 and primary_signal == 'SHORT':
        final_signal = 'SHORT'
        strength = 'STRONG (sentiment negative)'
    elif sentiment_correction == 1 and primary_signal == 'SHORT':
        final_signal = 'HOLD'
        strength = 'WEAK (sentiment opposes signal)'
    elif sentiment_correction == -1 and primary_signal == 'LONG':
        final_signal = 'HOLD'
        strength = 'WEAK (sentiment opposes signal)'
    else:
        final_signal = primary_signal
        strength = 'MEDIUM' if primary_signal != 'HOLD' else 'WEAK'
    
    # 7. Управление рисками (стоп-лосс и тейк-профит)
    entry_price = indicators['last_close']
    risk_params = calculate_risk_parameters(df, entry_price)
    
    # 8. Формируем подробный ответ
    explanation = (
        f"Мульти-таймфрейм: {multi_signal}\n"
        f"Новостной фон: {news_sentiment} (score: {sentiment_score:.2f})\n"
        f"Голоса: {final_signal} (сила: {strength})\n"
        f"Стоп-лосс: {risk_params['stop_loss']:.4f}\n"
        f"Тейк-профит: {risk_params['take_profit']:.4f}\n"
        f"ATR: {risk_params['atr']:.4f}"
    )
    
    return {
        'signal': final_signal,
        'reason': explanation,
        'indicators': indicators,
        'risk': risk_params,
        'multi_signal': multi_signal,
        'sentiment': news_sentiment,
        'strength': strength
    }

# ==================== ОБРАБОТЧИКИ КОМАНД (СОХРАНЯЕМ СТАРЫЙ ИНТЕРФЕЙС) ====================
# (все обработчики start, go, section_handler, asset_selected, timeframe_selected,
# duration_selected, resignal, back_handler остаются точно такими же, как в предыдущей версии,
# но в duration_selected и resignal мы вызываем НОВУЮ функцию generate_signal вместо старой)

async def duration_selected(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # ... (весь код такой же, но вместо старого анализа вызываем generate_signal)
    pass

async def resignal(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # ... (аналогично)
    pass

# ==================== ЗАПУСК ====================
def main():
    flask_app = Flask(__name__)
    @flask_app.route('/')
    def home():
        return "Bot is running!"
    
    def run_flask():
        port = int(os.environ.get('PORT', 10000))
        flask_app.run(host='0.0.0.0', port=port)
    
    thread = threading.Thread(target=run_flask)
    thread.daemon = True
    thread.start()
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
