# realtime-assistant (módulo 3)

Asistente en vivo para reuniones: **sigue la transcripción, detecta preguntas y sugiere respuestas** mientras la
reunión está en marcha. Se usa desde el panel «Asistente» de la web del módulo 1.

```
módulo 1 (transcriber)            módulo 3 (este)                         privacy-shield ──▶ LLM externo
  segmentos nuevos  ──sondeo──▶  reglas ─▶ LLM local (confirma) ─▶ pregunta
  GET /meetings/{id}/segments                                        │ (siempre vía el filtro)
                                  respuesta (streaming) ◀────────────┘
                                  eventos SSE ──▶ panel de la web
```

- **Nunca habla con un LLM externo directamente.** Las respuestas salen siempre por privacy-shield (módulo 2), que
  pseudonimiza lo personal antes de enviarlo y lo revierte al volver. Cada cliente HTTP tiene una allowlist con el
  único host de su servicio, y en Docker el contenedor no tiene salida a Internet.
- **Escucha a los demás, no a ti**: solo mira lo que llega por `system` (y `mix`), no lo que dices por el micro.
- **Detección en dos pasos**: reglas rápidas en español (signos `¿?`, interrogativos, segunda persona, tus nombres)
  y un LLM local pequeño que confirma que es una pregunta real dirigida a ti o al grupo (no retórica ni muletilla).
  Si el LLM local no responde, se usan solo las reglas.
- **Sin ruido**: deduplica preguntas repetidas, respeta un enfriamiento entre respuestas automáticas
  (`RTA_ANSWER_COOLDOWN_SECONDS`, 15 s) y responde de una en una. Las preguntas manuales siempre se responden.
- **Contexto**: la respuesta recibe las últimas líneas de la conversación («Yo» / «Otros»). La misma sesión de
  privacy-shield dura toda la reunión, así que el mismo nombre lleva el mismo token en todas las consultas.

## Uso

Desde la raíz del repositorio:

```bash
# .env: ANON_API_TOKEN, la clave de un proveedor (o RTA_SHIELD_PROVIDER=ollama para probar sin claves) y
#       RTA_USER_NAMES="Tu nombre, apodo"
make assistant-up        # privacy-shield + asistente
make open                # la web: en Grabar activa «Asistente en vivo»; en la reunión, pestaña «Asistente»
```

«Asistente en vivo» en la página de grabación sube el audio en trozos de **12 s** (en lugar de 45): la respuesta llega
antes a costa de una transcripción algo menos precisa. También puedes activarlo en cualquier reunión desde su pestaña
y escribir preguntas a mano.

## API

Mismo token Bearer que la web (`RTA_API_TOKEN` = `MT_API_TOKEN`). Se expone en la web bajo `/assistant/`.

| Endpoint | Función |
|---|---|
| `POST /v1/meetings/{id}/follow` | Empieza a seguir la reunión (idempotente). 404 si no existe, 503 si no se alcanza el transcriber |
| `DELETE /v1/meetings/{id}/follow` | Deja de seguirla |
| `GET /v1/meetings/{id}/status` | `{following, questions, answers}` |
| `POST /v1/meetings/{id}/ask` | `{text}` → pregunta manual; la respuesta llega por eventos |
| `POST /v1/meetings/{id}/questions/{qid}/answer` | Responde una pregunta detectada (o reintenta una que falló) |
| `GET /v1/meetings/{id}/events?after=N` | SSE: histórico con `id > N` y luego en vivo. `once=true` devuelve solo el histórico |

Eventos (`id` creciente por reunión): `question`, `answer_start`, `answer_chunk`, `answer_done`, `error`
(`leak_detected`, `policy_blocked`, `shield_unavailable`, `provider_error`…) y `status` (`following`/`stopped`).
Los errores llevan un código, nunca texto de la reunión.

## Configuración (`RTA_*`, ver `.env.example`)

`RTA_USER_NAMES` (tus nombres para detectar preguntas dirigidas a ti), `RTA_PROFILE` (contexto tuyo para las
respuestas), `RTA_CLASSIFIER` (`ollama` | `rules`), `RTA_OLLAMA_MODEL` (por defecto `qwen2.5:3b`, rápido),
`RTA_AUTO_ANSWER`, `RTA_ANSWER_COOLDOWN_SECONDS`, `RTA_POLL_SECONDS`, `RTA_CONTEXT_CHARS`,
`RTA_MIN_QUESTION_SCORE`, `RTA_SHIELD_PROVIDER`/`RTA_SHIELD_MODEL`.

## Límites conocidos

- **Latencia**: el módulo 1 transcribe por trozos de audio. Con 12 s hay unos 15–25 s entre que alguien pregunta y
  aparece la respuesta (trozo + Whisper + LLM). No es subtitulado en directo.
- Las reglas dependen de que Whisper ponga `¿?` y tildes; sin ellos detecta menos.
- Deja de seguir la reunión solo tras `RTA_IDLE_TIMEOUT_SECONDS` (30 min) sin segmentos nuevos, o al desactivarlo.
- El historial de eventos vive en memoria: se pierde al reiniciar el servicio.

## Desarrollo

Estructura hexagonal (ver `docs/ARCHITECTURE.md`): `domain` ← `application` ← `adapters` ← `bootstrap`, comprobada con
`lint-imports`. El caso de uso se prueba sin red con transcripción, clasificador y generador falsos; los adaptadores
HTTP con `httpx.MockTransport`.
