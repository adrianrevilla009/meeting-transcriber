import { useEffect, useRef } from "react";

const PALETTES = {
  violet: ["#a78bfa", "#f472b6"],
  cyan: ["#22d3ee", "#818cf8"],
} as const;

/** Barras espejadas que reaccionan al nivel de la fuente en tiempo real. */
export function Waveform({
  analyser,
  palette = "violet",
  bars = 56,
}: {
  analyser?: AnalyserNode;
  palette?: keyof typeof PALETTES;
  bars?: number;
}) {
  const canvas = useRef<HTMLCanvasElement>(null);

  useEffect(() => {
    const el = canvas.current;
    if (!el) return;
    const g = el.getContext("2d");
    if (!g) return;
    const data = new Uint8Array(analyser?.fftSize ?? 2048);
    const levels = new Float32Array(bars);
    let raf = 0;

    const draw = () => {
      const dpr = window.devicePixelRatio || 1;
      const w = el.clientWidth;
      const h = el.clientHeight;
      if (el.width !== w * dpr || el.height !== h * dpr) {
        el.width = w * dpr;
        el.height = h * dpr;
      }
      g.setTransform(dpr, 0, 0, dpr, 0, 0);
      g.clearRect(0, 0, w, h);

      // Nivel RMS por tramo de la forma de onda.
      if (analyser) analyser.getByteTimeDomainData(data);
      const step = Math.floor(data.length / bars);
      for (let i = 0; i < bars; i++) {
        let sum = 0;
        if (analyser) {
          for (let k = i * step; k < (i + 1) * step; k++) {
            const v = (data[k] - 128) / 128;
            sum += v * v;
          }
        }
        const rms = Math.min(1, Math.sqrt(sum / step) * 4);
        levels[i] = levels[i] * 0.7 + rms * 0.3;
      }

      const grad = g.createLinearGradient(0, 0, w, 0);
      grad.addColorStop(0, PALETTES[palette][0]);
      grad.addColorStop(1, PALETTES[palette][1]);
      g.fillStyle = grad;
      const gap = 3;
      const bw = Math.max(2, (w - gap * (bars - 1)) / bars);
      for (let i = 0; i < bars; i++) {
        const bh = Math.max(3, levels[i] * (h - 6));
        const x = i * (bw + gap);
        const y = (h - bh) / 2;
        g.globalAlpha = 0.35 + levels[i] * 0.65;
        g.beginPath();
        g.roundRect(x, y, bw, bh, bw / 2);
        g.fill();
      }
      raf = requestAnimationFrame(draw);
    };
    draw();
    return () => cancelAnimationFrame(raf);
  }, [analyser, palette, bars]);

  return <canvas ref={canvas} className="waveform" />;
}
