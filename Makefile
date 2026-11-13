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
PYTHON       ?= $(shell command -v py >/dev/null 2>&1 && echo py || echo python)
WHISPER      := $(or $(MT_WHISPER_MODEL),small)
LLM          := $(or $(MT_OLLAMA_MODEL),qwen2.5:7b)
AUTH         := -H "Authorization: Bearer $(MT_API_TOKEN)"

ifeq ($(OLLAMA),host)
COMPOSE  := docker compose -f docker-compose.yml -f docker-compose.host-ollama.yml
SERVICES := db api worker
else
COMPOSE  := docker compose
SERVICES := db api worker ollama
endif

.PHONY: help start env check models whisper-model llm-model up down restart logs ps health \
        ollama-check agent-install record meetings transcript events requirements search test clean

help: ## Muestra esta ayuda
	@grep -E '^[a-zA-Z_-]+:.*## ' Makefile | awk 'BEGIN{FS=":.*## "}{printf "  \033[36m%-15s\033[0m %s\n",$$1,$$2}'

start: env check models up ollama-check ## TODO en uno: .env, modelos (si faltan), build, arranque y health
	@echo ""; echo "Listo. API en $(API)  ->  ahora: make record TITLE=\"Mi reunion\" PROJECT=demo"

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
	@if $(COMPOSE) run --rm --no-deps -T api sh -c 'ls -d /data/models/models--*faster-whisper-$(WHISPER) >/dev/null 2>&1'; then \
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
	@"$(MAKE)" --no-print-directory health

down: ## Para los servicios (conserva datos y modelos)
	@docker compose -f docker-compose.yml -f docker-compose.host-ollama.yml down

restart: down up ## Reinicia

logs: ## Sigue los logs de api y worker
	@$(COMPOSE) logs -f api worker

ps: ## Estado de los contenedores
	@$(COMPOSE) ps

health: ## Espera a que la API responda
	@for i in $$(seq 1 30); do curl -sf $(API)/health >/dev/null && { echo "OK: API viva en $(API)"; exit 0; }; sleep 2; done; \
	 echo "La API no responde; mira: make logs"; exit 1

ollama-check: ## Verifica que el worker alcanza Ollama y el modelo existe
	@$(COMPOSE) exec -T worker python -c "import httpx,os; u=os.environ['MT_OLLAMA_URL']; m=[x['name'] for x in httpx.get(u+'/api/tags',timeout=5).json()['models']]; print('OK: worker ->', u, '| modelos:', ', '.join(m))" \
	 || echo "AVISO: el worker no llega a Ollama. En modo host prueba a definir OLLAMA_HOST=0.0.0.0 en Windows y reinicia Ollama."

agent-install: ## Instala dependencias del agente de captura (Windows)
	$(PYTHON) -m pip install PyAudioWPatch numpy soundfile requests

record: ## Graba una reunion: make record TITLE="Kickoff" PROJECT=pagos (Ctrl+C para terminar)
	$(PYTHON) agent/capture_agent.py --api $(API) --token "$(MT_API_TOKEN)" --title "$(TITLE)" --project "$(PROJECT)"

meetings: ## Lista reuniones
	@curl -s $(AUTH) $(API)/meetings; echo

transcript: ## Transcripcion+analisis en Markdown: make transcript ID=1
	@curl -s $(AUTH) $(API)/meetings/$(ID)/transcript

events: ## Requisitos/decisiones/dudas: make events ID=1
	@curl -s $(AUTH) $(API)/meetings/$(ID)/events; echo

requirements: ## Requisitos (opcional PROJECT=x)
	@curl -s $(AUTH) "$(API)/requirements?project=$(PROJECT)"; echo

search: ## Busca en transcripciones: make search Q="texto"
	@curl -s -G $(AUTH) --data-urlencode "q=$(Q)" $(API)/search; echo

test: ## Ejecuta los tests en local
	$(PYTHON) -m pytest

clean: ## BORRA contenedores y volumenes (BD, audio, modelos Whisper): make clean CONFIRM=yes
	@[ "$(CONFIRM)" = "yes" ] || { echo "Esto borra todos los datos. Repite con CONFIRM=yes"; exit 1; }
	docker compose -f docker-compose.yml -f docker-compose.host-ollama.yml --profile setup down -v
