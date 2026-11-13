import { useEffect, useState, type ReactNode } from "react";
import { Loader2 } from "lucide-react";
import { PHASE_LABEL, type Phase } from "../format";

export function StatusPill({ phase }: { phase: Phase }) {
  return (
    <span className={`pill pill-${phase}`}>
      <span className="pill-dot" />
      {PHASE_LABEL[phase]}
    </span>
  );
}

export function ProjectTag({ name }: { name: string }) {
  if (!name) return null;
  return <span className="tag">#{name}</span>;
}

export function Spinner({ size = 16 }: { size?: number }) {
  return <Loader2 size={size} className="spin" />;
}

export function Empty({ icon, title, children }: { icon: ReactNode; title: string; children?: ReactNode }) {
  return (
    <div className="empty">
      <div className="empty-icon">{icon}</div>
      <h3>{title}</h3>
      {children && <div className="muted">{children}</div>}
    </div>
  );
}

/** Botón destructivo de dos pasos: el primer clic pide confirmación durante unos segundos. */
export function ConfirmButton({
  onConfirm,
  children,
  confirmText = "¿Seguro? Pulsa de nuevo",
  disabled,
}: {
  onConfirm: () => void;
  children: ReactNode;
  confirmText?: string;
  disabled?: boolean;
}) {
  const [armed, setArmed] = useState(false);
  useEffect(() => {
    if (!armed) return;
    const t = setTimeout(() => setArmed(false), 4000);
    return () => clearTimeout(t);
  }, [armed]);
  return (
    <button
      className={`btn ${armed ? "btn-danger" : "btn-ghost"}`}
      disabled={disabled}
      onClick={() => (armed ? (setArmed(false), onConfirm()) : setArmed(true))}
    >
      {armed ? confirmText : children}
    </button>
  );
}

export function ProgressBar({ value, indeterminate }: { value: number; indeterminate?: boolean }) {
  return (
    <div className={`progress ${indeterminate ? "progress-indeterminate" : ""}`}>
      <div className="progress-fill" style={{ width: `${Math.max(0, Math.min(100, value * 100))}%` }} />
    </div>
  );
}

export function highlight(text: string, needle: string) {
  if (!needle) return text;
  const escaped = needle.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  const parts = text.split(new RegExp(`(${escaped})`, "gi"));
  return parts.map((p, i) =>
    p.toLowerCase() === needle.toLowerCase() ? <mark key={i}>{p}</mark> : <span key={i}>{p}</span>,
  );
}
