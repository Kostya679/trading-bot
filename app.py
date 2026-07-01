import os
from flask import Flask
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes

BOT_TOKEN = os.getenv("BOT_TOKEN")

if not BOT_TOKEN:
    raise ValueError("BOT_TOKEN not set")

# Flask для Render
app_flask = Flask(__name__)

@app_flask.route('/')
def home():
    return "Bot is running!"

# Обработчик команды /start
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("✅ Бот работает! Привет!")

def main():
    # Запускаем Flask в фоновом потоке
    from threading import Thread
    def run_flask():
        app_flask.run(host='0.0.0.0', port=int(os.environ.get('PORT', 10000)))
    Thread(target=run_flask).start()

    # Запускаем бота
    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    print("Бот запущен и готов к работе!")
    app.run_polling()

if __name__ == "__main__":
    main()
