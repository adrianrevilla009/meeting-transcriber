const KEY = "mt_assistant_live";

/** Preferencia "Asistente en vivo" de la pantalla de grabación (desactivada por defecto). */
export const livePref = {
  get(): boolean {
    try {
      return localStorage.getItem(KEY) === "1";
    } catch {
      return false;
    }
  },
  set(on: boolean) {
    try {
      localStorage.setItem(KEY, on ? "1" : "0");
    } catch {
      /* almacenamiento no disponible: la preferencia no se recuerda */
    }
  },
};
