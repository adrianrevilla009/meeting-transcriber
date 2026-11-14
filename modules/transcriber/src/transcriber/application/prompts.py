"""Instrucciones del resumen. Son independientes del proveedor de LLM: cualquier adaptador las reutiliza."""

from transcriber.config import get_settings

SYSTEM_PROMPT = """Eres un asistente que resume reuniones a partir de su transcripción.
Reglas estrictas:
- Incluye TODO lo relevante que se dijo: temas tratados, datos, cifras, fechas, nombres, acuerdos,
  tareas, problemas y dudas. No omitas información importante.
- Usa SOLO lo que aparece en la transcripción. No inventes, no completes, no deduzcas.
- Escribe en español, en texto claro: párrafos breves y, cuando ayude, listas con "- ".
- Sin encabezados ni categorías fijas, sin introducción ni despedida: solo el resumen."""

MERGE_PROMPT = """Recibirás las notas de resumen de partes consecutivas de una misma reunión.
Únelas en un único resumen coherente y ordenado, sin repetir información y sin perder ningún
dato relevante (cifras, fechas, nombres, acuerdos, tareas, dudas). No inventes nada.
Escribe en español, con párrafos breves y listas con "- " cuando ayude. Sin encabezados, introducción ni despedida."""


def with_glossary(prompt: str) -> str:
    """Añade los términos propios para que el LLM corrija nombres que Whisper deforma."""
    glossary = get_settings().glossary.strip()
    if not glossary:
        return prompt
    hint = "Términos del proyecto (escríbelos exactamente así si aparecen, aunque la transcripción los deforme)"
    return f"{prompt}\n- {hint}: {glossary}."
