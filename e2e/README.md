# Tests E2E del sistema completo

Levantan **los tres módulos reales en Docker** (Postgres, API, worker, web con nginx, privacy-shield con spaCy y el
asistente) y los prueban de extremo a extremo, igual que los usaría una persona. Se ejecutan en GitHub (job `e2e`).

Solo se sustituyen las dos piezas pesadas o externas:

| Pieza real | En los E2E |
|---|---|
| Whisper (audio → texto) | **Transcriptor falso**: el «audio» es un `.txt` y cada línea es una frase (`?` al inicio = baja confianza) |
| Ollama y proveedores en la nube | **`stub-llm`**: servidor con la API de Ollama, determinista, que **registra todo lo que recibe** |

`stub-llm` distingue a sus tres clientes por el prompt del sistema: resumen del transcriber (`RESUMEN-STUB …`),
clasificador de preguntas del asistente (veredicto JSON) y privacy-shield (`ECO-STUB: …`, repite el mensaje).
Gracias a su registro (`/_captured`) los tests **demuestran lo que saldría hacia el LLM**: solo tokens, nunca datos
personales.

## Qué se valida

| Fichero | Contenido |
|---|---|
| `tests/test_pipeline.py` | Subida de audio → cola → worker → transcripción (orden, quién habla, baja confianza) → resumen → exportación Markdown → búsqueda → reanálisis → borrado; endpoint incremental de segmentos |
| `tests/test_privacy.py` | privacy-shield real con NER: anonimizar/revertir, el chat solo envía tokens, sesión con tokens estables, streaming idéntico al normal, emails y teléfonos dictados, tarjetas y secretos bloquean, IBAN/DNI enmascarados, proveedores y errores |
| `tests/test_assistant.py` | Una pregunta en la transcripción se detecta, se responde vía privacy-shield y la respuesta llega restaurada; ignora al usuario y lo que no va con él; preguntas manuales; bloqueo con código de error sin que salga nada; responder bajo demanda; dejar de seguir |
| `tests/test_security.py` | Todo lo protegido rechaza tokens ausentes o erróneos; cada servicio valida su propio token; cabeceras de seguridad también a través del proxy del asistente; solo se publican los puertos previstos y solo en `127.0.0.1`; **`assistant` y `worker` no tienen salida a Internet** |
| `tests/test_zz_resilience.py` | Con el asistente caído, la web y el transcriber siguen funcionando y vuelven a servirlo al arrancar |
| `modules/transcriber/web/e2e/stack.spec.ts` | Navegador real (Chrome con micrófono falso): grabar → resumen; pestaña «Asistente» con pregunta manual; pregunta que llega a la transcripción con su respuesta en streaming; estado del sistema |

## Ejecutarlos

En CI no hay que hacer nada. En local (pesado: construye cinco imágenes, entre ellas spaCy y el transcriber):

```bash
cp .env.example .env     # y añade POSTGRES_PASSWORD, MT_API_TOKEN y ANON_API_TOKEN
pip install -r e2e/requirements.txt
make test-e2e-stack
```

Los tokens de CI son valores de prueba fijos (`e2e-…`), sin ningún secreto real. Para el navegador:
`cd modules/transcriber/web && MT_E2E_STUB=1 npx playwright test e2e/stack.spec.ts` con el stack ya levantado.

## Ampliarlos

- Un escenario nuevo del sistema: un `test_*.py` con los fixtures `web`, `shield`, `stub` y `meetings`
  (borra lo que creas). `helpers.py` trae `upload`, `wait_done`, `events`, `captured`…
- Otro comportamiento del LLM: `stub_llm/app.py` (todo lo que devuelve es determinista).
- Los E2E con Whisper y Ollama reales (`make test-e2e`) siguen existiendo aparte y no se ejecutan en CI.
