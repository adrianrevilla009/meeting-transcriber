# privacy-shield (módulo 2)

Proxy de ofuscación: **ningún dato personal sale de tu máquina hacia un LLM externo**. Antes de enviar un texto a un
proveedor (OpenAI, Anthropic…) se pseudonimiza localmente; cuando llega la respuesta se revierte localmente.

```
mensajes ─▶ detectar ─▶ pseudonimizar (vault de sesión) ─▶ LEAK GUARD ─▶ proveedor
                                                              │ fuga → bloquear (422)
respuesta ◀─ des-pseudonimizar (con streaming) ◀──────────────┘
```

- **Fail closed**: detector caído, política que bloquea o fuga detectada ⇒ no se llama al proveedor.
- **Defensa en profundidad**: un segundo detector independiente (leak guard) revisa lo que va a salir.
- **Reversible dentro de una sesión**: mismo valor → mismo token (`[PERSONA_1]`), y la respuesta se revierte.
- **Nada sensible en logs**: la auditoría guarda recuentos, hashes y latencias, nunca texto.
- **Medible**: generador de transcripciones sintéticas y evaluador de fugas y sobre-redacción (`eval/`).

Alcance: proyecto educativo. La ofuscación no es perfecta (ver *Límites*), no es cumplimiento legal ni anonimización
irreversible certificada.

## Uso rápido

```bash
cd modules/privacy-shield
pip install -e ".[ner,dev]"
python -m spacy download es_core_news_md     # modelo NER español
cp .env.example .env                          # ANON_API_TOKEN, claves de los proveedores…
cp config/glossary.example.yaml config/glossary.yaml
uvicorn --factory privacy_shield.bootstrap.api:create --port 8100
```

Con Docker (desde la raíz del repo): `docker compose --profile shield up -d --build privacy-shield` o `make shield-up`.
Escucha solo en `127.0.0.1:8100` y es el único contenedor con salida a Internet.

```bash
curl -s localhost:8100/v1/chat -H "Authorization: Bearer $ANON_API_TOKEN" -H 'content-type: application/json' -d '{
  "provider": "anthropic",
  "messages": [{"role": "user", "content": "Redacta un correo a Marta García (marta@empresa.es) sobre el pago"}]
}'
```

CLI: `privacy-shield anonymize "Llama a Marta García al 612 345 678"`.

## API

Todo requiere `Authorization: Bearer <ANON_API_TOKEN>` salvo `/health`. Sin token configurado, la API rechaza todo.

| Endpoint | Función |
|---|---|
| `POST /v1/anonymize` | `{session_id?, text}` → `{session_id, text, entities:[{type,token,strategy}]}` (sin valores reales) |
| `POST /v1/deanonymize` | `{session_id, text}` → `{text}` |
| `POST /v1/chat` | Caso principal. `{session_id?, provider?, model?, messages[], stream?, temperature?, max_tokens?}`. Con `stream: true`, SSE (`data: {"content", "finish_reason"}` y `data: [DONE]`) |
| `GET /v1/providers` | Proveedores registrados, si están configurados y si salen de la máquina |
| `DELETE /v1/sessions/{id}` | Borra el vault de la sesión |
| `GET /v1/sessions/{id}/mapping` | Desactivado (`ANON_DEBUG_MAPPING=false`); solo depuración local |
| `GET /health` | Estado |

Errores (sin texto del usuario): `422 leak_detected` / `policy_blocked`, `503 detector_unavailable` /
`provider_not_configured`, `403 provider_not_allowed`, `404 session_not_found` / `provider_not_found`, `502 provider_error`.
Sin `session_id` se crea uno y se devuelve; reutilízalo durante toda una conversación o reunión.

## Política y glosario

`config/policy.yaml` define la estrategia por tipo de entidad:

| Estrategia | Efecto |
|---|---|
| `pseudonymize` | Token reversible `[PERSONA_1]` (por defecto) |
| `mask` | Token no reversible `[IBAN]` (por defecto para DNI/NIE e IBAN) |
| `block` | Rechaza la petición (por defecto para tarjetas y secretos) |
| `allow` | No se toca |

También el umbral mínimo de confianza por tipo y `local_only` (solo proveedores que no salen de la máquina).
`config/glossary.yaml` (copia de `glossary.example.yaml`) añade términos propios: clientes, proyectos, apodos.

## Detección

Se ejecutan en este orden y los solapes se resuelven (gana el span más largo, luego mayor score, luego el más
específico: regex > glosario > nombres > NER):

1. **Regex**: email, teléfono ES, DNI/NIE (con letra de control), IBAN (mod 97), tarjeta (Luhn), IP, URL, API keys y
   contraseñas dictadas.
2. **Glosario**: sin distinguir mayúsculas ni tildes.
3. **Lista de nombres**: nombres de pila y apellidos comunes; los ambiguos (Rosa, Salvador…) solo con contexto.
4. **NER spaCy** (`es_core_news_md`): personas, organizaciones y ubicaciones. Se carga una vez al arrancar.

Antes de detectar, el **normalizador de ASR** convierte lo que produce Whisper (“seis cuatro cinco, treinta y dos…”,
“marta punto garcia arroba gmail punto com”) en una vista con dígitos y símbolos, y reproyecta los spans al texto
original (si hay duda se amplía el span: más vale tapar de más).

## Proveedores

`OpenAIAdapter`, `AnthropicAdapter` y `OllamaAdapter` (local: no sale de la máquina y, con `ANON_SKIP_LOCAL=true`, no
hace falta pseudonimizar). Cada cliente HTTP solo puede hablar con el host de su proveedor (**allowlist de salida**).
Añadir un proveedor = un archivo nuevo en `adapters/outbound/llm/`, pasar el test de contrato
(`tests/contract/test_llm_port.py`) y registrarlo en `bootstrap`.

## Evaluación (leak rate)

```bash
python -m eval.generator --per-scenario 10     # corpus sintético en eval/corpus (semilla 7)
python -m eval.run_eval                        # informe en eval/reports/<fecha>.md y .json
python -m eval.run_eval --no-ner               # sin spaCy
python -m eval.run_eval --write-baseline       # fija eval/baseline.json
```

El corpus mezcla escenarios normales (trabajo, médico, familia, finanzas, soporte, RR. HH…), casos adversariales
(ASR en minúsculas y con letras cambiadas, MAYÚSCULAS, números dictados, nombres ambiguos, mezcla ES/EN, una persona
repetida 20 veces) y **frases trampa** sin datos sensibles para medir la sobre-redacción. El informe da el **leak rate**
(valores reales que siguen visibles), recall y falsos positivos por tipo, sobre-redacción, ida y vuelta y latencia
(objetivo: < 150 ms p95 en ~500 caracteres), y lista los fallos concretos para ajustar reglas y glosario. Un test falla
si el leak rate sube respecto a `eval/baseline.json`.

## Límites conocidos

- El NER falla con nombres en minúsculas o sin contexto; la lista de nombres y el glosario compensan pero no todo.
- Si el mismo dato aparece con formatos distintos, la respuesta se revierte al formato visto primero.
- No hay UI; un frontal “antes/después” queda para cuando el núcleo esté estable.
- El vault en memoria se pierde al reiniciar (`ANON_VAULT=sqlite` lo persiste: usa disco cifrado).

## Desarrollo

Estructura hexagonal (ver `docs/ARCHITECTURE.md` en la raíz): `domain` ← `application` ← `adapters` ← `bootstrap`,
comprobada con `lint-imports`. El pipeline completo se prueba sin red ni claves con `FakeLLMAdapter`, que además
captura lo que “saldría”. Las decisiones no obvias están en [DECISIONS.md](DECISIONS.md).
