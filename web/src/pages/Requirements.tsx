import { useEffect, useMemo, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { useQueries, useQuery } from "@tanstack/react-query";
import { ChevronDown, GitCommitVertical, ListChecks, Quote } from "lucide-react";
import { api } from "../api";
import { fmtDate, fmtTs, meetingTitle } from "../format";
import type { Meeting, RequirementHistory } from "../types";
import { Empty, KindBadge, ProjectTag, Spinner } from "../components/ui";

function RequirementCard({
  history,
  meetings,
  open,
  onToggle,
}: {
  history: RequirementHistory;
  meetings: Map<number, Meeting>;
  open: boolean;
  onToggle: () => void;
}) {
  const { requirement: r, events } = history;
  const last = events[events.length - 1];
  const meetingCount = new Set(events.map((e) => e.meeting_id)).size;
  const changed = events.some((e) => e.kind === "changed_requirement");

  return (
    <div id={`req-${r.id}`} className={`req glass ${open ? "open" : ""}`}>
      <button className="req-head" onClick={onToggle} aria-expanded={open}>
        <div className="req-main">
          <div className="req-tags">
            <ProjectTag name={r.project} />
            {changed && <span className="badge tone-amber">ha cambiado</span>}
          </div>
          <h3>{r.title}</h3>
          {last && <p className="muted">{last.summary}</p>}
        </div>
        <div className="req-side">
          <div className="req-count">
            <strong>{events.length}</strong>
            <span className="muted small">menciones · {meetingCount} reuniones</span>
          </div>
          <ChevronDown size={18} className="req-chevron" />
        </div>
      </button>
      {open && (
        <ol className="timeline">
          {events.map((e) => {
            const m = meetings.get(e.meeting_id);
            return (
              <li key={e.id} className="timeline-item">
                <GitCommitVertical size={16} className="timeline-icon" />
                <div className="timeline-body">
                  <div className="timeline-top">
                    <KindBadge kind={e.kind} />
                    <Link to={`/meetings/${e.meeting_id}${e.segment_id ? `?seg=${e.segment_id}` : ""}`} className="link">
                      {m ? meetingTitle(m) : `Reunión #${e.meeting_id}`}
                    </Link>
                    <span className="muted small">
                      {m ? fmtDate(m.created_at) : ""} · {fmtTs(e.timestamp)}
                    </span>
                  </div>
                  <p>{e.summary}</p>
                  <blockquote>
                    <Quote size={13} />
                    {e.quote}
                  </blockquote>
                </div>
              </li>
            );
          })}
        </ol>
      )}
    </div>
  );
}

export function Requirements() {
  const [params] = useSearchParams();
  const focus = params.get("focus") ? Number(params.get("focus")) : null;
  const [project, setProject] = useState<string | null>(null);
  const [open, setOpen] = useState<Set<number>>(new Set(focus != null ? [focus] : []));

  const reqsQ = useQuery({ queryKey: ["requirements"], queryFn: () => api.requirements() });
  const meetingsQ = useQuery({ queryKey: ["meetings"], queryFn: api.meetings });
  const reqs = reqsQ.data ?? [];
  const projects = useMemo(() => [...new Set(reqs.map((r) => r.project).filter(Boolean))].sort(), [reqs]);
  const filtered = reqs.filter((r) => !project || r.project === project);

  const histories = useQueries({
    queries: filtered.map((r) => ({ queryKey: ["history", r.id], queryFn: () => api.history(r.id) })),
  });
  const meetings = useMemo(() => new Map((meetingsQ.data ?? []).map((m) => [m.id, m])), [meetingsQ.data]);

  useEffect(() => {
    if (focus == null) return;
    const t = setTimeout(() => document.getElementById(`req-${focus}`)?.scrollIntoView({ behavior: "smooth", block: "center" }), 300);
    return () => clearTimeout(t);
  }, [focus, histories.length]);

  const toggle = (id: number) =>
    setOpen((s) => {
      const n = new Set(s);
      if (n.has(id)) n.delete(id);
      else n.add(id);
      return n;
    });

  return (
    <div className="page">
      <header className="page-head rise">
        <h1 className="display-sm">Requisitos</h1>
        <p className="muted">Cómo evoluciona cada requisito a lo largo de las reuniones, con la cita exacta de quién lo dijo.</p>
      </header>

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

      {reqsQ.isLoading && (
        <div className="center-pad">
          <Spinner size={22} />
        </div>
      )}
      {reqsQ.data && !reqs.length && (
        <Empty icon={<ListChecks size={26} />} title="Todavía no hay requisitos">
          Aparecerán cuando la IA analice reuniones donde se hablen requisitos o decisiones.
        </Empty>
      )}
      <div className="req-list">
        {filtered.map((r, i) => {
          const h = histories[i]?.data;
          return h ? (
            <RequirementCard key={r.id} history={h} meetings={meetings} open={open.has(r.id)} onToggle={() => toggle(r.id)} />
          ) : (
            <div key={r.id} className="req glass skeleton-card" />
          );
        })}
      </div>
    </div>
  );
}
