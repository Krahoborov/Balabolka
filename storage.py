# === storage.py ===
import json
from collections import defaultdict

user_api_keys = {}
user_prompts = {}
user_prompt_lists = defaultdict(list)
user_prompt_indexes = defaultdict(int)
user_intervals = {}
user_jobs = {}
user_selected_channels = defaultdict(set)

waiting_for_api_key = set()
waiting_for_channel_selection = set()
waiting_for_prompt = set()
waiting_for_interval = set()

try:
    with open("channels.json", "r", encoding="utf-8") as f:
        CHANNEL_OPTIONS = json.load(f)
except FileNotFoundError:
    CHANNEL_OPTIONS = {}

known_channels = CHANNEL_OPTIONS

def save_channels():
    with open("channels.json", "w", encoding="utf-8") as f:
        json.dump(CHANNEL_OPTIONS, f, ensure_ascii=False, indent=2)

def add_channel(channel_id: str, title: str):
    CHANNEL_OPTIONS[channel_id] = title
    save_channels()
