# Trello Cloud Sync

Облачный планировщик: каждые 15 мин читает новые git-коммиты 6 проектов через GitHub API,
Groq сопоставляет коммит с карточкой Trello и двигает её по колонкам. Работает в облаке
GitHub Actions — ноут не нужен.

- Проекты: Bilim, Med Triage, Elza, KazBench, Gottfried, Job Search
- Haul синхронится отдельно (локальный git-хук — репо на другом аккаунте)
- Секреты: GROQ_API_KEY, TRELLO_API_KEY, TRELLO_TOKEN, GH_PAT
- Состояние: state.json (коммитится воркфлоу обратно)
