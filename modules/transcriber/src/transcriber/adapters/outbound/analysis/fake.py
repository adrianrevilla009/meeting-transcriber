from typing import ClassVar


class FakeAnalyzer:
    """Para tests: devuelve `script` como resumen de cada ventana, sin llamar a ningún LLM."""

    script: ClassVar[str] = ""

    def summarize(self, transcript_window: str) -> str:
        return self.script

    def merge(self, partial_summaries: list[str]) -> str:
        return "\n\n".join(partial_summaries)
