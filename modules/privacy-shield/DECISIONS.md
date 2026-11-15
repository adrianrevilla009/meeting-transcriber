# Decisiones

Registro de decisiones tomadas donde la guía de arquitectura era ambigua o se desvía de ella.

1. **spaCy directo en lugar de `presidio-analyzer`.** Solo se necesita el NER (PER/ORG/LOC); la sustitución ya la
   hace el pseudonimizador con el vault. Presidio añade un motor de reconocedores, configuración de NLP y bastante
   peso sin aportar nada aquí. El detector se llama `spacy_ner.py` (no `presidio_spacy.py`). Si hiciera falta
   reconocedores de Presidio más adelante, es un adaptador nuevo detrás de `DetectorPort`.
2. **`pyyaml` añadido a las dependencias.** `policy.yaml` y `glossary.yaml` son parte del diseño y necesitan un
   parser YAML.
3. **`httpx.MockTransport` en lugar de `respx`.** Los tests de contrato y de fugas inyectan un cliente httpx con
   transporte simulado (incluida la allowlist). Es más simple y captura igualmente el cuerpo exacto de la petición.
4. **Lista de nombres propia (`NameListDetector`).** El NER de spaCy falla con nombres sueltos y en minúsculas
   (justo lo que produce Whisper). Una lista de nombres y apellidos comunes los complementa; los nombres que también
   son palabras (Rosa, Salvador…) solo puntúan por encima del umbral con una pista de contexto.
5. **Barrido de valores conocidos.** Tras pseudonimizar, se sustituyen las apariciones de valores ya vistos en la
   sesión que el detector no marcó (p. ej. el mismo nombre en una frase donde el NER falla). Reduce fugas y evita
   bloqueos innecesarios del leak guard.
6. **Reversión al primer formato visto.** El vault normaliza (minúsculas, sin tildes, solo dígitos en teléfonos…):
   “Marta García”, “marta garcia” y “Marta” (alias) comparten token, y al revertir se devuelve la primera forma vista.
   La propiedad de ida y vuelta exacta se garantiza para valores con formato consistente.
7. **Mismo `fold` que conserva la longitud.** Plegar tildes y mayúsculas carácter a carácter permite reutilizar los
   offsets del texto original (glosario, barrido, leak guard).
8. **Detección de tarjetas por formato.** Solo 13-19 dígitos seguidos o grupos de 4 (y 4-6-5): evita que los dígitos
   de un IBAN pasen el algoritmo de Luhn por casualidad y bloqueen la petición.
9. **Nada de `assert` en el código de producción** (bandit) y errores de proveedor con mensaje fijo: nunca incluyen
   el cuerpo de la respuesta, que podría contener eco de datos.
10. **Baseline de evaluación.** `eval/baseline.json` no existe hasta que se ejecuta `--write-baseline` con datos
    reales; el test de regresión se salta mientras no esté. No se inventa un número.
11. **Fases opcionales.** Incluidos: `OllamaAdapter` con ruteo local (`ANON_SKIP_LOCAL`), `SqliteVault` y política
    `local_only`. Fuera del alcance por ahora: front de demo y modo LLM local del generador de corpus.
12. **Perfil `shield` en Docker Compose.** El servicio no arranca con `docker compose up` normal para no obligar a
    configurar tokens del módulo 2 al usar solo el transcriber.
