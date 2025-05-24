import logging
from telegram.ext import (
    ApplicationBuilder, CommandHandler, CallbackQueryHandler,
    MessageHandler, ChatMemberHandler, filters
)
import handlers

# === Настройка логирования ===
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)

# Снижаем уровень логов для httpx (подавляем INFO)
logging.getLogger("httpx").setLevel(logging.WARNING)

# Вставьте свой Telegram Token
TELEGRAM_TOKEN = "7978941282:AAE4DDfhL37SnzjPA6iaghDxB_y5Yspzocs"

def main():
    application = ApplicationBuilder().token(TELEGRAM_TOKEN).build()

    # Обработчики
    application.add_handler(CommandHandler("start", handlers.start))
    application.add_handler(CallbackQueryHandler(handlers.button_handler))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handlers.handle_message))
    application.add_handler(ChatMemberHandler(handlers.handle_my_chat_member, ChatMemberHandler.MY_CHAT_MEMBER))

    # Запуск бота
    application.run_polling()

if __name__ == "__main__":
    main()
