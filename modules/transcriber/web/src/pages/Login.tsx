import { useState, type FormEvent } from "react";
import { ArrowRight, KeyRound, ShieldCheck } from "lucide-react";
import { api, ApiError } from "../api";
import { Logo } from "../components/Layout";
import { Spinner } from "../components/ui";

export function Login({ onLogin }: { onLogin: (token: string) => void }) {
  const [token, setToken] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await api.check(token.trim());
      onLogin(token.trim());
    } catch (err) {
      setError(err instanceof ApiError && err.status === 401 ? "Ese token no es válido." : (err as Error).message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="login">
      <form className="login-card glass rise" onSubmit={submit}>
        <Logo />
        <h1 className="display">
          Tus reuniones,
          <br />
          <span className="gradient-text">transcritas en local.</span>
        </h1>
        <p className="muted">Whisper y el LLM corren en tu máquina. Nada sale de tu red.</p>
        <label className="field">
          <span>Token de acceso</span>
          <div className="input-icon">
            <KeyRound size={16} />
            <input
              type="password"
              autoFocus
              value={token}
              onChange={(e) => setToken(e.target.value)}
              placeholder="MT_API_TOKEN de tu .env"
            />
          </div>
        </label>
        {error && <div className="alert alert-error">{error}</div>}
        <button className="btn btn-primary btn-lg" disabled={!token.trim() || busy}>
          {busy ? <Spinner /> : <ArrowRight size={18} />}
          Entrar
        </button>
        <div className="login-foot muted">
          <ShieldCheck size={14} /> El token se guarda solo en este navegador.
        </div>
      </form>
    </div>
  );
}
