import { createContext, useCallback, useContext, useState, type ReactNode } from "react";
import { AlertTriangle, Check, Info, X } from "lucide-react";

type Tone = "ok" | "error" | "info";
interface Toast {
  id: number;
  text: string;
  tone: Tone;
}

const Ctx = createContext<(text: string, tone?: Tone) => void>(() => undefined);
let nextId = 1;

export function ToastProvider({ children }: { children: ReactNode }) {
  const [toasts, setToasts] = useState<Toast[]>([]);
  const remove = (id: number) => setToasts((t) => t.filter((x) => x.id !== id));
  const push = useCallback((text: string, tone: Tone = "ok") => {
    const id = nextId++;
    setToasts((t) => [...t, { id, text, tone }]);
    setTimeout(() => remove(id), 4500);
  }, []);
  const Icon = { ok: Check, error: AlertTriangle, info: Info };

  return (
    <Ctx.Provider value={push}>
      {children}
      <div className="toasts" role="status" aria-live="polite">
        {toasts.map((t) => {
          const I = Icon[t.tone];
          return (
            <div key={t.id} className={`toast toast-${t.tone}`}>
              <I size={16} />
              <span>{t.text}</span>
              <button className="icon-btn" onClick={() => remove(t.id)} aria-label="Cerrar">
                <X size={14} />
              </button>
            </div>
          );
        })}
      </div>
    </Ctx.Provider>
  );
}

export const useToast = () => useContext(Ctx);
