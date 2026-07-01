import os
import logging
from datetime import datetime
from dotenv import load_dotenv
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes
import requests
import yfinance as yf
import pandas as pd
import ta
from flask import Flask
import threading

load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN")
TWELVE_DATA_API_KEY = os.getenv("TWELVE_DATA_API_KEY", "")

if not BOT_TOKEN:
    raise ValueError("BOT_TOKEN не найден")

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# -------------------- ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ДАННЫХ --------------------
def get_market_data(symbol, timeframe, limit=100):
    clean = symbol.upper().replace('=X', '').replace('_OTC', '').replace('USDT', '').replace('BUSD', '')
    variations = [clean, f"{clean}=X", f"{clean}_OTC", f"{clean}USDT", f"{clean}BUSD"]
    variations = list(dict.fromkeys(variations))
    
    sources = []
    if TWELVE_DATA_API_KEY:
        sources.append(('twelvedata', fetch_twelvedata))
    sources.append(('yfinance', fetch_yfinance))
    try:
        from binance.client import Client
        sources.append(('binance', fetch_binance))
    except ImportError:
        logger.warning("Библиотека python-binance не установлена, Binance недоступен")
    
    for src_name, src_func in sources:
        for sym in variations:
            try:
                df = src_func(sym, timeframe, limit)
                if df is not None and not df.empty:
                    logger.info(f"Данные получены: {src_name} для {sym}")
                    return df
            except Exception as e:
                logger.warning(f"Ошибка {src_name} для {sym}: {e}")
                continue
    raise Exception("Нет данных ни из одного источника")

def fetch_twelvedata(symbol, timeframe, limit):
    interval_map = {'1m':'1min','5m':'5min','15m':'15min','30m':'30min','1h':'1h','4h':'4h','1d':'1day'}
    interval = interval_map.get(timeframe, '5min')
    url = "https://api.twelvedata.com/time_series"
    params = {'symbol':symbol, 'interval':interval, 'outputsize':limit, 'apikey':TWELVE_DATA_API_KEY}
    resp = requests.get(url, params=params, timeout=10)
    data = resp.json()
    if 'values' not in data:
        raise Exception("Нет данных")
    df = pd.DataFrame(data['values'])
    df = df.rename(columns={'open':'open','high':'high','low':'low','close':'close','volume':'volume'})
    for c in ['open','high','low','close','volume']:
        df[c] = df[c].astype(float)
    df = df.iloc[::-1].reset_index(drop=True)
    return df[['open','high','low','close','volume']]

def fetch_yfinance(symbol, timeframe, limit):
    if not symbol.endswith('=X'):
        symbol = symbol + '=X'
    interval = timeframe
    if interval == '4h':
        interval = '1h'
    ticker = yf.Ticker(symbol)
    df = ticker.history(period='5d', interval=interval)
    if df.empty:
        raise Exception("Нет данных")
    if timeframe == '4h':
        df = df.resample('4h').agg({'Open':'first','High':'max','Low':'min','Close':'last','Volume':'sum'}).dropna()
    df = df.iloc[-limit:]
    return df[['Open','High','Low','Close','Volume']].rename(columns={'Open':'open','High':'high','Low':'low','Close':'close','Volume':'volume'})

def fetch_binance(symbol, timeframe, limit):
    if not symbol.endswith('USDT') and not symbol.endswith('BUSD'):
        symbol = symbol + 'USDT'
    from binance.client import Client
    client = Client()
    interval_map = {'1m':Client.KLINE_INTERVAL_1MINUTE,'5m':Client.KLINE_INTERVAL_5MINUTE,'15m':Client.KLINE_INTERVAL_15MINUTE,'30m':Client.KLINE_INTERVAL_30MINUTE,'1h':Client.KLINE_INTERVAL_1HOUR,'4h':Client.KLINE_INTERVAL_4HOUR,'1d':Client.KLINE_INTERVAL_1DAY}
    klines = client.get_klines(symbol=symbol.upper(), interval=interval_map.get(timeframe, Client.KLINE_INTERVAL_5MINUTE), limit=limit)
    if not klines:
        raise Exception("Нет данных")
    df = pd.DataFrame(klines, columns=['timestamp','open','high','low','close','volume','ct','qav','trades','tbbav','tbqav','ignore'])
    for c in ['open','high','low','close','volume']:
        df[c] = df[c].astype(float)
    return df[['open','high','low','close','volume']]

def compute_signal(df):
    if df.empty or len(df) < 30:
        return {'signal':'HOLD','reason':'Недостаточно данных','indicators':{}}
    close = df['close']
    high = df['high']
    low = df['low']
    rsi = ta.momentum.RSIIndicator(close, 14).rsi().iloc[-1]
    macd = ta.trend.MACD(close)
    macd_diff = macd.macd_diff().iloc[-1]
    macd_line = macd.macd().iloc[-1]
    macd_signal = macd.macd_signal().iloc[-1]
    ema_fast = ta.trend.EMAIndicator(close, 9).ema_indicator().iloc[-1]
    ema_slow = ta.trend.EMAIndicator(close, 21).ema_indicator().iloc[-1]
    bb_high = ta.volatility.BollingerBands(close, 20, 2).bollinger_hband().iloc[-1]
    bb_low = ta.volatility.BollingerBands(close, 20, 2).bollinger_lband().iloc[-1]
    stoch = ta.momentum.StochasticOscillator(high, low, close, 14, 3)
    stoch_k = stoch.stoch().iloc[-1]
    stoch_d = stoch.stoch_signal().iloc[-1]
    adx = ta.trend.ADXIndicator(high, low, close, 14).adx().iloc[-1]
    
    votes_long, votes_short, reasons = 0, 0, []
    if rsi < 30:
        votes_long += 1
        reasons.append(f"RSI={rsi:.1f} (перепроданность)")
    elif rsi > 70:
        votes_short += 1
        reasons.append(f"RSI={rsi:.1f} (перекупленность)")
    if macd_diff > 0 and macd_line > macd_signal:
        votes_long += 1
        reasons.append("MACD бычье")
    elif macd_diff < 0 and macd_line < macd_signal:
        votes_short += 1
        reasons.append("MACD медвежье")
    if ema_fast > ema_slow:
        votes_long += 1
        reasons.append(f"EMA9>{ema_slow:.2f}")
    else:
        votes_short += 1
        reasons.append(f"EMA9<{ema_slow:.2f}")
    last = close.iloc[-1]
    if last <= bb_low:
        votes_long += 1
        reasons.append("Цена у нижней полосы")
    elif last >= bb_high:
        votes_short += 1
        reasons.append("Цена у верхней полосы")
    if stoch_k < 20 and stoch_d < 20:
        votes_long += 1
        reasons.append("Stoch перепродан")
    elif stoch_k > 80 and stoch_d > 80:
        votes_short += 1
        reasons.append("Stoch перекуплен")
    if adx > 25:
        if ema_fast > ema_slow:
            votes_long += 1
            reasons.append(f"ADX={adx:.1f} тренд")
        else:
            votes_short += 1
            reasons.append(f"ADX={adx:.1f} тренд")
    
    signal = 'HOLD'
    if votes_long > votes_short and votes_long >= 3:
        signal = 'LONG'
        final_reason = f"Бычий ({votes_long} vs {votes_short}). " + ", ".join(reasons)
    elif votes_short > votes_long and votes_short >= 3:
        signal = 'SHORT'
        final_reason = f"Медвежий ({votes_short} vs {votes_long}). " + ", ".join(reasons)
    else:
        final_reason = f"HOLD ({votes_long}L, {votes_short}S). " + ", ".join(reasons)
    
    return {'signal':signal, 'reason':final_reason, 'indicators':{
        'RSI':rsi, 'MACD_diff':macd_diff, 'EMA9':ema_fast, 'EMA21':ema_slow,
        'BB_high':bb_high, 'BB_low':bb_low, 'Stoch_K':stoch_k, 'Stoch_D':stoch_d,
        'ADX':adx, 'Last_Close':last
    }}

# -------------------- МЕНЮ И КНОПКИ --------------------
CURRENCIES = [
    "AUD/USD OTC", "EUR/USD OTC", "EUR/RUB OTC", "GBP/JPY OTC",
    "USD/CAD OTC", "USD/CHF OTC", "USD/JPY OTC", "GBP/USD OTC"
]
CRYPTO = ["BTC/USD OTC", "ETH/USD OTC", "LTC/USD OTC", "XRP/USD OTC", "SOL/USD OTC"]
COMMODITIES = ["Gold OTC", "Silver OTC", "Oil OTC", "Natural Gas OTC"]
STOCKS = ["AAPL OTC", "TSLA OTC", "GOOGL OTC", "AMZN OTC", "MSFT OTC", "NVDA OTC"]
INDICES = ["S&P 500 OTC", "NASDAQ OTC", "Dow Jones OTC", "Nikkei 225 OTC"]

TIMEFRAMES = ["5s", "10s", "15s", "30s", "1m", "2m", "3m", "5m", "10m", "15m", "30m", "1h", "4h"]
DURATIONS = ["5s", "10s", "15s", "30s", "1m", "2m", "3m", "4m", "5m", "6m", "8m", "10m", "15m", "20m", "25m", "30m", "45m", "1h", "2h", "3h", "4h"]

FLAG_URLS = {
    "AUD/USD OTC": "https://flagcdn.com/au.svg",
    "EUR/USD OTC": "https://flagcdn.com/eu.svg",
    "GBP/USD OTC": "https://flagcdn.com/gb.svg",
    "USD/JPY OTC": "https://flagcdn.com/jp.svg",
    "USD/CAD OTC": "https://flagcdn.com/ca.svg",
    "USD/CHF OTC": "https://flagcdn.com/ch.svg",
    "BTC/USD OTC": "https://cryptologos.cc/logos/bitcoin-btc-logo.png",
    "ETH/USD OTC": "https://cryptologos.cc/logos/ethereum-eth-logo.png",
}

def build_keyboard(items, back=False, back_data=None, cols=2):
    keyboard = []
    row = []
    for i, item in enumerate(items):
        row.append(InlineKeyboardButton(item, callback_data=item))
        if len(row) == cols:
            keyboard.append(row)
            row = []
    if row:
        keyboard.append(row)
    if back:
        keyboard.append([InlineKeyboardButton("🔙 Назад", callback_data=back_data or "back")])
    return InlineKeyboardMarkup(keyboard)

# -------------------- ОБРАБОТЧИКИ --------------------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        text = (
            "🚀 *Добро пожаловать в торгового бота-ассистента!*\n\n"
            "Я анализирую рынок и даю сигналы по активам из Pocket Option.\n"
            "Выбирай актив, таймфрейм и время сделки — я скажу, когда войти в LONG или SHORT.\n\n"
            "Нажми **GO!** чтобы начать."
        )
        keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("GO!", callback_data="go")]])
        await update.message.reply_text(text, parse_mode='Markdown', reply_markup=keyboard)
    except Exception as e:
        logger.error(f"Ошибка в start: {e}", exc_info=True)
        await update.message.reply_text("❌ Произошла ошибка при запуске. Попробуйте позже.")

async def go(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    keyboard = [
        [InlineKeyboardButton("💱 Валюты", callback_data="currencies")],
        [InlineKeyboardButton("🪙 Криптовалюты", callback_data="crypto")],
        [InlineKeyboardButton("🛢️ Сырьевые товары", callback_data="commodities")],
        [InlineKeyboardButton("📈 Акции", callback_data="stocks")],
        [InlineKeyboardButton("📊 Индексы", callback_data="indices")]
    ]
    await query.edit_message_text("Выберите раздел:", reply_markup=InlineKeyboardMarkup(keyboard))

async def section_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    section = query.data
    if section == "currencies":
        items = CURRENCIES
        title = "💱 Валютные пары"
    elif section == "crypto":
        items = CRYPTO
        title = "🪙 Криптовалюты"
    elif section == "commodities":
        items = COMMODITIES
        title = "🛢️ Сырьевые товары"
    elif section == "stocks":
        items = STOCKS
        title = "📈 Акции"
    elif section == "indices":
        items = INDICES
        title = "📊 Индексы"
    else:
        await query.edit_message_text("Ошибка")
        return
    keyboard = build_keyboard(items, back=True, back_data="go")
    await query.edit_message_text(f"{title} (выберите актив):", reply_markup=keyboard)

async def asset_selected(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    asset = query.data
    context.user_data['asset'] = asset
    flag_url = FLAG_URLS.get(asset, "https://flagcdn.com/unknown.svg")
    text = f"*{asset}*\n\nВыберите таймфрейм для анализа:"
    keyboard = build_keyboard(TIMEFRAMES, back=True, back_data="back_to_section")
    try:
        await query.message.delete()
        await update.effective_chat.send_photo(photo=flag_url, caption=text, parse_mode='Markdown', reply_markup=keyboard)
    except Exception as e:
        logger.warning(f"Не удалось отправить фото: {e}")
        await query.edit_message_text(text, parse_mode='Markdown', reply_markup=keyboard)

async def timeframe_selected(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    tf = query.data
    context.user_data['timeframe'] = tf
    text = f"✅ Таймфрейм *{tf}* выбран.\nТеперь выберите время сделки (экспирацию):"
    keyboard = build_keyboard(DURATIONS, back=True, back_data="back_to_asset")
    await query.edit_message_text(text, parse_mode='Markdown', reply_markup=keyboard)

async def duration_selected(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    duration = query.data
    context.user_data['duration'] = duration
    asset = context.user_data.get('asset')
    timeframe = context.user_data.get('timeframe')
    if not asset or not timeframe:
        await query.edit_message_text("Ошибка: не выбраны параметры. Начните заново /start")
        return
    await query.edit_message_text("⏳ Анализирую рынок...")
    try:
        clean_asset = asset.replace(" OTC", "").replace("/", "").strip()
        df = get_market_data(clean_asset, timeframe, limit=100)
        signal_data = compute_signal(df)
        signal = signal_data['signal']
        reason = signal_data['reason']
        price = signal_data['indicators'].get('Last_Close', 0)
        emoji = '🟢' if signal == 'LONG' else '🔴' if signal == 'SHORT' else '⚪'
        msg = (
            f"{emoji} *СИГНАЛ: {signal}*\n"
            f"Актив: {asset}\n"
            f"Таймфрейм: {timeframe}\n"
            f"Время сделки: {duration}\n"
            f"Цена: {price:.4f}\n\n"
            f"Обоснование:\n{reason}"
        )
        keyboard = [
            [InlineKeyboardButton("🔄 Дай сигнал ещё раз", callback_data="resignal")],
            [InlineKeyboardButton("🏠 Назад в меню", callback_data="home")]
        ]
        await query.edit_message_text(msg, parse_mode='Markdown', reply_markup=InlineKeyboardMarkup(keyboard))
    except Exception as e:
        logger.error(f"Ошибка в duration_selected: {e}", exc_info=True)
        await query.edit_message_text(f"❌ Ошибка: {str(e)}")

async def resignal(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    asset = context.user_data.get('asset')
    timeframe = context.user_data.get('timeframe')
    duration = context.user_data.get('duration')
    if not asset or not timeframe or not duration:
        await query.edit_message_text("Ошибка: данные потеряны. Начните заново /start")
        return
    await query.edit_message_text("⏳ Анализирую рынок...")
    try:
        clean_asset = asset.replace(" OTC", "").replace("/", "").strip()
        df = get_market_data(clean_asset, timeframe, limit=100)
        signal_data = compute_signal(df)
        signal = signal_data['signal']
        reason = signal_data['reason']
        price = signal_data['indicators'].get('Last_Close', 0)
        emoji = '🟢' if signal == 'LONG' else '🔴' if signal == 'SHORT' else '⚪'
        msg = (
            f"{emoji} *СИГНАЛ: {signal}*\n"
            f"Актив: {asset}\n"
            f"Таймфрейм: {timeframe}\n"
            f"Время сделки: {duration}\n"
            f"Цена: {price:.4f}\n\n"
            f"Обоснование:\n{reason}"
        )
        keyboard = [
            [InlineKeyboardButton("🔄 Дай сигнал ещё раз", callback_data="resignal")],
            [InlineKeyboardButton("🏠 Назад в меню", callback_data="home")]
        ]
        await query.edit_message_text(msg, parse_mode='Markdown', reply_markup=InlineKeyboardMarkup(keyboard))
    except Exception as e:
        logger.error(f"Ошибка в resignal: {e}", exc_info=True)
        await query.edit_message_text(f"❌ Ошибка: {str(e)}")

async def back_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    back_to = query.data
    if back_to == "back_to_section":
        # Удаляем текущее сообщение (это фото)
        try:
            await query.message.delete()
        except:
            pass
        # Отправляем новое сообщение с выбором раздела
        await go(update, context)
    elif back_to == "back_to_asset":
        # Возврат к выбору таймфрейма
        asset = context.user_data.get('asset')
        if asset:
            # Удаляем текущее сообщение с выбором времени
            try:
                await query.message.delete()
            except:
                pass
            # Показываем заново выбор таймфрейма
            await asset_selected(update, context)
        else:
            await go(update, context)
    elif back_to == "go":
        await go(update, context)
    elif back_to == "home":
        # Возврат в главное меню (удаляем всё и начинаем заново)
        try:
            await query.message.delete()
        except:
            pass
        await go(update, context)
    else:
        await go(update, context)
        
async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logger.error(f"Update {update} caused error {context.error}", exc_info=True)

# -------------------- ЗАПУСК --------------------
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
    logger.info("Flask-поток запущен")

    # --- Бот ---
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

    logger.info("Бот запущен и готов к работе!")
    try:
        app.run_polling()
    except Exception as e:
        logger.error(f"Ошибка при запуске polling: {e}", exc_info=True)
        raise

if __name__ == "__main__":
    main()
