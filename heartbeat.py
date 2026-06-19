"""Weekly health-check: verify Trello/GitHub/Groq reachable, ping Telegram.

Positive confirmation that the automation is alive (absence of the weekly ping =
something is wrong). Also flags a specific broken component.

Secrets via env: TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, GROQ_API_KEY,
TRELLO_API_KEY, TRELLO_TOKEN, GH_PAT
"""
from __future__ import annotations

import json
import os
import urllib.parse
import urllib.request

BOARD = "6a34f4c87d7de7875bfaaf88"


def check_trello() -> str:
    url = (f"https://api.trello.com/1/boards/{BOARD}?fields=name"
           f"&key={os.environ['TRELLO_API_KEY']}&token={os.environ['TRELLO_TOKEN']}")
    with urllib.request.urlopen(url, timeout=20) as r:
        json.loads(r.read())
    return "🟢"


def check_github() -> str:
    req = urllib.request.Request(
        "https://api.github.com/user",
        headers={"Authorization": f"Bearer {os.environ['GH_PAT']}",
                 "User-Agent": "heartbeat"})
    with urllib.request.urlopen(req, timeout=20) as r:
        json.loads(r.read())
    return "🟢"


def check_groq() -> str:
    from groq import Groq
    Groq(api_key=os.environ["GROQ_API_KEY"]).models.list()
    return "🟢"


def telegram(text: str) -> None:
    url = f"https://api.telegram.org/bot{os.environ['TELEGRAM_BOT_TOKEN']}/sendMessage"
    data = urllib.parse.urlencode({"chat_id": os.environ["TELEGRAM_CHAT_ID"],
                                   "text": text}).encode()
    urllib.request.urlopen(urllib.request.Request(url, data=data), timeout=20).read()


def main() -> None:
    results = {}
    for name, fn in [("Trello", check_trello), ("GitHub", check_github), ("Groq", check_groq)]:
        try:
            results[name] = fn()
        except Exception as exc:
            results[name] = f"🔴 {str(exc)[:60]}"

    all_ok = all(v == "🟢" for v in results.values())
    head = "🟢 Автоматизация работает" if all_ok else "🔴 Проблема в автоматизации"
    body = "\n".join(f"{name}: {status}" for name, status in results.items())
    telegram(f"{head}\n{body}")
    print(head, results)


if __name__ == "__main__":
    main()
