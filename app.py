import os
import logging
import time
from datetime import datetime
from dotenv import load_dotenv
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes
import yfinance as yf
import pandas as pd
import ta
import requests
from flask import Flask
import threading

load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN")
ALPHA_VANTAGE_API_KEY = os.getenv("ALPHA_VANTAGE_API_KEY", "")

if not BOT_TOKEN:
    raise ValueError("BOT_TOKEN не задан")

logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

# -------------------- ПОЛУЧЕНИЕ ДАННЫХ --------------------
def get_market_data(symbol, timeframe, limit=100):
    """
    Для криптовалют → Binance (символ + USDT)
    Для валют и акций → Alpha Vantage (если есть ключ) или Yahoo Finance
    """
    clean = symbol.upper().replace('=X', '').replace('_OTC', '').replace('USDT', '').replace('BUSD', '')
    crypto_list = ['BTC', 'ETH', 'LTC', 'XRP', 'SOL', 'ADA', 'DOT', 'LINK', 'BNB']
    is_crypto = clean in crypto_list or clean.endswith('USDT')

    if is_crypto:
        symbol_binance = clean if clean.endswith('USDT') else f"{clean}USDT"
        logger.info(f"Крипто: {symbol_binance} через Binance")
        try:
            return fetch_binance(symbol_binance, timeframe, limit)
        except Exception as e:
            logger.warning(f"Binance ошибка: {e}")

    # Для валют и акций
    # Если есть ключ Alpha Vantage – используем его
    if ALPHA_VANTAGE_API_KEY:
        try:
            logger.info(f"Попытка Alpha Vantage для {clean}")
            return fetch_alphavantage(clean, timeframe, limit)
        except Exception as e:
            logger.warning(f"Alpha Vantage ошибка: {e}")

    # Резерв – Yahoo Finance (с задержкой)
    yf_symbol = f"{clean}=X"
    logger.info(f"Резерв: Yahoo Finance для {yf_symbol}")
    try:
        return fetch_yfinance(yf_symbol, timeframe, limit)
    except Exception as e:
        logger.warning(f"Yahoo Finance ошибка: {e}")

    raise Exception("Не удалось получить данные ни из одного источника")

def fetch_alphavantage(symbol, timeframe, limit):
    interval_map = {'1m':'1min','5m':'5min','15m':'15min','30m':'30min','1h':'60min','4h':'60min','1d':'daily'}
    interval = interval_map.get(timeframe, '5min')
    # Определяем, валюта или акция
    if len(symbol) == 6 and symbol.isalpha() and symbol in ['EURUSD','GBPUSD','USDJPY','AUDUSD','USDCAD','USDCHF','NZDUSD']:
        url = f"https://www.alphavantage.co/query?function=FX_INTRADAY&from_symbol={symbol[:3]}&to_symbol={symbol[3:]}&interval={interval}&apikey={ALPHA_VANTAGE_API_KEY}&outputsize=full"
    else:
        url = f"https://www.alphavantage.co/query?function=TIME_SERIES_INTRADAY&symbol={symbol}&interval={interval}&apikey={ALPHA_VANTAGE_API_KEY}&outputsize=full"
    resp = requests.get(url, timeout=10)
    data = resp.json()
    if 'Time Series' not in data and 'Time Series FX' not in data:
        raise Exception("Нет данных от Alpha Vantage")
    key = 'Time Series' if 'Time Series' in data else 'Time Series FX'
    df = pd.DataFrame.from_dict(data[key], orient='index')
    df.index = pd.to_datetime(df.index)
    df = df.sort_index()
    df = df.rename(columns={'1. open':'open','2. high':'high','3. low':'low','4. close':'close','5. volume':'volume'})
    df = df[['open','high','low','close','volume']].astype(float)
    df = df.iloc[-limit:]
    return df

def fetch_yfinance(symbol, timeframe, limit):
    time.sleep(1.5)  # задержка, чтобы не превысить лимит
    interval = timeframe
    if interval == '4h':
        interval = '1h'
    ticker = yf.Ticker(symbol)
    df = ticker.history(period='7d', interval=interval)
    if df.empty:
        raise Exception("Нет данных от Yahoo Finance")
    if timeframe == '4h':
        df = df.resample('4h').agg({'Open':'first','High':'max','Low':'min','Close':'last','Volume':'sum'}).dropna()
    df = df.iloc[-limit:]
    return df[['Open','High','Low','Close','Volume']].rename(columns={'Open':'open','High':'high','Low':'low','Close':'close','Volume':'volume'})

def fetch_binance(symbol, timeframe, limit):
    from binance.client import Client
    client = Client()
    interval_map = {'1m':Client.KLINE_INTERVAL_1MINUTE,'5m':Client.KLINE_INTERVAL_5MINUTE,'15m':Client.KLINE_INTERVAL_15MINUTE,'30m':Client.KLINE_INTERVAL_30MINUTE,'1h':Client.KLINE_INTERVAL_1HOUR,'4h':Client.KLINE_INTERVAL_4HOUR,'1d':Client.KLINE_INTERVAL_1DAY}
    klines = client.get_klines(symbol=symbol.upper(), interval=interval_map.get(timeframe, Client.KLINE_INTERVAL_5MINUTE), limit=limit)
    if not klines:
        raise Exception("Нет данных от Binance")
    df = pd.DataFrame(klines, columns=['timestamp','open','high','low','close','volume','ct','qav','trades','tbbav','tbqav','ignore'])
    for c in ['open','high','low','close','volume']:
        df[c] = df[c].astype(float)
    return df[['open','high','low','close','volume']]

# -------------------- РАСЧЁТ СИГНАЛА --------------------
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
        reasons.append("EMA9 > EMA21")
    else:
        votes_short += 1
        reasons.append("EMA9 < EMA21")

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
            reasons.append(f"ADX={adx:.1f} (сильный тренд вверх)")
        else:
            votes_short += 1
            reasons.append(f"ADX={adx:.1f} (сильный тренд вниз)")
    else:
        reasons.append(f"ADX={adx:.1f} (слабый тренд)")

    signal = 'HOLD'
    if votes_long > votes_short and votes_long >= 3:
        signal = 'LONG'
        final_reason = f"Бычий перевес ({votes_long} vs {votes_short}). " + ", ".join(reasons)
    elif votes_short > votes_long and votes_short >= 3:
        signal = 'SHORT'
        final_reason = f"Медвежий перевес ({votes_short} vs {votes_long}). " + ", ".join(reasons)
    else:
        final_reason = f"Нет явного перевеса ({votes_long}L, {votes_short}S). " + ", ".join(reasons)

    return {'signal':signal, 'reason':final_reason, 'indicators':{
        'RSI':rsi, 'MACD_diff':macd_diff, 'EMA9':ema_fast, 'EMA21':ema_slow,
        'BB_high':bb_high, 'BB_low':bb_low, 'Stoch_K':stoch_k, 'Stoch_D':stoch_d,
        'ADX':adx, 'Last_Close':last
    }}

# -------------------- МЕНЮ И ОБРАБОТЧИКИ --------------------
CURRENCIES = ["AUD/USD OTC","EUR/USD OTC","EUR/RUB OTC","GBP/JPY OTC",
              "USD/CAD OTC","USD/CHF OTC","USD/JPY OTC","GBP/USD OTC"]
CRYPTO = ["BTC/USD OTC","ETH/USD OTC","LTC/USD OTC","XRP/USD OTC","SOL/USD OTC"]
COMMODITIES = ["Gold OTC","Silver OTC","Oil OTC","Natural Gas OTC"]
STOCKS = ["AAPL OTC","TSLA OTC","GOOGL OTC","AMZN OTC","MSFT OTC","NVDA OTC"]
INDICES = ["S&P 500 OTC","NASDAQ OTC","Dow Jones OTC","Nikkei 225 OTC"]

TIMEFRAMES = ["5s","10s","15s","30s","1m","2m","3m","5m","10m","15m","30m","1h","4h"]
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

# -------------------- ОБРАБОТЧИКИ --------------------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        text = ("🚀 *Торговый бот-ассистент*\n\n"
                "Я анализирую рынок и даю сигналы по активам из Pocket Option.\n"
                "Нажми **GO!** чтобы начать.")
        keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("GO!", callback_data="go")]])
        await update.message.reply_text(text, parse_mode='Markdown', reply_markup=keyboard)
    except Exception as e:
        logger.error(f"start error: {e}")

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
    await update.effective_chat.send_message("Выберите раздел:", reply_markup=InlineKeyboardMarkup(keyboard))

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
        await update.effective_chat.send_message("Ошибка")
        return
    keyboard = build_keyboard(items, back=True, back_data="go")
    try:
        await query.message.delete()
    except:
        pass
    await update.effective_chat.send_message(f"{title} (выберите актив):", reply_markup=keyboard)

async def asset_selected(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    asset = query.data
    # Игнорируем служебные кнопки
    if asset in ['go', 'currencies', 'crypto', 'commodities', 'stocks', 'indices']:
        return
    context.user_data['asset'] = asset
    text = f"*{asset}*\n\nВыберите таймфрейм:"
    keyboard = build_keyboard(TIMEFRAMES, back=True, back_data="back_to_section")
    try:
        await query.message.delete()
    except:
        pass
    await update.effective_chat.send_message(text, parse_mode='Markdown', reply_markup=keyboard)

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
        await query.message.delete()
    except:
        pass
    await update.effective_chat.send_message(text, parse_mode='Markdown', reply_markup=keyboard)

async def duration_selected(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    duration = query.data
    if duration in ['back_to_asset', 'back_to_section', 'go', 'home']:
        return

    asset = context.user_data.get('asset')
    timeframe = context.user_data.get('timeframe')
    if not asset or not timeframe:
        await update.effective_chat.send_message("⚠️ Ошибка: выберите актив и таймфрейм заново.")
        return

    await update.effective_chat.send_message("⏳ Анализирую рынок...")
    try:
        clean_asset = asset.replace(" OTC", "").replace("/", "").strip()
        logger.info(f"Пробую получить данные для {clean_asset}, таймфрейм {timeframe}")
        df = get_market_data(clean_asset, timeframe, limit=100)
        signal_data = compute_signal(df)
        signal = signal_data['signal']
        reason = signal_data['reason']
        price = signal_data['indicators'].get('Last_Close', 0)
        emoji = '🟢' if signal == 'LONG' else '🔴' if signal == 'SHORT' else '⚪'
        msg = (f"{emoji} *СИГНАЛ: {signal}*\n"
               f"Актив: {asset}\n"
               f"Таймфрейм: {timeframe}\n"
               f"Время сделки: {duration}\n"
               f"Цена: {price:.4f}\n\n"
               f"Обоснование:\n{reason}")
        keyboard = [
            [InlineKeyboardButton("🔄 Дай сигнал ещё раз", callback_data="resignal")],
            [InlineKeyboardButton("🏠 Назад в меню", callback_data="home")]
        ]
        try:
            await query.message.delete()
        except:
            pass
        await update.effective_chat.send_message(msg, parse_mode='Markdown', reply_markup=InlineKeyboardMarkup(keyboard))
    except Exception as e:
        logger.error(f"duration error: {e}")
        keyboard = [[InlineKeyboardButton("🏠 Назад в меню", callback_data="home")]]
        await update.effective_chat.send_message(
            f"❌ Ошибка: {str(e)}",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )

async def resignal(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    asset = context.user_data.get('asset')
    timeframe = context.user_data.get('timeframe')
    duration = context.user_data.get('duration')
    if not asset or not timeframe or not duration:
        await update.effective_chat.send_message("Ошибка: данные потеряны. Начните заново /start")
        return
    await update.effective_chat.send_message("⏳ Анализирую рынок...")
    try:
        clean_asset = asset.replace(" OTC", "").replace("/", "").strip()
        df = get_market_data(clean_asset, timeframe, limit=100)
        signal_data = compute_signal(df)
        signal = signal_data['signal']
        reason = signal_data['reason']
        price = signal_data['indicators'].get('Last_Close', 0)
        emoji = '🟢' if signal == 'LONG' else '🔴' if signal == 'SHORT' else '⚪'
        msg = (f"{emoji} *СИГНАЛ: {signal}*\n"
               f"Актив: {asset}\n"
               f"Таймфрейм: {timeframe}\n"
               f"Время сделки: {duration}\n"
               f"Цена: {price:.4f}\n\n"
               f"Обоснование:\n{reason}")
        keyboard = [
            [InlineKeyboardButton("🔄 Дай сигнал ещё раз", callback_data="resignal")],
            [InlineKeyboardButton("🏠 Назад в меню", callback_data="home")]
        ]
        try:
            await query.message.delete()
        except:
            pass
        await update.effective_chat.send_message(msg, parse_mode='Markdown', reply_markup=InlineKeyboardMarkup(keyboard))
    except Exception as e:
        logger.error(f"resignal error: {e}")
        keyboard = [[InlineKeyboardButton("🏠 Назад в меню", callback_data="home")]]
        await update.effective_chat.send_message(
            f"❌ Ошибка: {str(e)}",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )

async def back_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    back_to = query.data
    if back_to == "back_to_section":
        try:
            await query.message.delete()
        except:
            pass
        await go(update, context)
    elif back_to == "back_to_asset":
        asset = context.user_data.get('asset')
        if asset:
            try:
                await query.message.delete()
            except:
                pass
            await asset_selected(update, context)
        else:
            await go(update, context)
    elif back_to == "go":
        await go(update, context)
    elif back_to == "home":
        try:
            await query.message.delete()
        except:
            pass
        await go(update, context)
    else:
        await go(update, context)

async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logger.error(f"Update {update} caused error {context.error}")

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
