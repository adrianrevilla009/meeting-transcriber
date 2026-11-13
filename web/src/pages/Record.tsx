import { useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { AlertTriangle, CloudUpload, Headphones, Info, Mic, MonitorSpeaker, Square, X } from "lucide-react";
import { api } from "../api";
import { fmtTs } from "../format";
import { CHUNK_SECONDS } from "../recorder/engine";
import { useElapsed, useRecorder } from "../recorder/RecorderContext";
import { Spinner } from "../components/ui";
import { Waveform } from "../components/Waveform";
import { useToast } from "../components/Toasts";

function SourceToggle({
  on,
  onChange,
  icon,
  title,
  text,
}: {
  on: boolean;
  onChange: (v: boolean) => void;
  icon: React.ReactNode;
  title: string;
  text: string;
}) {
  return (
    <button type="button" className={`source-toggle ${on ? "on" : ""}`} onClick={() => onChange(!on)} aria-pressed={on}>
      <div className="source-icon">{icon}</div>
      <div className="source-text">
        <strong>{title}</strong>
        <span className="muted small">{text}</span>
      </div>
      <span className="switch">
        <span className="switch-knob" />
      </span>
    </button>
  );
}

function Setup() {
  const rec = useRecorder();
  const [title, setTitle] = useState("");
  const [project, setProject] = useState("");
  const [mic, setMic] = useState(true);
  const [system, setSystem] = useState(true);
  const { data: meetings } = useQuery({ queryKey: ["meetings"], queryFn: api.meetings });
  const projects = useMemo(() => [...new Set((meetings ?? []).map((m) => m.project).filter(Boolean))], [meetings]);
  const starting = rec.phase === "starting";

  return (
    <div className="record-setup">
      <div className="glass record-form rise">
        <h1 className="display-sm">Nueva grabación</h1>
        <p className="muted">Ponle nombre, elige qué grabar y pulsa el botón.</p>

        <div className="form-grid">
          <label className="field">
            <span>Título</span>
            <input value={title} onChange={(e) => setTitle(e.target.value)} placeholder="Kickoff con cliente" autoFocus />
          </label>
          <label className="field">
            <span>Proyecto</span>
            <input value={project} onChange={(e) => setProject(e.target.value)} placeholder="pagos" list="projects" />
            <datalist id="projects">
              {projects.map((p) => (
                <option key={p} value={p} />
              ))}
            </datalist>
          </label>
        </div>

        <div className="sources">
          <SourceToggle on={mic} onChange={setMic} icon={<Mic size={20} />} title="Tu micrófono" text='Aparece como "Yo"' />
          <SourceToggle
            on={system}
            onChange={setSystem}
            icon={<MonitorSpeaker size={20} />}
            title="Audio del ordenador"
            text='Teams, Meet, Zoom… Aparece como "Otros"'
          />
        </div>

        {system && (
          <div className="hint">
            <Info size={16} />
            <div>
              El navegador te pedirá compartir pantalla: elige <strong>Toda la pantalla</strong> y activa{" "}
              <strong>Compartir audio del sistema</strong>. No se graba la imagen, solo el sonido.
            </div>
          </div>
        )}
        {mic && system && (
          <div className="hint">
            <Headphones size={16} />
            <div>Usa auriculares para que tu micro no capte a los demás por duplicado.</div>
          </div>
        )}

        {rec.error && (
          <div className="alert alert-error">
            <AlertTriangle size={16} /> {rec.error}
            <button className="icon-btn" onClick={rec.dismissError} aria-label="Cerrar">
              <X size={14} />
            </button>
          </div>
        )}
      </div>

      <div className="record-orb-wrap rise" style={{ animationDelay: "80ms" }}>
        <button
          className="record-orb"
          aria-label={starting ? "Preparando…" : "Empezar a grabar"}
          disabled={starting || (!mic && !system)}
          onClick={() => rec.start({ title, project, mic, system })}
        >
          <span className="orb-glow" />
          <span className="orb-core">{starting ? <Spinner size={34} /> : <Mic size={40} />}</span>
        </button>
        <div className="orb-label">{starting ? "Preparando…" : "Empezar a grabar"}</div>
        <div className="muted small">Puedes navegar por la app mientras grabas</div>
      </div>
    </div>
  );
}

function Live() {
  const rec = useRecorder();
  const elapsed = useElapsed(rec.startedAt);
  const navigate = useNavigate();
  const qc = useQueryClient();
  const toast = useToast();
  const stopping = rec.phase === "stopping";
  const { stats } = rec;

  const stop = async () => {
    const id = await rec.stop();
    void qc.invalidateQueries({ queryKey: ["meetings"] });
    if (id) {
      toast("Grabación terminada. Transcribiendo…", "ok");
      navigate(`/meetings/${id}`);
    }
  };

  return (
    <div className="live glass rise">
      <div className="live-head">
        <span className="pill pill-recording">
          <span className="pill-dot" /> {stopping ? "Finalizando" : "En directo"}
        </span>
        <span className="muted">{rec.meeting?.title || `Reunión #${rec.meeting?.id}`}</span>
      </div>

      <div className="live-timer mono">{fmtTs(elapsed)}</div>

      <div className="lanes">
        {(["mic", "system"] as const).map((s) =>
          rec.analysers[s] ? (
            <div key={s} className="lane">
              <div className="lane-label">
                {s === "mic" ? <Mic size={15} /> : <MonitorSpeaker size={15} />}
                {s === "mic" ? "Yo" : "Otros"}
              </div>
              <Waveform analyser={rec.analysers[s]} palette={s === "mic" ? "violet" : "cyan"} />
            </div>
          ) : null,
        )}
      </div>

      <div className="live-stats">
        <div>
          <CloudUpload size={15} />
          <strong>{stats.sent}</strong> <span className="muted">fragmentos enviados</span>
        </div>
        <div>
          <span className="muted">Siguiente envío cada {CHUNK_SECONDS} s</span>
        </div>
        {stats.queued > 0 && (
          <div>
            <Spinner size={14} /> <span className="muted">{stats.queued} en cola{stats.retrying ? " (reintentando)" : ""}</span>
          </div>
        )}
        {stats.failed > 0 && (
          <div className="text-err">
            <AlertTriangle size={14} /> {stats.failed} fallidos
          </div>
        )}
      </div>

      {rec.warnings.map((w, i) => (
        <div key={i} className="alert alert-warn">
          <AlertTriangle size={16} /> {w}
        </div>
      ))}

      <button className="stop-btn" onClick={stop} disabled={stopping}>
        {stopping ? <Spinner size={18} /> : <Square size={18} fill="currentColor" />}
        {stopping ? "Enviando los últimos fragmentos…" : "Terminar reunión"}
      </button>
    </div>
  );
}

export function Record() {
  const rec = useRecorder();
  return <div className="page">{rec.phase === "recording" || rec.phase === "stopping" ? <Live /> : <Setup />}</div>;
}
