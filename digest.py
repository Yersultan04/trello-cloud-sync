"""Morning priorities digest (cloud) -> Telegram.

Each morning tells you what to focus on, ordered by the Eisenhower matrix, plus a
WIP warning. The board drives the day instead of just mirroring the past.

Secrets via env: TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, TRELLO_API_KEY, TRELLO_TOKEN
"""
from __future__ import annotations

import json
import os
import urllib.parse
import urllib.request

BOARD = "6a34f4c87d7de7875bfaaf88"
IN_PROGRESS = "In Progress (WIP <= 3)"
WIP_LIMIT = 3
# Eisenhower rank for ordering Up Next
Q_RANK = {"Q1 Срочно+Важно": 0, "Q2 Важно (план)": 1, "Q3 Делегировать": 2, "Q4 Потом": 3}
Q_SHORT = {"Q1 Срочно+Важно": "Q1", "Q2 Важно (план)": "Q2",
           "Q3 Делегировать": "Q3", "Q4 Потом": "Q4"}


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


def main() -> None:
    lists = trello(f"boards/{BOARD}/lists", fields="name")
    id_to_col = {l["id"]: l["name"] for l in lists}
    labels = {l["id"]: l["name"] for l in trello(f"boards/{BOARD}/labels", fields="name")}
    cards = trello(f"boards/{BOARD}/cards", fields="name,idList,idLabels")

    def quad(c: dict) -> tuple[int, str]:
        for lid in c.get("idLabels", []):
            n = labels.get(lid, "")
            if n in Q_RANK:
                return Q_RANK[n], Q_SHORT[n]
        return 4, "—"

    def project(c: dict) -> str:
        projs = {"Haul", "Bilim", "Med Triage", "Elza", "KazBench", "Gottfried", "Job Search"}
        for lid in c.get("idLabels", []):
            if labels.get(lid) in projs:
                return labels[lid]
        return ""

    Q_EMOJI = {0: "🔴", 1: "🟡", 2: "🟠", 3: "⚪", 4: "▪️"}

    in_prog = [c for c in cards if id_to_col.get(c["idList"]) == IN_PROGRESS]
    up_next = sorted([c for c in cards if id_to_col.get(c["idList"]) == "Up Next"],
                     key=quad)

    def row(c: dict) -> str:
        rank, _ = quad(c)
        p = project(c)
        tail = f"  <i>{esc(p)}</i>" if p else ""
        return f"{Q_EMOJI[rank]} {esc(c['name'])}{tail}"

    L = ["☀️ <b>Приоритеты на сегодня</b>", ""]

    head = f"🔨 <b>В работе</b> · {len(in_prog)}"
    if len(in_prog) > WIP_LIMIT:
        head += f"  ⚠️ &gt; {WIP_LIMIT}, доводи!"
    L.append(head)
    if in_prog:
        L += [f"      {row(c)}" for c in in_prog[:6]]
    else:
        L.append("      <i>пусто</i>")

    L += ["", "🎯 <b>Дальше</b> <i>(по Эйзенхауэру)</i>"]
    if up_next:
        L += [f"      {row(c)}" for c in up_next[:8]]
    else:
        L.append("      <i>пусто</i>")

    L += ["", "<i>🔴Q1 срочно+важно 🟡Q2 важно 🟠Q3 делегировать ⚪Q4 потом</i>"]

    telegram("\n".join(L))
    print("digest отправлен:", len(in_prog), "в работе,", len(up_next), "дальше")


if __name__ == "__main__":
    main()
