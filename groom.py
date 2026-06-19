"""Board grooming (cloud): archive stale Done/Q4 cards, flag stuck In Progress.

Runs daily. Keeps the board clean automatically:
  - Done cards inactive > 14 days        -> archive
  - Q4 "Потом" cards inactive > 30 days  -> archive (Eisenhower: eliminate)
  - In Progress cards inactive > 5 days  -> add "⏳ Застряло" label
  - removes the stale label from cards that left In Progress

Secrets via env: TRELLO_API_KEY, TRELLO_TOKEN
"""
from __future__ import annotations

import json
import os
import urllib.parse
import urllib.request
from datetime import datetime, timezone

BOARD = "6a34f4c87d7de7875bfaaf88"
TKEY = os.environ["TRELLO_API_KEY"]
TTOK = os.environ["TRELLO_TOKEN"]

DONE_DAYS = 14
Q4_DAYS = 30
STALE_DAYS = 5
IN_PROGRESS = "In Progress (WIP <= 3)"
Q4_LABEL = "Q4 Потом"
STALE_LABEL = "⏳ Застряло"


def trello(method: str, path: str, **params) -> object:
    params.update(key=TKEY, token=TTOK)
    url = f"https://api.trello.com/1/{path}?{urllib.parse.urlencode(params)}"
    with urllib.request.urlopen(urllib.request.Request(url, method=method), timeout=25) as r:
        body = r.read().decode()
    return json.loads(body) if body.strip() else None


def age_days(iso: str, now: datetime) -> int:
    dt = datetime.fromisoformat(iso.replace("Z", "+00:00"))
    return (now - dt).days


def main() -> None:
    now = datetime.now(timezone.utc)
    lists = trello("GET", f"boards/{BOARD}/lists", fields="name")
    id_to_col = {l["id"]: l["name"] for l in lists}
    labels = trello("GET", f"boards/{BOARD}/labels", fields="name")
    label_id = {l["name"]: l["id"] for l in labels if l["name"]}
    stale_lid = label_id.get(STALE_LABEL)
    q4_lid = label_id.get(Q4_LABEL)

    cards = trello("GET", f"boards/{BOARD}/cards",
                   fields="name,idList,idLabels,dateLastActivity")
    archived = stale_added = stale_removed = 0

    for c in cards:
        col = id_to_col.get(c["idList"], "?")
        days = age_days(c["dateLastActivity"], now)
        labels_on = c.get("idLabels", [])
        cid = c["id"]

        # archive old Done
        if col == "Done" and days > DONE_DAYS:
            trello("PUT", f"cards/{cid}", closed="true")
            archived += 1
            print(f"архив (Done {days}д): {c['name']}")
            continue
        # archive old Q4 (eliminate)
        if q4_lid in labels_on and days > Q4_DAYS and col != "Done":
            trello("PUT", f"cards/{cid}", closed="true")
            archived += 1
            print(f"архив (Q4 {days}д): {c['name']}")
            continue
        # stale flag on In Progress
        if stale_lid:
            is_stale = col == IN_PROGRESS and days > STALE_DAYS
            has = stale_lid in labels_on
            if is_stale and not has:
                trello("POST", f"cards/{cid}/idLabels", value=stale_lid)
                trello("POST", f"cards/{cid}/actions/comments",
                       text=f"⏳ Висит {days} дней без активности — доводим или разблокируем?")
                stale_added += 1
                print(f"застряло ({days}д): {c['name']}")
            elif has and not is_stale:
                trello("DELETE", f"cards/{cid}/idLabels/{stale_lid}")
                stale_removed += 1

    print(f"Готово. Архив: {archived}, помечено застрявших: {stale_added}, снято: {stale_removed}")


if __name__ == "__main__":
    main()
