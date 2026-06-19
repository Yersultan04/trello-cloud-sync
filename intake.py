"""Telegram task intake -> Trello (cloud, GitHub Actions).

Polls the bot for new messages, Groq parses each into {project, type, Eisenhower
quadrant, column, title}, creates a Trello card, and replies in Telegram.
Importance via Eisenhower matrix (Q1..Q4). Runs on schedule — no laptop.

Commands:
  <любой текст>   — новая задача
  /done <текст>   — закрыть задачу (в Done)
  /board          — показать Up Next + In Progress

Secrets via env: TELEGRAM_BOT_TOKEN, GROQ_API_KEY, TRELLO_API_KEY, TRELLO_TOKEN
State: tg_offset.json (offset + chat_id), committed back by the workflow.
"""
from __future__ import annotations

import json
import os
import urllib.parse
import urllib.request
from pathlib import Path

from groq import Groq

BOARD = "6a34f4c87d7de7875bfaaf88"
GROQ_MODEL = "llama-3.3-70b-versatile"
OFFSET_PATH = Path(__file__).resolve().parent / "tg_offset.json"

TG = os.environ["TELEGRAM_BOT_TOKEN"]
GROQ_KEY = os.environ["GROQ_API_KEY"]
TKEY = os.environ["TRELLO_API_KEY"]
TTOK = os.environ["TRELLO_TOKEN"]

PROJECTS = ["Haul", "Bilim", "Med Triage", "Elza", "KazBench", "Gottfried", "Job Search"]
EISENHOWER = {
    "Q1": "Q1 Срочно+Важно",
    "Q2": "Q2 Важно (план)",
    "Q3": "Q3 Делегировать",
    "Q4": "Q4 Потом",
}
# quadrant -> default column
Q_COLUMN = {"Q1": "Up Next", "Q2": "Backlog", "Q3": "Up Next", "Q4": "Backlog"}

PARSE_SYS = (
    "Ты разбираешь входящую задачу пользователя в карточку Kanban. Верни JSON.\n"
    f"Проекты: {PROJECTS} (или 'General' если не относится ни к одному).\n"
    "Тип: Feature/Bug/Chore/Research/Task.\n"
    "Матрица Эйзенхауэра — определи срочность и важность:\n"
    "  Q1 = срочно И важно; Q2 = важно, НЕ срочно; Q3 = срочно, НЕ важно; Q4 = ни то ни то.\n"
    'Ответ СТРОГО JSON: {"project":"<проект|General>","type":"<тип>","eisenhower":"Q1|Q2|Q3|Q4",'
    '"title":"<короткое имя задачи>","essence":"<суть одной строкой>"}'
)


def tg(method: str, **params) -> dict:
    url = f"https://api.telegram.org/bot{TG}/{method}"
    data = urllib.parse.urlencode(params).encode()
    with urllib.request.urlopen(urllib.request.Request(url, data=data), timeout=30) as r:
        return json.loads(r.read().decode())


def trello(method: str, path: str, **params) -> object:
    params.update(key=TKEY, token=TTOK)
    url = f"https://api.trello.com/1/{path}?{urllib.parse.urlencode(params)}"
    with urllib.request.urlopen(urllib.request.Request(url, method=method), timeout=25) as r:
        body = r.read().decode()
    return json.loads(body) if body.strip() else None


def board_meta() -> tuple[dict, dict, list]:
    lists = trello("GET", f"boards/{BOARD}/lists", fields="name")
    col_id = {l["name"]: l["id"] for l in lists}
    labels = trello("GET", f"boards/{BOARD}/labels", fields="name")
    label_id = {l["name"]: l["id"] for l in labels if l["name"]}
    id_to_col = {l["id"]: l["name"] for l in lists}
    return col_id, label_id, id_to_col


def parse_task(text: str) -> dict:
    client = Groq(api_key=GROQ_KEY)
    resp = client.chat.completions.create(
        model=GROQ_MODEL, temperature=0.2, response_format={"type": "json_object"},
        messages=[{"role": "system", "content": PARSE_SYS}, {"role": "user", "content": text}])
    return json.loads(resp.choices[0].message.content)


def find_duplicate(title: str, open_names: list[str]) -> str | None:
    if not open_names:
        return None
    client = Groq(api_key=GROQ_KEY)
    resp = client.chat.completions.create(
        model=GROQ_MODEL, temperature=0, response_format={"type": "json_object"},
        messages=[{"role": "system", "content":
                   "Есть ли в списке карточка про ТО ЖЕ самое, что новая задача? "
                   'Верни точное имя дубля или null. JSON: {"dup":"<имя|null>"}'},
                  {"role": "user", "content": json.dumps(
                      {"new": title, "cards": open_names}, ensure_ascii=False)}])
    return json.loads(resp.choices[0].message.content).get("dup")


def create_task(text: str, col_id: dict, label_id: dict, id_to_col: dict) -> str:
    p = parse_task(text)
    quad = p.get("eisenhower", "Q2")
    if quad not in EISENHOWER:
        quad = "Q2"
    column = Q_COLUMN.get(quad, "Backlog")
    title = (p.get("title") or text)[:120]

    # dedup against open cards
    cards = trello("GET", f"boards/{BOARD}/cards", fields="name,idList")
    open_names = [c["name"] for c in cards if id_to_col.get(c["idList"]) != "Done"]
    dup = find_duplicate(title, open_names)
    if dup:
        return f"♻️ Уже есть похожая, не дублирую:\n{dup}"

    labels = [label_id[EISENHOWER[quad]]]
    proj = p.get("project", "General")
    if proj in label_id:
        labels.append(label_id[proj])
    if p.get("type") in label_id:
        labels.append(label_id[p["type"]])
    trello("POST", "cards", idList=col_id[column], name=title,
           desc=f"Из Telegram.\nСуть: {p.get('essence','')}\nЭйзенхауэр: {quad}",
           idLabels=",".join(labels))
    return f"✅ {title}\n→ {column} · {quad} · {proj}"


def close_task(text: str, col_id: dict, id_to_col: dict) -> str:
    cards = trello("GET", f"boards/{BOARD}/cards", fields="name,idList")
    open_cards = [{"id": c["id"], "name": c["name"]}
                  for c in cards if id_to_col.get(c["idList"]) != "Done"]
    client = Groq(api_key=GROQ_KEY)
    resp = client.chat.completions.create(
        model=GROQ_MODEL, temperature=0, response_format={"type": "json_object"},
        messages=[{"role": "system", "content":
                   "Выбери id карточки, которую закрывает пользователь. Если нет подходящей — id:null. "
                   'JSON: {"id":"<id|null>"}'},
                  {"role": "user", "content": json.dumps(
                      {"close": text, "cards": open_cards}, ensure_ascii=False)}])
    cid = json.loads(resp.choices[0].message.content).get("id")
    if not cid:
        return f"❓ Не нашёл карточку для «{text}»"
    name = next((c["name"] for c in open_cards if c["id"] == cid), cid)
    trello("PUT", f"cards/{cid}", idList=col_id["Done"])
    return f"✅ Закрыто: {name}"


def show_board(id_to_col: dict) -> str:
    cards = trello("GET", f"boards/{BOARD}/cards", fields="name,idList")
    out = []
    for col in ["In Progress (WIP <= 3)", "Up Next"]:
        items = [c["name"] for c in cards if id_to_col.get(c["idList"]) == col]
        out.append(f"*{col}* ({len(items)})")
        out.extend(f"  • {n}" for n in items[:10]) or out.append("  —")
    return "\n".join(out)


def main() -> None:
    state = json.loads(OFFSET_PATH.read_text(encoding="utf-8")) if OFFSET_PATH.exists() else {}
    offset = state.get("offset", 0)
    updates = tg("getUpdates", offset=offset, timeout=0, allowed_updates=json.dumps(["message"]))
    if not updates.get("ok"):
        print("getUpdates fail:", updates)
        return
    results = updates.get("result", [])
    if not results:
        print("нет новых сообщений")
        return

    col_id, label_id, id_to_col = board_meta()
    for u in results:
        offset = max(offset, u["update_id"] + 1)
        msg = u.get("message") or {}
        text = (msg.get("text") or "").strip()
        chat = msg.get("chat", {}).get("id")
        if not text or not chat:
            continue
        state["chat_id"] = chat
        try:
            if text.startswith("/done"):
                reply = close_task(text[5:].strip(), col_id, id_to_col)
            elif text.startswith("/board"):
                reply = show_board(id_to_col)
            elif text.startswith("/start"):
                reply = "Привет! Пиши задачу — добавлю в Trello. /board — доска, /done <что> — закрыть."
            else:
                reply = create_task(text, col_id, label_id, id_to_col)
        except Exception as exc:
            reply = f"⚠️ Ошибка: {exc}"
        tg("sendMessage", chat_id=chat, text=reply, parse_mode="Markdown")
        print(f"обработано: {text[:50]} -> {reply[:50]}")

    state["offset"] = offset
    OFFSET_PATH.write_text(json.dumps(state, ensure_ascii=False, indent=1), encoding="utf-8")
    print("Готово.")


if __name__ == "__main__":
    main()
