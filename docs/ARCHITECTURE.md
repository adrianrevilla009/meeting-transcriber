# Arquitectura y convenciones

Monorepo de módulos independientes que se pueden desarrollar, probar y desplegar por separado, y que se
comunican entre sí **por HTTP** (nunca importándose código unos a otros).

| # | Módulo | Carpeta | Estado |
|---|---|---|---|
| 1 | Transcripción y resumen offline de reuniones (Whisper + Ollama) | `modules/transcriber` | Hecho |
| 2 | Proxy de ofuscación: pseudonimiza lo que sale al exterior y revierte la respuesta | `modules/privacy-shield` | Hecho (fases 0-5) |
| 3 | Asistente en vivo: sigue la reunión, detecta preguntas y sugiere respuestas con un LLM externo (siempre vía el módulo 2) | `modules/realtime-assistant` | Hecho |

## Plantilla de módulo (arquitectura hexagonal)

Todos los módulos Python siguen la misma estructura, de modo que quien conoce uno conoce los demás:

```
modules/<modulo>/
  pyproject.toml            dependencias, ruff, mypy, import-linter (reglas de capas)
  Dockerfile  .dockerignore
  src/<paquete>/
    domain/                 entidades y reglas de negocio. Sin frameworks ni proveedores
    application/            casos de uso y PUERTOS (interfaces). Solo depende de domain
    adapters/
      inbound/              lo que invoca al núcleo: API HTTP, worker, CLI
      outbound/<tema>/      implementaciones de los puertos: BD, almacenamiento, LLM, transcriptores...
    bootstrap/              raíz de composición: ÚNICO sitio que conoce los adaptadores concretos
    config.py               ajustes (variables de entorno con prefijo del módulo)
  tests/
    unit/ integration/ e2e/
```

### Regla de dependencias

```
bootstrap  →  adapters  →  application  →  domain
```

Cada capa solo puede importar las de su derecha. Se comprueba en CI con `lint-imports` (contratos en el
`pyproject.toml` de cada módulo):

1. **Capas**: nada de `domain`/`application` importa `adapters` o `bootstrap`.
2. **Sin frameworks en el núcleo**: `domain` y `application` no importan `fastapi`, `httpx`, `faster_whisper`...
3. **Adaptadores independientes**: un adaptador nunca importa otro; solo se conocen en `bootstrap`.

Compromiso asumido: SQLAlchemy se permite en `domain`/`application` (las entidades son modelos ORM y los casos
de uso reciben una `Session`). Si un módulo necesitara cambiar de motor de persistencia, se introduciría un
puerto de repositorio solo entonces.

### Cómo se cambian las cosas

| Quiero... | Toco |
|---|---|
| Otro proveedor de LLM / transcriptor / almacén | Un archivo nuevo en `adapters/outbound/<tema>/` + una línea en `bootstrap` |
| Otra forma de invocar el núcleo (CLI, cola, gRPC) | Un adaptador nuevo en `adapters/inbound/` |
| Una regla de negocio o caso de uso nuevo | `application/` (y `domain/` si hay entidades nuevas) |
| Probar sin red ni modelos | Adaptadores `Fake*` inyectados desde los tests |

### Inyección de dependencias

`application.runtime.Runtime` agrupa las dependencias ya cableadas (sesión de BD, almacén, transcriptor,
analizador). `bootstrap` lo construye; la API, el worker y los tests lo reciben. Los casos de uso son funciones
que reciben `session` y `rt`, sin estado global.

## Convenciones comunes

- **Seguridad por defecto**: servicios publicados solo en `127.0.0.1`, token Bearer, fallo cerrado si falta
  configuración, y nada sensible en logs.
- **Una variable de entorno por ajuste** con prefijo del módulo (`MT_*` en el transcriber, `ANON_*` en
  privacy-shield). Se documentan en el README del módulo y en `.env.example`.
- **CI en GitHub** (no se ejecuta en local): lint (`ruff`), tipos (`mypy`), arquitectura (`lint-imports`),
  seguridad (`bandit`), tests y construcción de imagen por módulo.
- **E2E del sistema completo** (`e2e/`): los tres módulos en Docker con transcriptor y LLM falsos; comprueba
  el cableado real, que no sale ningún dato personal y el aislamiento de red. Ver `e2e/README.md`.
- **Código compartido**: no hay librería común todavía. Si dos módulos necesitan lo mismo, se duplica hasta que
  aparezca la tercera necesidad; entonces se extrae a `libs/<nombre>` con su propio paquete.
- **Redes Docker**: solo `privacy-shield` tendrá salida a Internet; el resto, en redes internas, y hablarán con
  él por HTTP cuando necesiten un LLM en la nube.

## Cómo se conectan los módulos (Docker)

```
navegador ──▶ web (nginx) ──/api/──────▶ api (módulo 1) ──▶ db, worker, ollama
                   │
                   └──/assistant/──▶ assistant (módulo 3) ──▶ api (lee /meetings/{id}/segments)
                                          │                └──▶ ollama (clasifica preguntas, local)
                                          └──▶ privacy-shield (módulo 2) ──▶ LLM en la nube
```

Redes: `backend` y `assist` son internas (sin Internet); solo `privacy-shield` está también en `edge`. El asistente
vive en `backend` + `assist`, así que **no puede salir a Internet** aunque se cambiara una URL: lo único externo
pasa por el filtro de privacidad. Los módulos se hablan solo por HTTP y comparten el token de la web.
