import { useMemo, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { CalendarClock, FileText, FolderKanban, ListChecks, Mic, Search, Sparkles } from "lucide-react";
import { api } from "../api";
import { fmtDuration, fmtRelative, isBusy, meetingTitle, phaseOf } from "../format";
import type { Meeting } from "../types";
import { Empty, ProgressBar, ProjectTag, Spinner, StatusPill } from "../components/ui";

function greeting() {
  const h = new Date().getHours();
  return h < 13 ? "Buenos días" : h < 21 ? "Buenas tardes" : "Buenas noches";
}

function MeetingCard({ m, index }: { m: Meeting; index: number }) {
  const phase = phaseOf(m);
  const busy = isBusy(phase);
  const { data: p } = useQuery({
    queryKey: ["progress", m.id],
    queryFn: () => api.progress(m.id),
    enabled: phase !== "ready",
    refetchInterval: busy ? 3000 : false,
  });
  const ratio = p && p.chunks_total ? p.chunks_done / p.chunks_total : 0;
  const duration = fmtDuration(m.created_at, m.finished_at);

  return (
    <Link to={`/meetings/${m.id}`} className={`meeting-card glass rise ${busy ? "is-busy" : ""}`} style={{ animationDelay: `${Math.min(index, 12) * 40}ms` }}>
      <div className="meeting-card-top">
        <StatusPill phase={phase} />
        <ProjectTag name={m.project} />
      </div>
      <h3 className="meeting-card-title">{meetingTitle(m)}</h3>
      <div className="meeting-card-meta muted">
        <CalendarClock size={14} /> {fmtRelative(m.created_at)}
        {duration && <span>· {duration}</span>}
      </div>
      {phase === "transcribing" && (
        <div className="meeting-card-progress">
          <ProgressBar value={ratio} />
          <span className="muted small">
            {p ? `${p.chunks_done}/${p.chunks_total} fragmentos` : "…"}
          </span>
        </div>
      )}
      {phase === "analyzing" && (
        <div className="meeting-card-progress">
          <ProgressBar value={1} indeterminate />
          <span className="muted small">La IA está leyendo la transcripción…</span>
        </div>
      )}
    </Link>
  );
}

export function Dashboard() {
  const navigate = useNavigate();
  const [project, setProject] = useState<string | null>(null);
  const [filter, setFilter] = useState("");

  const { data: meetings, isLoading, error } = useQuery({
    queryKey: ["meetings"],
    queryFn: api.meetings,
    refetchInterval: (q) => (q.state.data?.some((m) => phaseOf(m) !== "ready" && phaseOf(m) !== "failed") ? 4000 : 20_000),
  });
  const { data: requirements } = useQuery({ queryKey: ["requirements"], queryFn: () => api.requirements() });

  const projects = useMemo(
    () => [...new Set((meetings ?? []).map((m) => m.project).filter(Boolean))].sort(),
    [meetings],
  );
  const visible = useMemo(() => {
    const f = filter.trim().toLowerCase();
    return (meetings ?? []).filter(
      (m) => (!project || m.project === project) && (!f || meetingTitle(m).toLowerCase().includes(f)),
    );
  }, [meetings, project, filter]);
  const processing = (meetings ?? []).filter((m) => isBusy(phaseOf(m))).length;

  const stats = [
    { icon: FileText, label: "Reuniones", value: meetings?.length ?? "–", tone: "violet" },
    { icon: Sparkles, label: "En proceso", value: processing, tone: "cyan" },
    { icon: ListChecks, label: "Requisitos", value: requirements?.length ?? "–", tone: "green" },
    { icon: FolderKanban, label: "Proyectos", value: projects.length, tone: "pink" },
  ];

  return (
    <div className="page">
      <section className="hero glass rise">
        <div className="hero-text">
          <span className="eyebrow">{greeting()} 👋</span>
          <h1 className="display">
            Graba. Transcribe. <span className="gradient-text">Entiende.</span>
          </h1>
          <p className="muted">
            Pulsa grabar al empezar la reunión. Al terminar, Whisper la transcribe y la IA extrae requisitos,
            decisiones y dudas — todo en tu máquina.
          </p>
        </div>
        <button className="record-cta" onClick={() => navigate("/record")}>
          <span className="record-cta-ring" />
          <span className="record-cta-core">
            <Mic size={30} />
          </span>
          <span className="record-cta-label">Nueva grabación</span>
        </button>
      </section>

      <section className="stats">
        {stats.map(({ icon: Icon, label, value, tone }, i) => (
          <div key={label} className="stat glass rise" style={{ animationDelay: `${80 + i * 50}ms` }}>
            <div className={`stat-icon tone-${tone}`}>
              <Icon size={18} />
            </div>
            <div>
              <div className="stat-value">{value}</div>
              <div className="muted small">{label}</div>
            </div>
          </div>
        ))}
      </section>

      <section>
        <div className="section-head">
          <h2>Reuniones</h2>
          <div className="input-icon input-sm">
            <Search size={15} />
            <input value={filter} onChange={(e) => setFilter(e.target.value)} placeholder="Filtrar por título" />
          </div>
        </div>
        {projects.length > 0 && (
          <div className="chips">
            <button className={`chip ${!project ? "active" : ""}`} onClick={() => setProject(null)}>
              Todos
            </button>
            {projects.map((p) => (
              <button key={p} className={`chip ${project === p ? "active" : ""}`} onClick={() => setProject(p)}>
                #{p}
              </button>
            ))}
          </div>
        )}

        {isLoading && (
          <div className="center-pad">
            <Spinner size={22} />
          </div>
        )}
        {error && <div className="alert alert-error">{(error as Error).message}</div>}
        {meetings && meetings.length === 0 && (
          <Empty icon={<Mic size={26} />} title="Aún no hay reuniones">
            Graba la primera y aparecerá aquí con su transcripción y análisis.
            <div style={{ marginTop: 16 }}>
              <button className="btn btn-primary" onClick={() => navigate("/record")}>
                <Mic size={16} /> Grabar ahora
              </button>
            </div>
          </Empty>
        )}
        {meetings && meetings.length > 0 && visible.length === 0 && (
          <Empty icon={<Search size={24} />} title="Sin resultados">Prueba con otro filtro.</Empty>
        )}
        <div className="meeting-grid">
          {visible.map((m, i) => (
            <MeetingCard key={m.id} m={m} index={i} />
          ))}
        </div>
      </section>
    </div>
  );
}
