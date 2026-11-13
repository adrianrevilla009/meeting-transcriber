import { useEffect, useRef, useState } from "react";
import { Link, useNavigate, useParams, useSearchParams } from "react-router-dom";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import {
  AlertTriangle,
  ArrowLeft,
  Brain,
  CalendarClock,
  Check,
  Copy,
  Download,
  FileText,
  Mic,
  RefreshCw,
  Search,
  Square,
  Trash2,
} from "lucide-react";
import { api } from "../api";
import { downloadText, fmtDate, fmtDuration, fmtTs, meetingTitle, phaseOf, slug, SPEAKER, type Phase } from "../format";
import type { Meeting as MeetingT, Progress, Segment } from "../types";
import { ConfirmButton, Empty, highlight, ProgressBar, ProjectTag, Spinner, StatusPill } from "../components/ui";
import { useToast } from "../components/Toasts";
import { useRecorder } from "../recorder/RecorderContext";

function Stepper({ phase, progress }: { phase: Phase; progress?: Progress }) {
  const order: Phase[] = ["recording", "transcribing", "analyzing", "ready"];
  const at = phase === "failed" ? 3 : order.indexOf(phase);
  const ratio = progress && progress.chunks_total ? progress.chunks_done / progress.chunks_total : 0;
  const steps = [
    { label: "Grabación", detail: progress ? `${progress.chunks_total} fragmentos` : "" },
    {
      label: "Transcripción",
      detail: progress ? `${progress.chunks_done}/${progress.chunks_total} · ${progress.segments} frases` : "",
    },
    { label: "Resumen IA", detail: phase === "failed" ? "falló" : "" },
    { label: "Lista", detail: "" },
  ];
  return (
    <div className="stepper glass">
      {steps.map((s, i) => {
        const state =
          i < at || (i === 3 && phase === "ready")
            ? "done"
            : i === at
              ? phase === "failed"
                ? "error"
                : "active"
              : "todo";
        return (
          <div key={s.label} className={`step step-${state}`}>
            <div className="step-dot">
              {state === "done" ? <Check size={14} /> : state === "active" ? <Spinner size={14} /> : i + 1}
            </div>
            <div className="step-text">
              <strong>{s.label}</strong>
              {s.detail && <span className="muted small">{s.detail}</span>}
              {i === 1 && state === "active" && <ProgressBar value={ratio} />}
              {i === 2 && state === "active" && <ProgressBar value={1} indeterminate />}
            </div>
          </div>
        );
      })}
    </div>
  );
}

function Transcript({ segments, phase, focus }: { segments: Segment[]; phase: Phase; focus: number | null }) {
  const [q, setQ] = useState("");
  const [onlyDoubtful, setOnlyDoubtful] = useState(false);
  const container = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (focus == null) return;
    const el = container.current?.querySelector(`[data-seg="${focus}"]`);
    if (el) {
      el.scrollIntoView({ behavior: "smooth", block: "center" });
      el.classList.remove("flash");
      void (el as HTMLElement).offsetWidth;
      el.classList.add("flash");
    }
  }, [focus, segments.length]);

  const needle = q.trim().toLowerCase();
  const visible = segments.filter(
    (s) => (!onlyDoubtful || s.low_confidence) && (!needle || s.text.toLowerCase().includes(needle)),
  );
  const doubtful = segments.filter((s) => s.low_confidence).length;

  if (!segments.length) {
    return phase === "recording" || phase === "transcribing" ? (
      <Empty icon={<Spinner size={24} />} title="Transcribiendo…">
        Las frases aparecerán aquí en cuanto Whisper procese el primer fragmento.
      </Empty>
    ) : (
      <Empty icon={<FileText size={24} />} title="Transcripción vacía">
        No se detectó voz en el audio.
      </Empty>
    );
  }

  return (
    <div>
      <div className="toolbar">
        <div className="input-icon input-sm">
          <Search size={15} />
          <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Buscar en esta reunión" />
        </div>
        {doubtful > 0 && (
          <button className={`chip ${onlyDoubtful ? "active" : ""}`} onClick={() => setOnlyDoubtful((v) => !v)}>
            <AlertTriangle size={13} /> {doubtful} dudosas
          </button>
        )}
        <span className="muted small">{segments.length} frases</span>
      </div>
      <div className="chat" ref={container}>
        {visible.map((s, i) => {
          const prev = visible[i - 1];
          const first = !prev || prev.source !== s.source;
          return (
            <div key={s.id} data-seg={s.id} className={`bubble-row from-${s.source} ${first ? "first" : ""}`}>
              {first && <div className="bubble-who">{SPEAKER[s.source] ?? s.source}</div>}
              <div
                className={`bubble ${s.low_confidence ? "doubtful" : ""}`}
                title={s.low_confidence ? "Baja confianza: revisa esta frase" : undefined}
              >
                <span className="bubble-ts mono">{fmtTs(s.start)}</span>
                <span>{needle ? highlight(s.text, needle) : s.text}</span>
                {s.low_confidence && <AlertTriangle size={13} className="bubble-flag" />}
              </div>
            </div>
          );
        })}
        {!visible.length && <div className="muted center-pad">Nada coincide con el filtro.</div>}
      </div>
    </div>
  );
}

type Block = { type: "p" | "h"; text: string } | { type: "ul"; items: string[] };

/** Párrafos, títulos ("# …") y listas ("- …" o "* …"): lo justo para mostrar el resumen sin dependencias. */
function parseSummary(text: string): Block[] {
  const blocks: Block[] = [];
  let para: string[] = [];
  const flush = () => {
    if (para.length) blocks.push({ type: "p", text: para.join(" ") });
    para = [];
  };
  for (const raw of text.split(/\r?\n/)) {
    const line = raw.trim();
    const bullet = /^[-*•]\s+(.*)$/.exec(line);
    const heading = /^#{1,6}\s+(.*)$/.exec(line);
    if (!line) {
      flush();
    } else if (bullet) {
      flush();
      const last = blocks[blocks.length - 1];
      if (last?.type === "ul") last.items.push(bullet[1]);
      else blocks.push({ type: "ul", items: [bullet[1]] });
    } else if (heading) {
      flush();
      blocks.push({ type: "h", text: heading[1] });
    } else {
      para.push(line);
    }
  }
  flush();
  return blocks;
}

function Summary({ meeting, phase }: { meeting: MeetingT; phase: Phase }) {
  if (phase === "recording" || phase === "transcribing" || phase === "analyzing") {
    return (
      <div className="summary-wait">
        <div className="skeleton" />
        <div className="skeleton short" />
        <div className="muted">
          <Brain size={16} />{" "}
          {phase === "analyzing"
            ? "La IA está leyendo la transcripción…"
            : "El resumen se genera al terminar la transcripción."}
        </div>
      </div>
    );
  }
  if (meeting.analysis_status === "skipped") {
    return (
      <Empty icon={<Brain size={24} />} title="Resumen desactivado">
        MT_ANALYZER=none en la configuración.
      </Empty>
    );
  }
  if (meeting.analysis_status === "failed") {
    return (
      <Empty icon={<Brain size={24} />} title="Resumen no disponible">
        El análisis falló; puedes reintentarlo con «Reanalizar».
      </Empty>
    );
  }
  if (!meeting.summary?.trim()) {
    return (
      <Empty icon={<Brain size={24} />} title="Sin resumen">
        No hay contenido suficiente en la transcripción para resumir.
      </Empty>
    );
  }
  return (
    <div className="summary">
      {parseSummary(meeting.summary).map((b, i) =>
        b.type === "ul" ? (
          <ul key={i}>
            {b.items.map((it, j) => (
              <li key={j}>{it}</li>
            ))}
          </ul>
        ) : b.type === "h" ? (
          <h3 key={i}>{b.text}</h3>
        ) : (
          <p key={i}>{b.text}</p>
        ),
      )}
    </div>
  );
}

export function Meeting() {
  const id = Number(useParams().id);
  const [params] = useSearchParams();
  const navigate = useNavigate();
  const qc = useQueryClient();
  const toast = useToast();
  const rec = useRecorder();
  const focus = params.get("seg") ? Number(params.get("seg")) : null;
  const [tab, setTab] = useState<"summary" | "transcript">(focus != null ? "transcript" : "summary");
  const [copied, setCopied] = useState(false);

  const meetingQ = useQuery({
    queryKey: ["meeting", id],
    queryFn: () => api.meeting(id),
    refetchInterval: (q) => {
      const m = q.state.data;
      return m && (phaseOf(m) === "ready" || phaseOf(m) === "failed") ? false : 2500;
    },
  });
  const m = meetingQ.data;
  const phase: Phase | null = m ? phaseOf(m) : null;
  const live = phase === "recording" || phase === "transcribing" || phase === "analyzing";

  const progressQ = useQuery({
    queryKey: ["progress", id],
    queryFn: () => api.progress(id),
    enabled: !!m,
    refetchInterval: live ? 2500 : false,
  });
  const segmentsQ = useQuery({
    queryKey: ["segments", id],
    queryFn: () => api.segments(id),
    enabled: !!m,
    refetchInterval: phase === "recording" || phase === "transcribing" ? 4000 : false,
  });

  // Al cambiar de fase, refresca lo que depende de ella.
  useEffect(() => {
    if (!phase) return;
    void qc.invalidateQueries({ queryKey: ["segments", id] });
    void qc.invalidateQueries({ queryKey: ["meetings"] });
  }, [phase, id, qc]);

  if (meetingQ.isLoading)
    return (
      <div className="page center-pad">
        <Spinner size={24} />
      </div>
    );
  if (meetingQ.error || !m || !phase) {
    return (
      <div className="page">
        <Empty icon={<FileText size={24} />} title="Reunión no encontrada">
          <Link to="/" className="btn btn-ghost" style={{ marginTop: 12 }}>
            <ArrowLeft size={16} /> Volver
          </Link>
        </Empty>
      </div>
    );
  }

  const title = meetingTitle(m);
  const duration = fmtDuration(m.created_at, m.finished_at);
  const recordingHere = rec.meeting?.id === m.id;

  const download = async () => downloadText(`${slug(title)}.md`, await api.markdown(m.id));
  const copy = async () => {
    await navigator.clipboard.writeText(await api.markdown(m.id));
    setCopied(true);
    setTimeout(() => setCopied(false), 1500);
  };
  const reanalyze = async () => {
    await api.reanalyze(m.id);
    toast("Reanálisis en cola", "info");
    void qc.invalidateQueries({ queryKey: ["meeting", id] });
  };
  const remove = async () => {
    await api.deleteMeeting(m.id);
    toast("Reunión eliminada", "ok");
    void qc.invalidateQueries({ queryKey: ["meetings"] });
    navigate("/");
  };
  const finish = async () => {
    await api.finish(m.id);
    toast("Reunión cerrada. Transcribiendo…", "ok");
    void qc.invalidateQueries({ queryKey: ["meeting", id] });
  };

  return (
    <div className="page">
      <Link to="/" className="back muted">
        <ArrowLeft size={16} /> Reuniones
      </Link>

      <header className="meeting-head rise">
        <div>
          <div className="meeting-head-tags">
            <StatusPill phase={phase} />
            <ProjectTag name={m.project} />
          </div>
          <h1 className="display-sm">{title}</h1>
          <div className="muted meta-row">
            <CalendarClock size={15} /> {fmtDate(m.created_at)}
            {duration && <span>· {duration}</span>}
          </div>
        </div>
        <div className="actions">
          <button className="btn btn-ghost" onClick={copy} disabled={phase === "recording"}>
            {copied ? <Check size={16} /> : <Copy size={16} />} {copied ? "Copiado" : "Copiar"}
          </button>
          <button className="btn btn-ghost" onClick={download} disabled={phase === "recording"}>
            <Download size={16} /> Markdown
          </button>
          <button className="btn btn-ghost" onClick={reanalyze} disabled={phase !== "ready" && phase !== "failed"}>
            <RefreshCw size={16} /> Reanalizar
          </button>
          <ConfirmButton onConfirm={remove} disabled={recordingHere}>
            <Trash2 size={16} /> Eliminar
          </ConfirmButton>
        </div>
      </header>

      {phase === "recording" && (
        <div className="alert alert-info">
          <Mic size={16} />
          {recordingHere ? (
            <>
              Grabando ahora mismo.{" "}
              <Link to="/record" className="link">
                Ir a la grabación
              </Link>
            </>
          ) : (
            <>
              Esta reunión sigue abierta (¿se cerró el navegador mientras grababas?).
              <button className="btn btn-sm btn-primary" onClick={finish}>
                <Square size={14} /> Cerrar y transcribir
              </button>
            </>
          )}
        </div>
      )}
      {phase === "failed" && (
        <div className="alert alert-error">
          <AlertTriangle size={16} />
          <div>
            El análisis con IA falló; la transcripción sí está disponible.
            {m.analysis_error && <div className="small mono err-detail">{m.analysis_error}</div>}
          </div>
          <button className="btn btn-sm btn-ghost" onClick={reanalyze}>
            <RefreshCw size={14} /> Reintentar
          </button>
        </div>
      )}
      {progressQ.data && progressQ.data.chunks_failed > 0 && (
        <div className="alert alert-warn">
          <AlertTriangle size={16} /> {progressQ.data.chunks_failed} fragmentos no se pudieron transcribir (mira{" "}
          <code>make logs</code>).
        </div>
      )}

      <Stepper phase={phase} progress={progressQ.data} />

      <div className="tabs">
        <button className={`tab ${tab === "summary" ? "active" : ""}`} onClick={() => setTab("summary")}>
          <Brain size={16} /> Resumen
        </button>
        <button className={`tab ${tab === "transcript" ? "active" : ""}`} onClick={() => setTab("transcript")}>
          <FileText size={16} /> Transcripción
          {segmentsQ.data && segmentsQ.data.length > 0 && <span className="tab-count">{segmentsQ.data.length}</span>}
        </button>
      </div>

      <div className="glass tab-panel">
        {tab === "summary" ? (
          <Summary meeting={m} phase={phase} />
        ) : (
          <Transcript segments={segmentsQ.data ?? []} phase={phase} focus={focus} />
        )}
      </div>
    </div>
  );
}
