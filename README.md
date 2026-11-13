# Meeting Transcriber

Transcripción local y privada de reuniones. Nada sale de tu máquina/red: Whisper y el LLM (Ollama) corren en local.

## Arquitectura
```
[Windows] capture_agent.py ──HTTP──▶ api (FastAPI) ──▶ Postgres (datos + cola SKIP LOCKED)
                                                         ▲
                                   worker ── faster-whisper ──▶ segmentos (transcripción cruda, inmutable)
                                      └──── Ollama (LLM) ──▶ requisitos/decisiones/dudas con CITA VERIFICADA
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
de la transcripción, leer el análisis con citas, ver la evolución de los requisitos y buscar en todas las
reuniones. Al grabar, elige **Toda la pantalla** y marca **Compartir audio del sistema**.
Desarrollo del frontal con recarga en caliente: `make web-dev` (http://localhost:5173).

## Captura (Windows, alternativa por línea de comandos)
```powershell
pip install PyAudioWPatch numpy soundfile requests
python agent/capture_agent.py --token TU_TOKEN --title "Kickoff" --project pagos
# Ctrl+C para terminar → el worker transcribe, analiza y exporta
```
Graba tu micro (`mic`, aparece como "Yo") y el audio del sistema (`system`, "Otros") por separado.

## Uso
| Endpoint | Para qué |
|---|---|
| `GET /meetings/{id}/transcript` (`?format=json`) | Transcripción + análisis en `.md` |
| `GET /meetings/{id}/events` | Requisitos/decisiones/dudas detectados |
| `GET /requirements?project=X` / `/requirements/{id}/history` | Cómo evoluciona cada requisito entre reuniones |
| `GET /search?q=texto` | Búsqueda en todas las transcripciones |
| `POST /meetings/{id}/analyze` | Reanalizar (p. ej. tras cambiar de modelo) |
| `DELETE /meetings/{id}` | Borrar todo rastro de una reunión |

Todo requiere `Authorization: Bearer <MT_API_TOKEN>` salvo `/health`. Cada petición queda en `audit_log`.

## Medir la fiabilidad real
1. Graba 3-5 reuniones con audio retenido (`MT_AUDIO_RETENTION_DAYS=30`).
2. Corrige a mano un fragmento y compara: `python scripts/eval_wer.py referencia.txt hipotesis.txt` (requiere `pip install jiwer`).
3. Ajusta modelo, glosario y umbrales (`MT_MIN_AVG_LOGPROB`, `MT_QUOTE_MIN_SCORE`) con datos.

## Tests
| Orden | Qué prueba | Necesita |
|---|---|---|
| `make test` | Todo lo rápido (las dos filas siguientes) | `uv`, Node |
| `make test-api` | Python unit + integración: verificador de citas, análisis, worker, todos los endpoints, auditoría (SQLite, transcriptor y LLM falsos) | `uv` |
| `make test-web` | Vitest: formato, codificación WAV y troceo, subidas con reintento, cliente API y cada pantalla (Testing Library) | Node |
| `make test-e2e` | Pipeline real (voz → Whisper → Ollama → Postgres, con WER) y navegador real (Playwright graba con un micro falso que reproduce la voz) | stack arrancado, Chrome |
| `make coverage` | Informes de cobertura | |

El audio de prueba (`tests/fixtures/speech_es.wav`) es voz sintética en español con su guion exacto
(`speech_es.txt`); se regenera con `powershell -File tests/fixtures/make_speech.ps1`.
GitHub Actions ejecuta `make test` en cada push; los e2e se lanzan en local porque necesitan los modelos.

## Desarrollo
```bash
make test        # crea .venv con uv e instala dependencias la primera vez
make web-dev     # frontal con recarga en caliente
```
Variables de entorno `MT_*` en `app/config.py`.

## Pendiente / siguientes pasos
- Migraciones con Alembic (ahora `create_all` al arrancar).
- Diarización con pyannote (hoy: solo mic vs. sistema).
- Búsqueda semántica con pgvector (hoy: búsqueda por texto).
- Cifrado en reposo: usa cifrado de disco/volumen en el entorno corporativo.
