"""Cloud Trello sync (GitHub Actions): poll repos -> Groq -> move/create cards.

Runs on a schedule in GitHub's cloud (no laptop needed). Reads new commits per
project from the GitHub API, asks Groq to map each commit to a card + column,
applies moves on the Trello board. State (last sha per project) persists in
state.json, committed back by the workflow.

Secrets via env: GROQ_API_KEY, TRELLO_API_KEY, TRELLO_TOKEN, GH_PAT
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
STATE_PATH = Path(__file__).resolve().parent / "state.json"

GROQ_KEY = os.environ["GROQ_API_KEY"]
TKEY = os.environ["TRELLO_API_KEY"]
TTOK = os.environ["TRELLO_TOKEN"]
GH_PAT = os.environ["GH_PAT"]

# project label -> GitHub owner/repo (Haul excluded: handled by local hook)
PROJECTS = {
    "Bilim": "Yersultan04/bilim-ai",
    "Med Triage": "Yersultan04/incident-compass",
    "Elza": "baxromov/elizeja-ai",
    "KazBench": "Yersultan04/kazbench",
    "Gottfried": "Yersultan04/gottfried",
    "Job Search": "Yersultan04/job-search",
}

SYS_PROMPT = (
    "Ты — менеджер Kanban-доски. Тебе дают НОВЫЕ git-коммиты по проекту и текущие "
    "карточки этого проекта (id, название, колонка). Отрази работу на доске.\n"
    "ГЛАВНОЕ: сначала ПОПЫТАЙСЯ сопоставить коммит с существующей карточкой по смыслу. "
    "Создавай новую (card='NEW') ТОЛЬКО если ни одна карточка не относится к теме коммита.\n"
    "Коммит = ЗАВЕРШЁННАЯ работа по своей теме. По умолчанию:\n"
    "  - коммит закрывает суть карточки → 'Done'\n"
    "  - 'In Progress (WIP <= 3)' только если в коммите явно промежуточный шаг (wip/part/начал)\n"
    "  - PR/review → 'In Review'; блокер → 'Blocked'\n"
    "Новая карточка: работа сделана коммитом → 'Done'; явное начало большой темы → "
    "'In Progress (WIP <= 3)'; иначе 'Backlog'.\n"
    "Колонки дословно: Triage, Backlog, Up Next, 'In Progress (WIP <= 3)', In Review, Blocked, Done.\n"
    'Ответ СТРОГО JSON: {"actions":[{"card":"<id|NEW>","name":"<если NEW: имя>",'
    '"column":"<колонка>","comment":"<1 строка: что сделано>"}]}'
)


def gh(path: str) -> object:
    req = urllib.request.Request(
        f"https://api.github.com/{path}",
        headers={"Authorization": f"Bearer {GH_PAT}",
                 "Accept": "application/vnd.github+json", "User-Agent": "trello-sync"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read().decode())


def trello(method: str, path: str, **params) -> object:
    params.update(key=TKEY, token=TTOK)
    url = f"https://api.trello.com/1/{path}?{urllib.parse.urlencode(params)}"
    with urllib.request.urlopen(urllib.request.Request(url, method=method), timeout=25) as r:
        body = r.read().decode()
    return json.loads(body) if body.strip() else None


def commits_since(repo: str, since: str | None, limit: int) -> tuple[list[dict], str | None]:
    data = gh(f"repos/{repo}/commits?per_page={max(limit, 30)}")
    head = data[0]["sha"] if data else since
    out: list[dict] = []
    for c in data:
        if since and c["sha"] == since:
            break
        lines = c["commit"]["message"].splitlines()
        out.append({"sha": c["sha"][:9], "subject": lines[0] if lines else "",
                    "body": "\n".join(lines[1:])[:300]})
        if not since and len(out) >= limit:
            break
    return out, head


def decide(commits: list[dict], cards: list[dict]) -> list[dict]:
    client = Groq(api_key=GROQ_KEY)
    payload = {"commits": commits,
               "cards": [{"id": c["id"], "name": c["name"], "column": c["column"]} for c in cards]}
    resp = client.chat.completions.create(
        model=GROQ_MODEL, temperature=0.1, response_format={"type": "json_object"},
        messages=[{"role": "system", "content": SYS_PROMPT},
                  {"role": "user", "content": json.dumps(payload, ensure_ascii=False)}])
    return json.loads(resp.choices[0].message.content).get("actions", [])


def main() -> None:
    lists = trello("GET", f"boards/{BOARD}/lists", fields="name")
    col_id = {l["name"]: l["id"] for l in lists}
    id_to_col = {l["id"]: l["name"] for l in lists}
    labels = trello("GET", f"boards/{BOARD}/labels", fields="name")
    label_id = {l["name"]: l["id"] for l in labels if l["name"]}
    all_cards = trello("GET", f"boards/{BOARD}/cards", fields="name,idList,idLabels")

    state = json.loads(STATE_PATH.read_text(encoding="utf-8")) if STATE_PATH.exists() else {}

    for project, repo in PROJECTS.items():
        plabel = label_id.get(project)
        since = state.get(project)

        if since is None:  # first cloud run: baseline only
            try:
                _, head = commits_since(repo, None, 1)
            except Exception as exc:
                print(f"[{project}] недоступен: {exc}")
                continue
            if head:
                state[project] = head
            print(f"[{project}] baseline {head[:9] if head else '-'}")
            continue

        try:
            commits, head = commits_since(repo, since, 10)
        except Exception as exc:
            print(f"[{project}] недоступен: {exc}")
            continue
        if not commits:
            print(f"[{project}] новых коммитов нет")
            continue

        cards = [{"id": c["id"], "name": c["name"], "column": id_to_col.get(c["idList"], "?")}
                 for c in all_cards if not plabel or plabel in c.get("idLabels", [])]
        try:
            actions = decide(commits, cards)
        except Exception as exc:
            print(f"[{project}] Groq ошибка: {exc}")
            continue

        print(f"[{project}] коммитов {len(commits)}, решений {len(actions)}")
        for a in actions:
            target = col_id.get(a.get("column", ""))
            comment = a.get("comment", "")
            if not target:
                continue
            if a.get("card") == "NEW":
                name = (a.get("name") or "").strip()[:120]
                if not name:
                    continue
                extra = {"idLabels": plabel} if plabel else {}
                card = trello("POST", "cards", idList=target, name=name,
                              desc=f"Авто из коммита.\n{comment}", **extra)
                if card and comment:
                    trello("POST", f"cards/{card['id']}/actions/comments", text=comment)
                print(f"   + СОЗДАТЬ «{name}» → {a['column']}")
            else:
                cid = a.get("card")
                trello("PUT", f"cards/{cid}", idList=target)
                if comment:
                    trello("POST", f"cards/{cid}/actions/comments", text=comment)
                print(f"   → ДВИНУТЬ {cid} → {a['column']}")

        if head:
            state[project] = head

    STATE_PATH.write_text(json.dumps(state, ensure_ascii=False, indent=1), encoding="utf-8")
    print("Готово.")


if __name__ == "__main__":
    main()
