"""Descarga el modelo Whisper a la carpeta local (ejecutar con red; luego se puede aislar)."""
from app.config import get_settings


def main() -> None:
    from faster_whisper import WhisperModel

    s = get_settings()
    s.whisper_models_dir.mkdir(parents=True, exist_ok=True)
    WhisperModel(s.whisper_model, device="cpu", compute_type="int8", download_root=str(s.whisper_models_dir))
    print(f"Modelo {s.whisper_model} descargado en {s.whisper_models_dir}")


if __name__ == "__main__":
    main()
