# Хранилища для состояний и данных пользователей

user_api_keys = {}
waiting_for_api_key = set()

user_selected_channels = {}  # user_id -> set(channel_ids)
waiting_for_channel_selection = set()

waiting_for_channel_ids = set()  # Для отдельного шага ввода ID каналов

user_prompts = {}
waiting_for_prompt = set()

user_intervals = {}
waiting_for_interval = set()

user_jobs = {}
