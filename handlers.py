from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
import logging
import openai

import storage
from config import TOKEN

logger = logging.getLogger(__name__)

# /start команда
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [[InlineKeyboardButton("Начать", callback_data='start')]]
    reply_markup = InlineKeyboardMarkup(keyboard)

    if update.message:
        await update.message.reply_text(
            "Привет! Нажмите кнопку «Начать» для ввода API ключа OpenAI.",
            reply_markup=reply_markup
        )
    elif update.callback_query:
        await update.callback_query.message.edit_text(
            "Привет! Нажмите кнопку «Начать» для ввода API ключа OpenAI."
        )


# Обработчик кнопки Stop
async def stop_callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = query.from_user.id
    await query.answer()

    logger.info(f"Stop pressed by user {user_id}")

    job = storage.user_jobs.get(user_id)
    if job:
        job.schedule_removal()
        del storage.user_jobs[user_id]
        await query.edit_message_text("Периодическая публикация остановлена.")
        logger.info(f"Job stopped for user {user_id}")
    else:
        await query.answer("Публикация уже не активна.", show_alert=True)
        logger.info(f"No active job for user {user_id}")


# Кнопки: Начать, Далее (тут только переход к вводу каналов)
async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = query.from_user.id
    await query.answer()

    if query.data == 'start':
        storage.waiting_for_api_key.add(user_id)
        await query.message.edit_text("Введите API ключ для использования ChatGPT:")
        return

    if query.data == "channels_done":
        if not storage.user_selected_channels.get(user_id):
            await query.answer("Выберите хотя бы один канал!", show_alert=True)
            return

        storage.waiting_for_channel_selection.discard(user_id)
        storage.waiting_for_prompt.add(user_id)
        await query.message.edit_text("Теперь введите промпт, который бот будет публиковать в выбранные каналы.")
        return

    if query.data == "stop":
        await stop_callback_handler(update, context)
        return


# Сообщения от пользователя
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    text = update.message.text.strip()

    # Шаг 1: API ключ
    if user_id in storage.waiting_for_api_key:
        storage.user_api_keys[user_id] = text
        storage.waiting_for_api_key.remove(user_id)
        storage.waiting_for_channel_ids.add(user_id)
        await update.message.reply_text(
            "Введите ID каналов через запятую, например: -1001234567890,-1009876543210"
        )
        return

    # Шаг 2: Ввод ID каналов
    if user_id in storage.waiting_for_channel_ids:
        channel_ids = {ch.strip() for ch in text.split(",") if ch.strip()}
        if not channel_ids:
            await update.message.reply_text("Пожалуйста, введите хотя бы один ID канала.")
            return

        storage.user_selected_channels[user_id] = channel_ids
        storage.waiting_for_channel_ids.remove(user_id)
        storage.waiting_for_prompt.add(user_id)

        await update.message.reply_text(
            f"Каналы сохранены: {', '.join(channel_ids)}\n\nТеперь введите промпт, который бот будет публиковать."
        )
        return

    # Шаг 3: Промпт
    if user_id in storage.waiting_for_prompt:
        storage.user_prompts[user_id] = text
        storage.waiting_for_prompt.remove(user_id)
        storage.waiting_for_interval.add(user_id)
        await update.message.reply_text("Промпт сохранён! Введите интервал в минутах.")
        return

    # Шаг 4: Интервал
    if user_id in storage.waiting_for_interval:
        try:
            interval = int(text)
            if interval <= 0:
                raise ValueError
        except ValueError:
            await update.message.reply_text("Введите положительное число минут.")
            return

        storage.user_intervals[user_id] = interval
        storage.waiting_for_interval.remove(user_id)

        # Отмена предыдущей задачи, если есть
        if user_id in storage.user_jobs:
            storage.user_jobs[user_id].schedule_removal()

        # Запуск новой задачи с периодической публикацией
        job = context.application.job_queue.run_repeating(
            publish_prompt, interval=interval * 60, first=0, data=user_id
        )
        storage.user_jobs[user_id] = job

        # Отправляем сообщение с кнопкой Stop для отмены
        keyboard = [[InlineKeyboardButton("Stop", callback_data="stop")]]
        reply_markup = InlineKeyboardMarkup(keyboard)

        await update.message.reply_text(
            f"Публикация настроена каждые {interval} минут.",
            reply_markup=reply_markup
        )
        return

    # Обычное сообщение (чат)
    if user_id not in storage.user_api_keys:
        await update.message.reply_text("Сначала нажмите «Начать» и введите API ключ.")
        return

    openai.api_key = storage.user_api_keys[user_id]

    try:
        response = openai.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": text}]
        )
        answer = response.choices[0].message.content
    except Exception as e:
        logger.error(f"OpenAI error: {e}")
        answer = "Произошла ошибка при обращении к ChatGPT."

    await update.message.reply_text(answer)

    # Отправка в выбранные каналы
    for channel_id in storage.user_selected_channels.get(user_id, []):
        try:
            await context.bot.send_message(
                chat_id=channel_id,
                text=f"<b>Пользователь:</b>\n{text}\n\n<b>Ответ:</b>\n{answer}",
                parse_mode='HTML'
            )
        except Exception as e:
            logger.error(f"Ошибка отправки в канал {channel_id}: {e}")


# Периодическая публикация
async def publish_prompt(context: ContextTypes.DEFAULT_TYPE):
    user_id = context.job.data
    api_key = storage.user_api_keys.get(user_id)
    prompt = storage.user_prompts.get(user_id)
    channels = storage.user_selected_channels.get(user_id)

    if not api_key or not prompt or not channels:
        logger.warning(f"Нет данных для пользователя {user_id}, удаляю задачу.")
        context.job.schedule_removal()
        return

    openai.api_key = api_key

    try:
        response = openai.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": prompt}]
        )
        answer = response.choices[0].message.content
    except Exception as e:
        logger.error(f"OpenAI error: {e}")
        return

    for channel_id in channels:
        try:
            await context.bot.send_message(
                chat_id=channel_id,
                text=f"<b>Авто-публикация</b>\n\n<b>Промпт:</b>\n{prompt}\n\n<b>Ответ:</b>\n{answer}",
                parse_mode='HTML'
            )
        except Exception as e:
            logger.error(f"Ошибка отправки в канал {channel_id}: {e}")
