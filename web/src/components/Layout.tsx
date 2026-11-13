import { NavLink, Outlet, useNavigate } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { AudioLines, Cpu, LayoutDashboard, ListChecks, LogOut, Mic, Search, Sparkles } from "lucide-react";
import { api } from "../api";
import { fmtTs } from "../format";
import { useElapsed, useRecorder } from "../recorder/RecorderContext";

export function Logo() {
  return (
    <div className="logo">
      <div className="logo-mark">
        <AudioLines size={18} />
      </div>
      <div>
        <div className="logo-name">Transcriber</div>
        <div className="logo-sub">local · privado</div>
      </div>
    </div>
  );
}

function LiveBadge() {
  const rec = useRecorder();
  const elapsed = useElapsed(rec.startedAt);
  const navigate = useNavigate();
  if (rec.phase !== "recording" && rec.phase !== "stopping") return null;
  return (
    <button className="live-badge" onClick={() => navigate("/record")}>
      <span className="live-dot" />
      <span>{rec.phase === "stopping" ? "Finalizando…" : "Grabando"}</span>
      <span className="mono">{fmtTs(elapsed)}</span>
    </button>
  );
}

function SystemCard() {
  const { data, isError } = useQuery({ queryKey: ["system"], queryFn: api.system, refetchInterval: 10_000 });
  const llmOk = data && (data.analyzer !== "ollama" || (data.ollama_reachable && data.ollama_model_installed));
  return (
    <div className="system-card">
      <div className="system-row">
        <span className={`dot ${isError ? "dot-err" : data ? "dot-ok" : ""}`} />
        <span>API</span>
        <span className="muted">{isError ? "sin conexión" : data ? "en línea" : "…"}</span>
      </div>
      {data && (
        <>
          <div className="system-row">
            <Cpu size={13} />
            <span>Whisper</span>
            <span className="muted mono">{data.whisper_model}</span>
          </div>
          <div className="system-row">
            <span className={`dot ${llmOk ? "dot-ok" : "dot-warn"}`} />
            <span>LLM</span>
            <span className="muted mono" title={llmOk ? "" : "Ollama no responde o falta el modelo"}>
              {data.analyzer === "ollama" ? data.ollama_model : data.analyzer}
            </span>
          </div>
          {data.queue > 0 && (
            <div className="system-row">
              <Sparkles size={13} />
              <span>Cola</span>
              <span className="muted">{data.queue} fragmentos</span>
            </div>
          )}
        </>
      )}
    </div>
  );
}

export function Layout({ onLogout }: { onLogout: () => void }) {
  const nav = [
    { to: "/", icon: LayoutDashboard, label: "Reuniones", end: true },
    { to: "/record", icon: Mic, label: "Grabar" },
    { to: "/requirements", icon: ListChecks, label: "Requisitos" },
    { to: "/search", icon: Search, label: "Buscar" },
  ];
  return (
    <div className="shell">
      <aside className="sidebar">
        <Logo />
        <LiveBadge />
        <nav className="nav">
          {nav.map(({ to, icon: Icon, label, end }) => (
            <NavLink key={to} to={to} end={end} className={({ isActive }) => `nav-item ${isActive ? "active" : ""}`}>
              <Icon size={18} />
              <span>{label}</span>
            </NavLink>
          ))}
        </nav>
        <div className="sidebar-foot">
          <SystemCard />
          <button className="nav-item" onClick={onLogout}>
            <LogOut size={18} />
            <span>Salir</span>
          </button>
        </div>
      </aside>
      <main className="main">
        <Outlet />
      </main>
    </div>
  );
}
