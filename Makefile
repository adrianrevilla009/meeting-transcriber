# Meeting Transcriber — atajos. Ejecutar desde Git Bash / WSL.
#   make start                          -> todo de una vez (env, modelos, build, arranque, health)
#   make record TITLE="Kickoff" PROJECT=pagos
#   make help                           -> lista de comandos
#
# OLLAMA=host   (por defecto) usa el Ollama instalado en tu máquina
# OLLAMA=docker usa el contenedor ollama del docker-compose

SHELL := sh
-include .env
export MSYS_NO_PATHCONV := 1

OLLAMA       ?= host
API          ?= http://127.0.0.1:8000
WEB          ?= http://127.0.0.1:3000
PYTHON       ?= $(shell command -v py >/dev/null 2>&1 && echo py || echo python)
WHISPER      := $(or $(MT_WHISPER_MODEL),small)
LLM          := $(or $(MT_OLLAMA_MODEL),qwen2.5:7b)
AUTH         := -H "Authorization: Bearer $(MT_API_TOKEN)"

# Se usa en linea (no con un make recursivo): en Windows el sub-make puede no encontrar sh.
HEALTH_CHECK = for i in $$(seq 1 30); do curl -sf $(API)/health >/dev/null && { echo "OK: API viva en $(API)"; exit 0; }; sleep 2; done; \
	 echo "La API no responde; mira: make logs"; exit 1

ifeq ($(OLLAMA),host)
COMPOSE  := docker compose -f docker-compose.yml -f docker-compose.host-ollama.yml
SERVICES := db api worker web
else
COMPOSE  := docker compose
SERVICES := db api worker web ollama
endif

.PHONY: help start open web-dev test-api test-web test-e2e test-all coverage env check models whisper-model llm-model up down restart logs ps health \
        ollama-check agent-install record meetings transcript search test clean shield-up shield-down shield-logs assistant-up assistant-down assistant-logs test-e2e-stack

help: ## Muestra esta ayuda
	@grep -E '^[a-zA-Z0-9_-]+:.*## ' Makefile | awk 'BEGIN{FS=":.*## "}{printf "  \033[36m%-15s\033[0m %s\n",$$1,$$2}'

start: env check models up ollama-check ## TODO en uno: .env, modelos (si faltan), build, arranque y health
	@echo ""; echo "Listo. Abre $(WEB) (token: MT_API_TOKEN de .env)  ->  make open"

open: ## Abre el frontal en el navegador
	@explorer "$(WEB)" || true

web-dev: ## Frontal en modo desarrollo con recarga en caliente (http://localhost:5173)
	cd modules/transcriber/web && npm install && npm run dev

env: ## Crea .env desde .env.example si no existe
	@if [ ! -f .env ]; then cp .env.example .env; echo ".env creado: edita POSTGRES_PASSWORD y MT_API_TOKEN y vuelve a lanzar make start"; exit 1; fi

check: ## Comprueba que docker (y ollama en modo host) estan disponibles
	@docker info >/dev/null 2>&1 || { echo "Docker no esta arrancado"; exit 1; }
	@if [ "$(OLLAMA)" = "host" ]; then \
	  command -v ollama >/dev/null || { echo "ollama no encontrado; instala Ollama o usa OLLAMA=docker"; exit 1; }; \
	  curl -sf http://localhost:11434/api/tags >/dev/null || { echo "Ollama no responde en localhost:11434; abre la app de Ollama"; exit 1; }; \
	fi
	@echo "OK: entorno (ollama=$(OLLAMA))"

models: whisper-model llm-model ## Descarga Whisper y el LLM solo si no estan ya

whisper-model: ## Descarga el modelo Whisper al volumen si falta
	@$(COMPOSE) build -q api
	@if $(COMPOSE) run --rm --no-deps -T api sh -c 'ls /data/models/models--*faster-whisper-$(WHISPER)/snapshots/*/model.bin >/dev/null 2>&1'; then \
	  echo "OK: Whisper '$(WHISPER)' ya instalado"; \
	else \
	  echo "Descargando Whisper '$(WHISPER)'..."; \
	  docker compose --profile setup run --rm models; \
	fi

llm-model: ## Descarga el LLM en Ollama (host o contenedor) si falta
ifeq ($(OLLAMA),host)
	@if ollama list | awk 'NR>1{print $$1}' | grep -qxE '$(LLM)(:latest)?'; then \
	  echo "OK: LLM '$(LLM)' ya instalado en Ollama local"; \
	else \
	  echo "Descargando '$(LLM)' en Ollama local..."; ollama pull $(LLM); \
	fi
else
	@docker compose --profile setup run --rm --entrypoint sh ollama-pull -c \
	  'ollama serve >/dev/null 2>&1 & sleep 5; \
	   if ollama list | awk "NR>1{print \$$1}" | grep -qxE "$(LLM)(:latest)?"; then echo "OK: LLM $(LLM) ya instalado"; \
	   else ollama pull $(LLM); fi'
endif

up: ## Construye y arranca los servicios y espera a /health
	@$(COMPOSE) up -d --build $(SERVICES)
	@$(HEALTH_CHECK)

down: ## Para los servicios (conserva datos y modelos)
	@docker compose -f docker-compose.yml -f docker-compose.host-ollama.yml down

restart: down up ## Reinicia

logs: ## Sigue los logs de api, worker y web
	@$(COMPOSE) logs -f api worker web

ps: ## Estado de los contenedores
	@$(COMPOSE) ps

health: ## Espera a que la API responda
	@$(HEALTH_CHECK)

ollama-check: ## Verifica que el worker alcanza Ollama y el modelo existe
	@$(COMPOSE) exec -T worker python -c "import httpx,os; u=os.environ['MT_OLLAMA_URL']; m=[x['name'] for x in httpx.get(u+'/api/tags',timeout=5).json()['models']]; print('OK: worker ->', u, '| modelos:', ', '.join(m))" \
	 || echo "AVISO: el worker no llega a Ollama. En modo host prueba a definir OLLAMA_HOST=0.0.0.0 en Windows y reinicia Ollama."

agent-install: ## Instala dependencias del agente de captura (Windows)
	$(PYTHON) -m pip install PyAudioWPatch numpy soundfile requests

record: ## Graba una reunion: make record TITLE="Kickoff" PROJECT=pagos (Ctrl+C para terminar)
	$(PYTHON) modules/transcriber/agent/capture_agent.py --api $(API) --token "$(MT_API_TOKEN)" --title "$(TITLE)" --project "$(PROJECT)"

meetings: ## Lista reuniones
	@curl -s $(AUTH) $(API)/meetings; echo

transcript: ## Resumen+transcripcion en Markdown: make transcript ID=1
	@curl -s $(AUTH) $(API)/meetings/$(ID)/transcript

search: ## Busca en transcripciones: make search Q="texto"
	@curl -s -G $(AUTH) --data-urlencode "q=$(Q)" $(API)/search; echo

# ---------- Tests ----------
# Entorno Python aislado en modules/transcriber/.venv (requiere uv: https://docs.astral.sh/uv/)
# Los comandos de Python se ejecutan desde modules/transcriber/ (ahí viven pyproject.toml y los tests).
VENV_PY = $(if $(wildcard modules/transcriber/.venv/Scripts/python.exe),.venv/Scripts/python,.venv/bin/python)

modules/transcriber/.venv:
	uv venv --python 3.12 modules/transcriber/.venv
	uv pip install --python modules/transcriber/.venv -e "modules/transcriber[dev]"

modules/transcriber/web/node_modules:
	cd modules/transcriber/web && npm ci

test: test-api test-web ## Tests rápidos: unit + integración (API) y unit + componentes (web)

test-api: modules/transcriber/.venv ## Python: unit + integración (SQLite, transcriptor y LLM falsos)
	cd modules/transcriber && $(VENV_PY) -m pytest

test-web: modules/transcriber/web/node_modules ## Web: unit + componentes con Vitest
	cd modules/transcriber/web && npm test

test-e2e: modules/transcriber/.venv modules/transcriber/web/node_modules up ## E2E reales: pipeline (Whisper+Ollama+Postgres) y navegador (Playwright)
	cd modules/transcriber && $(VENV_PY) -m pytest -m e2e -v
	cd modules/transcriber/web && npx playwright test

test-all: test test-e2e ## Toda la batería

coverage: modules/transcriber/.venv modules/transcriber/web/node_modules ## Informes de cobertura (API y web)
	cd modules/transcriber && $(VENV_PY) -m pytest --cov=transcriber --cov-report=term-missing
	cd modules/transcriber/web && npm run test:coverage

clean: ## BORRA contenedores y volumenes (BD, audio, modelos Whisper): make clean CONFIRM=yes
	@[ "$(CONFIRM)" = "yes" ] || { echo "Esto borra todos los datos. Repite con CONFIRM=yes"; exit 1; }
	docker compose -f docker-compose.yml -f docker-compose.host-ollama.yml --profile setup down -v

# ---------- Módulo 2: privacy-shield (ver modules/privacy-shield/README.md) ----------
shield-up: ## Construye y arranca el proxy de ofuscación (127.0.0.1:8100)
	@docker compose --profile shield up -d --build privacy-shield

shield-down: ## Para el proxy de ofuscación
	@docker compose --profile shield stop privacy-shield

shield-logs: ## Sigue los logs del proxy de ofuscación
	@docker compose --profile shield logs -f privacy-shield

# ---------- Módulo 3: realtime-assistant (ver modules/realtime-assistant/README.md) ----------
assistant-up: ## Arranca privacy-shield + el asistente en vivo (panel "Asistente" en la web)
	@docker compose --profile shield up -d --build privacy-shield assistant

assistant-down: ## Para el asistente en vivo
	@docker compose --profile shield stop assistant

assistant-logs: ## Sigue los logs del asistente
	@docker compose --profile shield logs -f assistant

# ---------- E2E del stack completo con transcriptor y LLM falsos (lo mismo que hace el CI; ver e2e/README.md) ----------
E2E_COMPOSE := docker compose -f docker-compose.yml -f e2e/docker-compose.e2e.yml --profile shield
test-e2e-stack: ## E2E de los 3 módulos en Docker con LLM falso (pesado: construye 5 imágenes)
	$(E2E_COMPOSE) up -d --build db api worker web privacy-shield assistant stub-llm
	cd e2e && E2E_COMPOSE="$(E2E_COMPOSE)" $(PYTHON) -m pytest
	$(E2E_COMPOSE) down -v
