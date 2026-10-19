# openflow-sdk-py — паспорт проекта

> Для агентов Manager. Сгенерировано автоматически 2026-10-19 по коду репозитория, проверь и поправь при необходимости.

**Что это.** Тонкий Python SDK и CLI (пакет `openflow`) для openflowmcp.com: один ключ вида `fk_...` даёт LLM-чат (Anthropic/OpenAI/Gemini-совместимый), генерацию изображений, видео и голоса поверх пула собственных Google-аккаунтов. Для разработчиков, которым нужен доступ к моделям из Python-кода или через обёртки над популярными coding-CLI.
**Стек.** Python >=3.10; единственная runtime-зависимость httpx>=0.27; сборка hatchling; тесты pytest + pytest-asyncio + respx; опционально rich
**Статус.** активен (все коммиты от 2026-10-09, релиз 0.1.0, alpha)
**Где работает.** Неизвестно: в репозитории нет деплоя/серверной части. Это клиентская библиотека/CLI, которая работает против внешнего сервиса https://openflowmcp.com (он в этом репо не hosted).

## Запуск локально
- `pip install -e '.[dev]'`
- `export OPENFLOW_API_KEY=fk_...`
- `openflow doctor`
- `openflow chat "..."`

## Проверка (тесты, линтер, сборка)
- `python -m pytest`

## Деплой
Неизвестно: публикация в PyPI из репозитория не описана; README предлагает установку напрямую из GitHub (pip install git+https://github.com/molkex/openflow-sdk-py.git). CI/пайплайнов в файлах нет.

## Важные места
- `openflow/client.py` — основной HTTP-клиент OpenFlow/AsyncOpenFlow: чат, стриминг, image/video/voice, маршрутизация по аккаунтам
- `openflow/cli.py` — CLI `openflow`: REPL, chat, models, accounts, image/video/voice, doctor, config
- `openflow/wrappers.py` — обёртки openflow-code / openflow-aider / openflow-codex / openflow-cursor
- `openflow/errors.py` — маппинг ошибок API на AuthError/QuotaError/UpstreamError
- `openflow/models.py` — модели ответов (usage, urls, job_id и т.п.)
- `pyproject.toml` — зависимости, entry points CLI, конфиг pytest
- `tests/e2e/test_journey_sdk_python.py` — e2e-сценарии прохождения SDK-пути

## Переменные окружения (только имена, значения — не в git)
- `OPENFLOW_API_KEY`
- `OPENFLOW_BASE_URL`

## Осторожно
- API-ключ `fk_...`: не логировать и не коммитить; `openflow doctor` и e2e-тесты могут ходить в реальный сервис
- маршрутизация на конкретные аккаунты (account_email / account_tag) — ошибка привязки уводит трафик на чужой/не тот аккаунт пула
- base URL (OPENFLOW_BASE_URL) — подмена легко ломает совместимость и уводит ключ на сторонний хост
- имена entry points в pyproject (openflow-code/-aider/-codex/-cursor): переименование ломает установленные обёртки у пользователей
- wrappers.py перезаписывает файлы в домашней директории пользователя (~/.cursor/mcp.json) — трогать осторожно
