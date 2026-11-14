# Meeting Transcriber

Transcripción local y privada de reuniones. Nada sale de tu máquina/red: Whisper y el LLM (Ollama) corren en local.

## Estructura del repositorio
```
backend/   API, worker, agente de captura, scripts y tests de Python (Dockerfile y pyproject propios)
web/       frontal React
docker-compose.yml, Makefile, .env   orquestación común
```
Cada proyecto del portfolio vive en su propia carpeta de primer nivel con sus tests y su Dockerfile.

## Arquitectura
```
[Windows] capture_agent.py ──HTTP──▶ api (FastAPI) ──▶ Postgres (datos + cola SKIP LOCKED)
                                                         ▲
                                   worker ── faster-whisper ──▶ segmentos (transcripción cruda, inmutable)
                                      └──── Ollama (LLM) ──▶ resumen de la reunión (la transcripción no se toca)
                                                         └──▶ exports/meeting_N.md
```
Principios de fiabilidad:
- La transcripción cruda es la fuente de verdad; el LLM **solo extrae**, nunca reescribe.
- Cada elemento extraído lleva una cita literal que se comprueba contra los segmentos; si no aparece, se descarta.
- Segmentos de baja confianza se marcan `[?]` en el `.md`.
- El audio se borra al transcribir (`MT_AUDIO_RETENTION_DAYS=0`) o tras N días.

## Arranque (Docker, en WSL o servidor)
```bash
cp .env.example .env            # edita contraseñas, token y glosario
docker compose --profile setup run --rm models        # descarga Whisper (una vez, con red)
docker compose --profile setup run --rm ollama-pull   # descarga el LLM (una vez, con red)
docker compose up -d --build    # api + worker + db + ollama (red backend sin Internet)
curl http://127.0.0.1:8000/health
```
En CPU de 16 GB: `MT_WHISPER_MODEL=small` (o `medium`) y `MT_OLLAMA_MODEL=qwen2.5:7b`. El análisis tardará minutos por reunión.

## Frontal web (recomendado)
```bash
make start      # descarga modelos si faltan, construye y arranca todo
make open       # abre http://127.0.0.1:3000 (token: MT_API_TOKEN de .env)
```
Desde el navegador puedes grabar (micrófono + audio del sistema, sin instalar nada), seguir el progreso
de la transcripción, leer el resumen y buscar en todas las
reuniones. Al grabar, elige **Toda la pantalla** y marca **Compartir audio del sistema**.
Desarrollo del frontal con recarga en caliente: `make web-dev` (http://localhost:5173).

## Captura (Windows, alternativa por línea de comandos)
```powershell
pip install PyAudioWPatch numpy soundfile requests
python backend/agent/capture_agent.py --token TU_TOKEN --title "Kickoff" --project pagos
# Ctrl+C para terminar → el worker transcribe, analiza y exporta
```
Graba tu micro (`mic`, aparece como "Yo") y el audio del sistema (`system`, "Otros") por separado.

## Uso
| Endpoint | Para qué |
|---|---|
| `GET /meetings/{id}/transcript` (`?format=json`) | Resumen + transcripción en `.md` |
| `GET /search?q=texto` | Búsqueda en todas las transcripciones |
| `POST /meetings/{id}/analyze` | Reanalizar (p. ej. tras cambiar de modelo) |
| `DELETE /meetings/{id}` | Borrar todo rastro de una reunión |

Todo requiere `Authorization: Bearer <MT_API_TOKEN>` salvo `/health`. Cada petición queda en `audit_log`.

## Mejorar la calidad (Whisper y resumen)
Todo se controla con variables `MT_*` en `.env`; tras cambiarlas, `make up` (o `docker compose up -d`) y,
si cambias el modelo, descárgalo (`make models`). De más a menos impacto:

| Qué falla | Palanca | Variable | Coste |
|---|---|---|---|
| Nombres propios, siglas o jerga mal escritos | Glosario: va a Whisper (`initial_prompt`) y al LLM, que corrige los términos deformados | `MT_GLOSSARY="Zoltrabek, ProyectoX"` | Ninguno |
| Transcripción con muchos errores | Modelo Whisper mayor: `small` → `medium` (`large-v3` solo con GPU) | `MT_WHISPER_MODEL` | ~3× más lento en CPU |
| Errores puntuales de palabras | Búsqueda en haz más amplia (por defecto 5; 1 = voraz) | `MT_WHISPER_BEAM_SIZE` | Algo más lento |
| Resumen que omite o inventa | LLM mayor: `qwen2.5:7b` → `qwen2.5:14b` (`make llm-model` tras cambiarlo) | `MT_OLLAMA_MODEL` | Más RAM y tiempo |
| Resumen que se corta o pierde el inicio | Contexto del LLM (el de Ollama por defecto recorta) | `MT_OLLAMA_NUM_CTX` (8192) | Más RAM |
| Resumen con poco detalle en reuniones largas | Trozos de transcripción más grandes (menos fusiones) | `MT_ANALYSIS_WINDOW_CHARS` (6000) | Un 7b pierde detalle si son muy grandes |

Aplicado ya por defecto: `beam_size=5`, VAD, glosario también en el LLM y contexto de 8192 tokens.
Lo que más pesa y no es un parámetro: la calidad del audio. Usa auriculares (el micro no debe recoger el audio del
sistema) y comprueba que el nivel no sea bajo. En CPU de 16 GB, `medium` + `qwen2.5:7b` es el techo razonable.
Para medir el efecto de cada cambio: `scripts/eval_wer.py` (ver abajo).

## Medir la fiabilidad real
1. Graba 3-5 reuniones con audio retenido (`MT_AUDIO_RETENTION_DAYS=30`).
2. Corrige a mano un fragmento y compara: `python backend/scripts/eval_wer.py referencia.txt hipotesis.txt` (requiere `pip install jiwer`).
3. Ajusta modelo, glosario y umbrales (`MT_MIN_AVG_LOGPROB`) con datos.

## Tests
| Orden | Qué prueba | Necesita |
|---|---|---|
| `make test` | Todo lo rápido (las dos filas siguientes) | `uv`, Node |
| `make test-api` | Python unit + integración: verificador de citas, análisis, worker, todos los endpoints, auditoría (SQLite, transcriptor y LLM falsos) | `uv` |
| `make test-web` | Vitest: formato, codificación WAV y troceo, subidas con reintento, cliente API y cada pantalla (Testing Library) | Node |
| `make test-e2e` | Pipeline real (voz → Whisper → Ollama → Postgres, con WER) y navegador real (Playwright graba con un micro falso que reproduce la voz) | stack arrancado, Chrome |
| `make coverage` | Informes de cobertura | |

El audio de prueba (`backend/tests/fixtures/speech_es.wav`) es voz sintética en español con su guion exacto
(`speech_es.txt`); se regenera con `powershell -File backend/tests/fixtures/make_speech.ps1`.
GitHub Actions ejecuta `make test` en cada push; los e2e se lanzan en local porque necesitan los modelos.

## Desarrollo
```bash
make test        # crea backend/.venv con uv e instala dependencias la primera vez
make web-dev     # frontal con recarga en caliente
```
Variables de entorno `MT_*` en `backend/app/config.py`.

## Pendiente / siguientes pasos
- Migraciones con Alembic (ahora `create_all` al arrancar).
- Diarización con pyannote (hoy: solo mic vs. sistema).
- Búsqueda semántica con pgvector (hoy: búsqueda por texto).
- Cifrado en reposo: usa cifrado de disco/volumen en el entorno corporativo.
