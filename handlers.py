# === handlers.py ===
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ChatMemberUpdated
from telegram.ext import ContextTypes, ChatMemberHandler
import logging
import openai

import storage

logger = logging.getLogger(__name__)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [[InlineKeyboardButton("Начать", callback_data='start')]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text(
        "Привет! Нажмите кнопку «Начать» для ввода API ключа OpenAI.",
        reply_markup=reply_markup
    )

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = query.from_user.id
    await query.answer()

    if query.data == 'start':
        storage.waiting_for_api_key.add(user_id)
        await query.message.edit_text("Введите API ключ OpenAI:")
        return

    if query.data.startswith("toggle_channel:"):
        channel_id = query.data.split(":")[1]
        selected = storage.user_selected_channels.setdefault(user_id, set())
        if channel_id in selected:
            selected.remove(channel_id)
        else:
            selected.add(channel_id)

        keyboard = [
            [InlineKeyboardButton(
                f"{'✅' if ch_id in selected else '☑️'} {ch_name}",
                callback_data=f"toggle_channel:{ch_id}"
            )]
            for ch_id, ch_name in storage.known_channels.items()
        ]
        keyboard.append([InlineKeyboardButton("Далее", callback_data="channels_done")])
        await query.edit_message_reply_markup(reply_markup=InlineKeyboardMarkup(keyboard))
        return

    if query.data == "channels_done":
        if not storage.user_selected_channels.get(user_id):
            await query.answer("Выберите хотя бы один канал!", show_alert=True)
            return
        storage.waiting_for_channel_selection.discard(user_id)
        storage.waiting_for_prompt.add(user_id)
        await query.message.edit_text("Введите промпт для публикации в каналах.")
        return

    if query.data == "start_generation":
        if not storage.user_prompt_lists.get(user_id):
            await query.answer("Вы не добавили ни одного промпта!", show_alert=True)
            return

        storage.user_prompts[user_id] = storage.user_prompt_lists[user_id]
        storage.user_prompt_lists[user_id] = []
        storage.user_prompt_indexes[user_id] = 0
        storage.waiting_for_prompt.discard(user_id)
        storage.waiting_for_interval.add(user_id)

        await query.message.edit_text("Введите интервал публикации (в минутах):")
        return

    if query.data == "stop":
        job = storage.user_jobs.get(user_id)
        if job:
            job.schedule_removal()
            del storage.user_jobs[user_id]
            await query.message.edit_text("Публикация остановлена.")
        else:
            await query.answer("Публикация уже остановлена.", show_alert=True)

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    text = update.message.text.strip()

    if user_id in storage.waiting_for_api_key:
        storage.user_api_keys[user_id] = text
        storage.waiting_for_api_key.remove(user_id)
        storage.waiting_for_channel_selection.add(user_id)
        storage.user_selected_channels[user_id] = set()

        keyboard = [
            [InlineKeyboardButton(
                f"☑️ {name}", callback_data=f"toggle_channel:{ch_id}"
            )]
            for ch_id, name in storage.known_channels.items()
        ]
        keyboard.append([InlineKeyboardButton("Далее", callback_data="channels_done")])
        reply_markup = InlineKeyboardMarkup(keyboard)

        await update.message.reply_text("Выберите каналы для публикации:", reply_markup=reply_markup)
        return

    if user_id in storage.waiting_for_prompt:
        if user_id not in storage.user_prompt_lists:
            storage.user_prompt_lists[user_id] = []
        storage.user_prompt_lists[user_id].append(text)

        keyboard = [[InlineKeyboardButton("Начать генерацию", callback_data="start_generation")]]
        await update.message.reply_text(
            f"Добавлен промпт: «{text}»\n\nВы можете ввести ещё или нажать кнопку для начала генерации.",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        return

    if user_id in storage.waiting_for_interval:
        try:
            interval = int(text)
            if interval <= 0:
                raise ValueError()
        except ValueError:
            await update.message.reply_text("Введите положительное целое число.")
            return

        storage.user_intervals[user_id] = interval
        storage.waiting_for_interval.remove(user_id)

        if user_id in storage.user_jobs:
            storage.user_jobs[user_id].schedule_removal()

        await publish_prompt_now(context, user_id)

        job = context.application.job_queue.run_repeating(
            publish_prompt, interval=interval * 60, first=interval * 60, data=user_id
        )
        storage.user_jobs[user_id] = job

        keyboard = [[InlineKeyboardButton("Stop", callback_data="stop")]]
        await update.message.reply_text(
            f"Генерация запущена каждые {interval} минут.",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        return

    if user_id not in storage.user_api_keys:
        await update.message.reply_text("Сначала нажмите «Начать» и введите API ключ.")
        return

    await chat_and_respond(update, context, user_id, text)

async def chat_and_respond(update, context, user_id, prompt_text):
    openai.api_key = storage.user_api_keys[user_id]
    try:
        response = openai.chat.completions.create(
            model="gpt-4-turbo",
            messages=[{"role": "user", "content": prompt_text}]
        )
        answer = response.choices[0].message.content
    except Exception as e:
        logger.error(f"OpenAI error: {e}")
        answer = "Ошибка при обращении к OpenAI."

    await update.message.reply_text(answer)

async def publish_prompt_now(context, user_id):
    api_key = storage.user_api_keys.get(user_id)
    prompt_list = storage.user_prompts.get(user_id, [])
    index = storage.user_prompt_indexes.get(user_id, 0)
    channels = storage.user_selected_channels.get(user_id)

    if not api_key or not prompt_list or not channels:
        return

    prompt = prompt_list[index]
    storage.user_prompt_indexes[user_id] = (index + 1) % len(prompt_list)

    openai.api_key = api_key
    try:
        response = openai.chat.completions.create(
            model="gpt-4",
            messages=[{"role": "user", "content": prompt}]
        )
        answer = response.choices[0].message.content
    except Exception as e:
        logger.error(f"Ошибка OpenAI: {e}")
        return

    fact_number = index + 1

    for channel_id in channels:
        try:
            await context.bot.send_message(
                chat_id=channel_id,
                text=f"{answer}",
                parse_mode='HTML'
            )
        except Exception as e:
            logger.error(f"Ошибка отправки в канал {channel_id}: {e}")

async def publish_prompt(context: ContextTypes.DEFAULT_TYPE):
    user_id = context.job.data
    await publish_prompt_now(context, user_id)

async def handle_my_chat_member(update: Update, context: ContextTypes.DEFAULT_TYPE):
    member_update: ChatMemberUpdated = update.my_chat_member
    if member_update.new_chat_member.status in ["administrator", "member"]:
        chat = member_update.chat
        if chat.type == "channel":
            storage.known_channels[str(chat.id)] = chat.title
            storage.save_channels()
            logger.info(f"Бот добавлен в канал: {chat.title} ({chat.id})")
