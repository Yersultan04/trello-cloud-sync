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


def telegram(text: str) -> None:
    url = f"https://api.telegram.org/bot{os.environ['TELEGRAM_BOT_TOKEN']}/sendMessage"
    data = urllib.parse.urlencode({"chat_id": os.environ["TELEGRAM_CHAT_ID"],
                                   "text": text}).encode()
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

    in_prog = [c for c in cards if id_to_col.get(c["idList"]) == IN_PROGRESS]
    up_next = sorted([c for c in cards if id_to_col.get(c["idList"]) == "Up Next"],
                     key=quad)

    lines = ["☀️ Приоритеты на сегодня", ""]

    wip = f"  ⚠️ WIP {len(in_prog)} > {WIP_LIMIT} — доводи, а не начинай!" if len(in_prog) > WIP_LIMIT else ""
    lines.append(f"🔨 В работе ({len(in_prog)}){wip}")
    if in_prog:
        for c in in_prog[:6]:
            p = project(c)
            lines.append(f"  • {c['name']}" + (f" [{p}]" if p else ""))
    else:
        lines.append("  — пусто")

    lines.append("")
    lines.append("🎯 Дальше (по Эйзенхауэру)")
    if up_next:
        for c in up_next[:8]:
            _, q = quad(c)
            p = project(c)
            lines.append(f"  {q} · {c['name']}" + (f" [{p}]" if p else ""))
    else:
        lines.append("  — пусто")

    telegram("\n".join(lines))
    print("digest отправлен:", len(in_prog), "в работе,", len(up_next), "дальше")


if __name__ == "__main__":
    main()
