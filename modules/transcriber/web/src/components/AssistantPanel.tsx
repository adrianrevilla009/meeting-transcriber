import { useEffect, useReducer, useState, type FormEvent } from "react";
import { AlertTriangle, Bot, Send, ShieldCheck, Sparkles } from "lucide-react";
import { assistant, isUnavailable, streamEvents } from "../assistantApi";
import { applyEvent, EMPTY_VIEW, type QA } from "../assistantState";
import { fmtTs } from "../format";
import { Empty, Spinner } from "./ui";

type Conn = "loading" | "unavailable" | "ready";

function Card({ qa, onAnswer }: { qa: QA; onAnswer: (id: string) => void }) {
  return (
    <article className={`assistant-card assistant-${qa.status}`}>
      <div className="assistant-q">
        <span className="tag mono">{fmtTs(qa.ts)}</span>
        <span>{qa.text}</span>
        {qa.origin === "manual" && <span className="muted small">(tu pregunta)</span>}
      </div>
      {qa.status === "unanswered" &&
        (qa.origin === "detected" ? (
          <button className="btn btn-sm btn-ghost" onClick={() => onAnswer(qa.id)}>
            <Sparkles size={14} /> Responder
          </button>
        ) : (
          <div className="muted small">
            <Spinner size={13} /> Pensando…
          </div>
        ))}
      {(qa.status === "streaming" || qa.status === "done") && (
        <div className="assistant-a" aria-live="polite">
          {qa.answer || <Spinner size={14} />}
        </div>
      )}
      {qa.status === "error" && (
        <div className="alert alert-error">
          <AlertTriangle size={16} /> {qa.error}
        </div>
      )}
    </article>
  );
}

export function AssistantPanel({ meetingId }: { meetingId: number }) {
  const [conn, setConn] = useState<Conn>("loading");
  const [following, setFollowing] = useState(false);
  const [busy, setBusy] = useState(false);
  const [text, setText] = useState("");
  const [problem, setProblem] = useState<string | null>(null);
  const [view, dispatch] = useReducer(applyEvent, EMPTY_VIEW);

  // Estado inicial y, si el servicio responde, flujo de eventos (el servidor reenvía el histórico al conectar).
  useEffect(() => {
    const ctl = new AbortController();
    assistant
      .status(meetingId)
      .then((s) => {
        if (ctl.signal.aborted) return;
        setFollowing(s.following);
        setConn("ready");
        return streamEvents(meetingId, 0, dispatch, ctl.signal);
      })
      .catch((e: unknown) => {
        if (ctl.signal.aborted) return;
        if (isUnavailable(e)) setConn("unavailable");
        else setProblem(e instanceof Error ? e.message : "Error del asistente");
      });
    return () => ctl.abort();
  }, [meetingId]);

  const run = async (action: () => Promise<unknown>) => {
    setBusy(true);
    setProblem(null);
    try {
      await action();
    } catch (e) {
      if (isUnavailable(e)) setConn("unavailable");
      else setProblem(e instanceof Error ? e.message : "Error del asistente");
    } finally {
      setBusy(false);
    }
  };

  const toggle = () =>
    run(async () => {
      if (following) await assistant.unfollow(meetingId);
      else await assistant.follow(meetingId);
      setFollowing(!following);
    });

  const ask = (e: FormEvent) => {
    e.preventDefault();
    const q = text.trim();
    if (!q) return;
    void run(async () => {
      await assistant.ask(meetingId, q);
      setText("");
    });
  };

  if (conn === "loading")
    return (
      <div className="center-pad">
        <Spinner size={22} />
      </div>
    );

  if (conn === "unavailable")
    return (
      <Empty icon={<Bot size={24} />} title="Asistente no disponible">
        El servicio del asistente no responde. Comprueba que está arrancado y vuelve a abrir esta pestaña.
      </Empty>
    );

  return (
    <div className="assistant">
      <div className="assistant-head">
        <div>
          <strong>Asistente en vivo</strong>
          <div className="muted small">Detecta las preguntas que te hacen y te sugiere qué responder.</div>
        </div>
        <button className={`btn ${following ? "btn-ghost" : "btn-primary"}`} onClick={toggle} disabled={busy}>
          {following ? "Desactivar asistente" : "Activar asistente"}
        </button>
      </div>

      {problem && (
        <div className="alert alert-error">
          <AlertTriangle size={16} /> {problem}
        </div>
      )}
      {view.notices.map((n, i) => (
        <div key={i} className="alert alert-warn">
          <AlertTriangle size={16} /> {n}
        </div>
      ))}

      {view.items.length === 0 ? (
        <Empty icon={<Sparkles size={24} />} title="Sin preguntas todavía">
          {following
            ? "Escucho la reunión. Cuando alguien te haga una pregunta, la verás aquí con una respuesta sugerida."
            : "Activa el asistente para que escuche la reunión, o escribe tú una pregunta abajo."}
        </Empty>
      ) : (
        <div className="assistant-list">
          {view.items.map((qa) => (
            <Card key={qa.id} qa={qa} onAnswer={(id) => void run(() => assistant.answer(meetingId, id))} />
          ))}
        </div>
      )}

      <form className="assistant-ask" onSubmit={ask}>
        <input
          value={text}
          onChange={(e) => setText(e.target.value)}
          placeholder="Pregunta algo al asistente"
          aria-label="Pregunta para el asistente"
        />
        <button type="submit" className="btn btn-primary" disabled={busy || !text.trim()}>
          <Send size={15} /> Preguntar
        </button>
      </form>

      <div className="hint">
        <ShieldCheck size={16} />
        <div>
          Las consultas pasan por el filtro de privacidad: los datos personales se sustituyen antes de salir y se
          restauran en la respuesta.
        </div>
      </div>
    </div>
  );
}
