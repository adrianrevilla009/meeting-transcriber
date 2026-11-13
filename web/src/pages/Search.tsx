import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { Search as SearchIcon, TextSearch } from "lucide-react";
import { api } from "../api";
import { fmtDate, fmtTs, meetingTitle } from "../format";
import type { SearchHit } from "../types";
import { Empty, highlight, Spinner } from "../components/ui";

function useDebounced<T>(value: T, ms: number): T {
  const [v, setV] = useState(value);
  useEffect(() => {
    const t = setTimeout(() => setV(value), ms);
    return () => clearTimeout(t);
  }, [value, ms]);
  return v;
}

export function Search() {
  const [q, setQ] = useState("");
  const term = useDebounced(q.trim(), 300);
  const { data: hits, isFetching } = useQuery({
    queryKey: ["search", term],
    queryFn: () => api.search(term),
    enabled: term.length >= 2,
    placeholderData: (prev) => prev,
  });
  const meetingsQ = useQuery({ queryKey: ["meetings"], queryFn: api.meetings });
  const meetings = useMemo(() => new Map((meetingsQ.data ?? []).map((m) => [m.id, m])), [meetingsQ.data]);

  const groups = useMemo(() => {
    const g = new Map<number, SearchHit[]>();
    for (const h of hits ?? []) g.set(h.meeting_id, [...(g.get(h.meeting_id) ?? []), h]);
    return [...g.entries()];
  }, [hits]);

  return (
    <div className="page">
      <header className="page-head rise">
        <h1 className="display-sm">Buscar</h1>
        <p className="muted">Encuentra cualquier frase dicha en cualquier reunión.</p>
      </header>

      <div className="search-hero rise">
        <SearchIcon size={22} />
        <input
          autoFocus
          value={q}
          onChange={(e) => setQ(e.target.value)}
          placeholder="presupuesto, fecha de entrega, Bizum…"
        />
        {isFetching && <Spinner size={18} />}
      </div>

      {term.length < 2 ? (
        <Empty icon={<TextSearch size={26} />} title="Escribe al menos 2 letras" />
      ) : hits && !hits.length ? (
        <Empty icon={<TextSearch size={26} />} title="Sin coincidencias">
          Nadie dijo «{term}» en ninguna reunión transcrita.
        </Empty>
      ) : (
        <div className="search-results">
          {hits && (
            <div className="muted small">
              {hits.length} coincidencias en {groups.length} reuniones
            </div>
          )}
          {groups.map(([mid, list]) => {
            const m = meetings.get(mid);
            return (
              <section key={mid} className="glass search-group rise">
                <Link to={`/meetings/${mid}`} className="search-group-head">
                  <strong>{m ? meetingTitle(m) : `Reunión #${mid}`}</strong>
                  <span className="muted small">{m ? fmtDate(m.created_at) : ""}</span>
                </Link>
                {list.map((h) => (
                  <Link key={h.segment_id} to={`/meetings/${mid}?seg=${h.segment_id}`} className="search-hit">
                    <span className="bubble-ts mono">{fmtTs(h.start)}</span>
                    <span>{highlight(h.text, term)}</span>
                  </Link>
                ))}
              </section>
            );
          })}
        </div>
      )}
    </div>
  );
}
