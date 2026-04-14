# MASTER PLAN: AutoStop CRM / Minimal Kanban

> Этот файл намеренно содержит живые доступы и секреты по прямому запросу владельца. Не публиковать наружу без ручной редактуры.

## 1. Назначение проекта

AutoStop CRM — рабочая CRM для автосервиса на базе kanban-доски с локальным API, MCP-коннектором, отдельным server AI worker, заказ-нарядами, печатью, кассами, сотрудниками и зарплатами.

Legacy-имена, которые все еще являются нормой:

- Python package: `minimal_kanban`
- локальная data-папка: `%APPDATA%\Minimal Kanban`
- часть старых текстов и файлов все еще использует название `Minimal Kanban`

Текущая рабочая ветка:

- `autostopCRM`

Текущий подтвержденный commit локально и на production:

- `3c06cf0caeb8f0b10027986d4de7449e9646f82b`

## 1.1. Последний maintenance-pass (2026-04-14)

В этом легком стабилизационном проходе без изменения архитектуры уже исправлены:

- MCP runtime больше не строит `base_url` и self-probe от wildcard bind host (`0.0.0.0` / `::`), а нормализует их в loopback (`127.0.0.1` / `::1`). Это убрало хрупкость readiness/debug-проверок MCP runtime.
- `GET /api/health` переведен в quiet-success routing, что убрало лишний INFO-шум в серверных логах от частых health-check запросов.
- `tests.test_mcp` больше не оставляет `anyio ResourceWarning` на незакрытых in-memory streams: тестовый helper переведен на штатный `streamable_http_client(...)`, а test teardown дочищает хвостовые `MemoryObject*Stream`.
- `ApiServer.base_url` теперь корректно нормализует wildcard/IPv6 bind hosts и формирует валидный URL для явного IPv6 (`http://[::1]:port`).

Короткая подтвержденная валидация после этих правок:

- `python -m unittest tests.test_api tests.test_mcp tests.test_mcp_main tests.test_app_startup -v` — `88 tests`, `OK`
- `python -m unittest tests.test_mcp -v` — `22 tests`, `OK`, без `ResourceWarning`
- `python scripts/run_isolated_tests.py` — `19 isolated modules`, `OK`
- import smoke для `main.py`, `main_mcp.py`, `main_agent.py` — `IMPORT_SMOKE_OK`

## 2. Текущая архитектура и основные модули

Общая схема:

```text
Desktop UI / browser UI
  -> local HTTP API
  -> CardService + domain services
  -> JsonStore / JSON data files

External GPT / ChatGPT / MCP client
  -> MCP server
  -> internal BoardApiClient
  -> local HTTP API
  -> тот же CardService / storage

Server AI worker
  -> AgentControlService / AgentStorage
  -> local HTTP API + bounded tools
  -> read -> evidence -> plan -> tools -> patch -> write -> verify
```

Основные точки входа:

- `main.py` — desktop runtime
- `main_mcp.py` — MCP runtime entrypoint
- `main_agent.py` — отдельный AI worker

Ключевые модули:

- `src/minimal_kanban/app.py` — desktop bootstrap
- `src/minimal_kanban/api/server.py` — локальный HTTP API
- `src/minimal_kanban/services/card_service.py` — основная бизнес-логика
- `src/minimal_kanban/services/snapshot_service.py` — snapshots, wall, compact reads
- `src/minimal_kanban/operator_auth.py` — operator/admin auth
- `src/minimal_kanban/repair_order.py` — заказ-наряд
- `src/minimal_kanban/printing/service.py` — печать и export
- `src/minimal_kanban/mcp/server.py` — MCP tool surface
- `src/minimal_kanban/mcp/client.py` — MCP -> local API transport
- `src/minimal_kanban/mcp/main.py` — запуск MCP runtime
- `src/minimal_kanban/agent/control.py` — queue / scheduler / heartbeat
- `src/minimal_kanban/agent/runner.py` — core orchestration
- `src/minimal_kanban/agent/tools.py` — bounded tools
- `src/minimal_kanban/agent/automotive_tools.py` — VIN / parts / DTC / fault research tools
- `src/minimal_kanban/agent/scenarios/` — deterministic autofill scenarios:
  - `vin_enrichment.py`
  - `parts_lookup.py`
  - `maintenance_lookup.py`
  - `dtc_lookup.py`
  - `fault_research.py`

## 3. Как запускать локально

Через принятые проектом PowerShell-скрипты:

```powershell
.\scripts\run_dev.ps1
.\scripts\run_mcp_server.ps1
```

Напрямую:

```powershell
.\.venv\Scripts\python.exe main.py
.\.venv\Scripts\python.exe main_mcp.py
.\.venv\Scripts\python.exe main_agent.py
```

Что делает `run_dev.ps1`:

- поднимает/создает `.venv`
- ставит `requirements.txt`
- запускает `main.py`

Что делает `run_mcp_server.ps1`:

- поднимает/обновляет `.venv`
- применяет env overrides для API/MCP
- запускает `python -m minimal_kanban.mcp.main`

Ключевые локальные default-порты:

- API: `127.0.0.1:41731`
- MCP: `127.0.0.1:41831/mcp`

## 4. Как работает на сервере

Production server:

- host: `46.8.254.243`
- repo path: `/opt/autostopcrm`
- public CRM: [https://crm.autostopcrm.ru](https://crm.autostopcrm.ru)
- public MCP: [https://crm.autostopcrm.ru/mcp](https://crm.autostopcrm.ru/mcp)

Production deploy:

```bash
cd /opt/autostopcrm
./deploy.sh
```

Что делает `deploy.sh`:

- `git fetch origin autostopCRM`
- `git reset --hard origin/autostopCRM`
- `docker compose up -d --build`
- локальные smoke-checks:
  - `scripts/check_live_connector.py`
  - `scripts/check_agent_runtime.py`

Compose stack:

- `autostopcrm` — основной контейнер, сейчас стартует `python main_mcp.py`
- `autostopcrm-agent` — отдельный worker, стартует `python main_agent.py`

Проброс портов:

- `127.0.0.1:8000 -> 41731/tcp`
- `127.0.0.1:8001 -> 41831/tcp`

Host data dir:

- `/opt/autostopcrm/data`

Container data dir:

- `/root/.minimal-kanban`

## 5. Как работает MCP-коннектор

MCP слой не повторяет бизнес-логику. Он является transport/control surface над тем же локальным API.

Текущая схема:

```text
MCP tool call
  -> src/minimal_kanban/mcp/server.py
  -> BoardApiClient
  -> local API
  -> CardService / domain services
```

Runtime `main_mcp.py` / `minimal_kanban.mcp.main` делает следующее:

1. Загружает `SettingsService`.
2. Пытается использовать уже доступный local API.
3. Если API нет, запускает embedded API внутри MCP runtime.
4. Создает FastMCP server через `create_mcp_server(...)`.
5. Публикует Streamable HTTP endpoint.

Canonical MCP path policy:

- canonical tool path: `/AutoStopCRM/<tool_name>`
- legacy long alias `/AutoStopCRM/link_.../<tool_name>` нормализуется в canonical short path

Важные connector meta-константы:

- `CONNECTOR_SCHEMA_VERSION = "2026-04-13"`
- `CONNECTOR_VERSION = "autostopcrm-mcp-2026-04-13"`

Базовый стартовый flow для внешнего агента:

1. `ping_connector()`
2. `bootstrap_context()`
3. `get_runtime_status()`

Основной envelope ответов MCP/API:

```json
{
  "ok": true,
  "data": {},
  "error": null,
  "meta": {
    "request_id": "...",
    "timestamp": "...",
    "schema_version": "...",
    "connector_version": "..."
  }
}
```

## 6. Где лежат ключевые файлы, конфиги, логи и точки входа

Корень репозитория:

- `README.md`
- `00_START_HERE_AUTOSTOP_CRM.md`
- `PROJECT_HANDOFF.md`
- `API_GUIDE.md`
- `MCP_GUIDE.md`
- `deploy.sh`
- `docker-compose.yml`
- `Dockerfile`
- `requirements.txt`
- `main.py`
- `main_mcp.py`
- `main_agent.py`

Ключевые runtime-конфиги:

- локально: `%APPDATA%\Minimal Kanban\settings.json`
- локально: `%APPDATA%\Minimal Kanban\users.json`
- локально: `%APPDATA%\Minimal Kanban\state.json`
- локально: `%APPDATA%\Minimal Kanban\mcp-oauth-state.json`
- production: `/opt/autostopcrm/.env`
- production data: `/opt/autostopcrm/data`

Логи:

- локально: `%APPDATA%\Minimal Kanban\logs\`
- production: `docker compose logs -f autostopcrm`
- production data logs path по volume-модели: `/opt/autostopcrm/data/logs`

Прочие runtime-папки данных:

- `%APPDATA%\Minimal Kanban\attachments`
- `%APPDATA%\Minimal Kanban\repair-orders`
- `%APPDATA%\Minimal Kanban\printing`
- `%APPDATA%\Minimal Kanban\agent`

## 7. Реально обнаруженные конфиги и живые значения

### 7.1 Локальный `%APPDATA%\\Minimal Kanban\\settings.json`

Выявлено:

- `integration_enabled = true`
- `use_local_api = true`
- `auto_connect_on_startup = true`
- `test_mode = true`
- `local_api_auth_mode = none`
- `mcp_auth_mode = none`
- `provider = openai`
- `model = gpt-5.4-mini`
- `base_url = https://api.openai.com/v1`
- `openai_api_key = ""`
- `tunnel_url = https://dare-villa-audit-biodiversity.trycloudflare.com`
- `effective_mcp_url = https://dare-villa-audit-biodiversity.trycloudflare.com/mcp`

Вывод:

- локальный settings-файл сейчас указывает на старый Cloudflare tunnel
- локально токены пустые
- локально OpenAI ключ в settings не сохранен

### 7.2 Production `/opt/autostopcrm/.env`

Фактическое содержимое:

```dotenv
AUTOSTOP_PUBLIC_BASE_URL=https://crm.autostopcrm.ru
AUTOSTOP_PUBLIC_MCP_URL=https://crm.autostopcrm.ru/mcp
AUTOSTOP_MCP_ALLOWED_HOSTS=46.8.254.243,46.8.254.243:*,crm.autostopcrm.ru,crm.autostopcrm.ru:*
AUTOSTOP_MCP_ALLOWED_ORIGINS=http://46.8.254.243,http://46.8.254.243:*,http://crm.autostopcrm.ru,http://crm.autostopcrm.ru:*,https://crm.autostopcrm.ru,https://crm.autostopcrm.ru:*
AUTOSTOP_DATA_DIR=./data
OPENAI_API_KEY=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
OPENAI_MODEL=gpt-5.4-mini
```

Вывод:

- production AI worker получает живой `OPENAI_API_KEY` прямо из `.env`
- секрет хранится в plain text
- compose передает его только в `autostopcrm-agent`

### 7.3 Production `/opt/autostopcrm/data/settings.json`

Выявлено:

- `public_https_base_url = https://crm.autostopcrm.ru`
- `effective_mcp_url = https://crm.autostopcrm.ru/mcp`
- `mcp_auth_mode = none`
- `auth.access_token = ""`
- `auth.local_api_bearer_token = ""`
- `auth.mcp_bearer_token = ""`
- `auth.openai_api_key = ""`
- `allowed_hosts` содержат старый IP `185.42.164.2`

Вывод:

- production persisted settings частично устарели по allowed hosts/origins
- compose env поверх этого уже подставляет актуальный `46.8.254.243`, поэтому runtime жив
- persisted settings и compose env сейчас расходятся

### 7.4 Production `/opt/autostopcrm/data/users.json`

Выявлено:

- usernames: `ADMIN`, `MARIA`, `SERGEY`
- session tokens хранятся прямо в `users.json`
- токенов много, они накапливаются

Примеры живых session tokens, реально найденных во время аудита:

- `Pjid0fOA6gHZB22rps-7_V4FwMdbcui6I_r3V-jbpC4`
- `u1kwDrnYEh9TekpunjiMv80ajMDFR8ZNiCnzZ9WzpXQ`
- `0u_HrgN7JM_L1lF9aVmp9sKt_OV9DMss9Jcotv-nhUc`
- `74tiiMxqPMu0uB61eUPQyjIoMal-owGOMFh0Ze7gbgs`

Вывод:

- operator sessions персистятся в plain text
- cleanup сессий агрессивно не делается
- это operational debt и security risk

## 8. Текущее состояние проекта: что готово, что сломано, что рискованно

### Что готово

- production runtime жив, локальный и server HEAD совпадают:
  - `d9ff24a68dc5fbd04da5f1940cbb78fe33358e76`
- сайт отвечает `200`
- MCP endpoint отвечает, HTTP статус на `GET /mcp` сейчас `406`, что для streamable MCP endpoint допустимо и означает, что endpoint жив
- compose stack healthy:
  - `autostopcrm` healthy
  - `autostopcrm-agent` up
- отдельный server AI worker запущен
- MCP canonical path и alias normalization уже реализованы
- server AI orchestration и deterministic scenarios уже внедрены
- production CRM/MCP домены живые

### Что выглядит сломанным или неполным

- полноценный OAuth для MCP фактически не используется:
  - `%APPDATA%\Minimal Kanban\mcp-oauth-state.json` пустой
  - auth режимы в settings стоят в `none`
- часть docs/guide-файлов в текущем shell-чтении выглядит с mojibake, значит по крайней мере часть документации и/или консольной выдачи еще страдает от проблем кодировки
- локальный settings все еще содержит старый tunnel URL:
  - `https://dare-villa-audit-biodiversity.trycloudflare.com`

### Что рискованно

- production все еще живет на default admin credentials:
  - code default username: `admin`
  - code default password: `admin`
  - legacy upgrade password path: `admin123`
- production OpenAI key лежит открытым текстом в `/opt/autostopcrm/.env`
- production operator session tokens лежат открытым текстом в `/opt/autostopcrm/data/users.json`
- API/MCP bearer auth в актуальных runtime settings выключены:
  - `auth_mode = none`
  - `local_api_bearer_token = ""`
  - `mcp_bearer_token = ""`
- persisted settings и compose env расходятся по разрешенным host/origin:
  - settings содержит `185.42.164.2`
  - compose env содержит `46.8.254.243`
- в рабочем дереве есть unrelated untracked хвосты:
  - `AMNEZIA_VPN_MONITORING.md`
  - `scripts/amnezia-*`

## 9. Технический долг

1. Сменить default admin credentials и зафиксировать новый auth baseline.
2. Вынести `OPENAI_API_KEY` и session tokens из plain-text operational surface или хотя бы сократить blast radius.
3. Почистить накопленные operator sessions в `users.json`.
4. Свести persisted settings и compose env к одному актуальному набору allowed hosts/origins.
5. Обновить или пересохранить docs, у которых всплывает mojibake при чтении/экспорте.
6. Убрать stale local tunnel URL из `%APPDATA%\Minimal Kanban\settings.json`.
7. Разобрать unrelated `AMNEZIA*` артефакты вне основной CRM-задачи.

## 10. Следующие шаги

Краткий practical backlog:

1. Credential rotation:
   - сменить `MINIMAL_KANBAN_DEFAULT_ADMIN_USERNAME`
   - сменить `MINIMAL_KANBAN_DEFAULT_ADMIN_PASSWORD`
   - выполнить deploy
   - перепроверить operator login и server smoke
2. Secret hygiene:
   - перенести `OPENAI_API_KEY` в более контролируемый server secret source
   - удалить устаревшие session tokens
3. Config cleanup:
   - синхронизировать `/opt/autostopcrm/.env` и `/opt/autostopcrm/data/settings.json`
4. Docs cleanup:
   - исправить encoding-sensitive `.md`/`.txt` документы
5. Local dev cleanup:
   - убрать старый Cloudflare tunnel URL из локальных settings

## 11. Карта доступов и секретов с реальными значениями

### 11.1 GitHub

| Что | Реальное значение | Где хранится | Для чего | Как получить доступ | Владелец/контроль |
|---|---|---|---|---|---|
| Git remote | `https://github.com/UgaChavis/GITHUB.git` | `.git/config` | исходный репозиторий | обычный `git fetch/push`, если есть права на remote | GitHub account/repo `UgaChavis` |

### 11.2 Production server access

| Что | Реальное значение | Где хранится | Для чего | Как получить доступ | Владелец/контроль |
|---|---|---|---|---|---|
| Server IP | `46.8.254.243` | docs, deploy notes, current runtime | production host | SSH | root on server |
| SSH user | `root` | operational practice | deploy / diagnostics | SSH key auth | root |
| SSH private key path | `C:\Users\9860606\.ssh\autostopcrm_server_ed25519` | локальная рабочая станция | доступ к production | `ssh -i C:\Users\9860606\.ssh\autostopcrm_server_ed25519 root@46.8.254.243` | локальный пользователь `9860606` |
| Server repo path | `/opt/autostopcrm` | server filesystem | git/deploy/runtime | SSH | root |

### 11.3 Public URLs

| Что | Реальное значение | Где хранится | Для чего |
|---|---|---|---|
| Public CRM | `https://crm.autostopcrm.ru` | `/opt/autostopcrm/.env`, docs | рабочий UI |
| Public MCP | `https://crm.autostopcrm.ru/mcp` | `/opt/autostopcrm/.env`, settings | MCP connector |

### 11.4 Operator/Admin access

| Что | Реальное значение | Где хранится | Для чего | Как получить доступ | Владелец/контроль |
|---|---|---|---|---|---|
| Default admin username | `admin` | `src/minimal_kanban/config.py` default env fallback | первичный admin login | operator login | system default |
| Stored normalized admin username | `ADMIN` | `%APPDATA%\Minimal Kanban\users.json`, `/opt/autostopcrm/data/users.json` | фактический stored user id | login normalizes name | app auth layer |
| Default admin password | `admin` | `src/minimal_kanban/config.py` default env fallback | первичный admin login | operator login | system default |
| Legacy password path | `admin123` | `src/minimal_kanban/operator_auth.py` | one-time legacy password-hash upgrade path | only if old hash still matches | code legacy path |

### 11.5 OpenAI / AI runtime

| Что | Реальное значение | Где хранится | Для чего | Как получить доступ | Владелец/контроль |
|---|---|---|---|---|---|
| OpenAI model | `gpt-5.4-mini` | `/opt/autostopcrm/.env`, compose env, settings | server AI model | server env or settings | deploy/runtime owner |
| OpenAI base URL | `https://api.openai.com/v1` | settings/config | API endpoint | settings/config | runtime config |
| OPENAI_API_KEY | `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` | `/opt/autostopcrm/.env` | server AI access to OpenAI | SSH -> `cat /opt/autostopcrm/.env` | server root / project operator |

### 11.6 MCP / API auth

| Что | Реальное значение | Где хранится | Для чего | Комментарий |
|---|---|---|---|---|
| `local_api_auth_mode` | `none` | local/server settings.json | auth mode for local API | bearer disabled |
| `mcp_auth_mode` | `none` | local/server settings.json | auth mode for MCP | bearer disabled |
| `local_api_bearer_token` | `""` | local/server settings.json | optional API bearer | empty |
| `mcp_bearer_token` | `""` | local/server settings.json | optional MCP bearer | empty |
| `access_token` | `""` | local/server settings.json | shared auth token slot | empty |

### 11.7 Local connector/runtime artifacts

| Что | Реальное значение | Где хранится | Для чего |
|---|---|---|---|
| Local tunnel URL | `https://dare-villa-audit-biodiversity.trycloudflare.com` | `%APPDATA%\Minimal Kanban\settings.json` | старый public MCP route для локальной машины |
| Local MCP URL | `http://127.0.0.1:41831/mcp` | `%APPDATA%\Minimal Kanban\settings.json` | local MCP |
| Local API URL | `http://127.0.0.1:41731` | `%APPDATA%\Minimal Kanban\settings.json` | local API |

### 11.8 Persisted live operator session tokens

Полный набор лежит в:

- local: `%APPDATA%\Minimal Kanban\users.json`
- production: `/opt/autostopcrm/data/users.json`

Примеры реально существующих production session tokens:

- `Pjid0fOA6gHZB22rps-7_V4FwMdbcui6I_r3V-jbpC4`
- `u1kwDrnYEh9TekpunjiMv80ajMDFR8ZNiCnzZ9WzpXQ`
- `0u_HrgN7JM_L1lF9aVmp9sKt_OV9DMss9Jcotv-nhUc`
- `74tiiMxqPMu0uB61eUPQyjIoMal-owGOMFh0Ze7gbgs`

Назначение:

- операторские сессии логина

Комментарий:

- это реальные живые bearer-like session secrets
- они персистятся прямо в JSON

## 12. Короткая карта репозитория

```text
autostopcrm-deploy-src/
  deploy.sh
  docker-compose.yml
  Dockerfile
  main.py
  main_mcp.py
  main_agent.py
  scripts/
    run_dev.ps1
    run_mcp_server.ps1
    check_live_connector.py
    check_agent_runtime.py
    run_isolated_tests.py
  src/minimal_kanban/
    api/
    agent/
    mcp/
    printing/
    services/
    storage/
    ui/
  tests/
  docs/
```

## 13. Быстрый operational summary

- Это production CRM с двумя живыми контейнерами: app/MCP и отдельный AI worker.
- Основная бизнес-логика живет в `CardService`, а MCP просто проксирует вызовы в тот же backend.
- Production и local repo сейчас на одном commit `d9ff24a68dc5fbd04da5f1940cbb78fe33358e76`.
- Самые реальные риски не в кодовой архитектуре, а в операционном слое:
  - default admin credentials
  - plain-text OpenAI key
  - plain-text session tokens
  - stale settings values
  - encoding debt в документации
