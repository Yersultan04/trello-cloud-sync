"""Weekly board review (cloud) -> Telegram digest of anomalies.

Groq scans the open cards for problems (duplicates, missing project label, cards
that look done but aren't in Done, clearly wrong column) and reports them for you
to act on. Read-only — never auto-fixes, only flags.

Secrets via env: TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, GROQ_API_KEY,
TRELLO_API_KEY, TRELLO_TOKEN
"""
from __future__ import annotations

import json
import os
import urllib.parse
import urllib.request

from groq import Groq

BOARD = "6a34f4c87d7de7875bfaaf88"
PROJECTS = {"Haul", "Bilim", "Med Triage", "Elza", "KazBench", "Gottfried", "Job Search"}

SYS = (
    "Ты ревьюишь Kanban-доску. Тебе дают открытые карточки (имя, колонка, метки). "
    "Найди проблемы:\n"
    "1) duplicate — две карточки про одно и то же\n"
    "2) no_project — нет метки проекта (из списка проектов)\n"
    "3) looks_done — по имени работа сделана, но карточка не в Done\n"
    "4) wrong_column — карточка явно не в той колонке\n"
    'Ответ JSON: {"issues":[{"type":"<тип>","cards":["имя1","имя2"],"note":"<кратко>"}]} '
    "Если проблем нет — пустой список."
)


def trello(path: str, **params) -> object:
    params.update(key=os.environ["TRELLO_API_KEY"], token=os.environ["TRELLO_TOKEN"])
    url = f"https://api.trello.com/1/{path}?{urllib.parse.urlencode(params)}"
    with urllib.request.urlopen(url, timeout=20) as r:
        return json.loads(r.read().decode())


def esc(s: str) -> str:
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def telegram(text: str) -> None:
    url = f"https://api.telegram.org/bot{os.environ['TELEGRAM_BOT_TOKEN']}/sendMessage"
    data = urllib.parse.urlencode({"chat_id": os.environ["TELEGRAM_CHAT_ID"],
                                   "text": text, "parse_mode": "HTML",
                                   "disable_web_page_preview": "true"}).encode()
    urllib.request.urlopen(urllib.request.Request(url, data=data), timeout=20).read()


# служебные/почтовые карточки — не проектные задачи, в сверке не участвуют
def is_utility(name: str) -> bool:
    n = name.lower()
    return (name.startswith(("✉️", "📬")) or "ответить:" in n or "сообщение:" in n
            or "how this board works" in n or "почта" in n and "сводка" in n)


def main() -> None:
    lists = trello(f"boards/{BOARD}/lists", fields="name")
    id_to_col = {l["id"]: l["name"] for l in lists}
    labels = {l["id"]: l["name"] for l in trello(f"boards/{BOARD}/labels", fields="name")}
    cards = trello(f"boards/{BOARD}/cards", fields="name,idList,idLabels")

    items = []
    for c in cards:
        col = id_to_col.get(c["idList"], "?")
        if col == "Done" or is_utility(c["name"]):
            continue
        items.append({"name": c["name"], "column": col,
                      "labels": [labels.get(x, "") for x in c.get("idLabels", [])]})

    client = Groq(api_key=os.environ["GROQ_API_KEY"])
    resp = client.chat.completions.create(
        model="llama-3.3-70b-versatile", temperature=0.1,
        response_format={"type": "json_object"},
        messages=[{"role": "system", "content": SYS},
                  {"role": "user", "content": json.dumps(items, ensure_ascii=False)}])
    issues = json.loads(resp.choices[0].message.content).get("issues", [])

    if not issues:
        telegram("🔍 <b>Сверка доски</b>\n\nЧисто, замечаний нет 👍")
        print("чисто")
        return

    tname = {"duplicate": "♻️ Дубль", "no_project": "🏷 Нет проекта",
             "looks_done": "✅ Похоже сделано", "wrong_column": "↔️ Не та колонка"}
    lines = [f"🔍 <b>Сверка доски</b> · {len(issues)} замечаний", ""]
    for i in issues[:12]:
        lines.append(f"<b>{tname.get(i.get('type'), esc(str(i.get('type'))))}</b>")
        for card in i.get("cards", [])[:8]:
            lines.append(f"      • {esc(card)}")
        if i.get("note"):
            lines.append(f"      <i>{esc(i['note'])}</i>")
        lines.append("")
    telegram("\n".join(lines).strip())
    print(f"замечаний: {len(issues)}")


if __name__ == "__main__":
    main()
