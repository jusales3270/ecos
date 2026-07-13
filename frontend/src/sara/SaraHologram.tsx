import { useEffect, useRef } from "react";
import type { SaraMode, SaraState } from "./saraTypes";

const colors = ["#ffb54d", "#ff8c1a", "#ffd591", "#c25607", "#ffedc4", "#ff7a00"];
type Particle = { a: number; r: number; speed: number; size: number; color: string; tilt: number };

export function SaraHologram({ mode, state, reducedMotion }: { mode: SaraMode; state: SaraState; reducedMotion: boolean }) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const particlesRef = useRef<Particle[] | null>(null);
  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas || mode === "closed") return;
    if (!particlesRef.current) particlesRef.current = Array.from({ length: 2200 }, (_, index) => ({ a: Math.random() * Math.PI * 2, r: .18 + (index % 7) * .105 + Math.random() * .09, speed: .0008 + Math.random() * .0028, size: .5 + Math.random() * 1.8, color: colors[index % colors.length], tilt: (index % 7) * .42 }));
    const context = canvas.getContext("2d");
    if (!context) return;
    let raf = 0;
    let hidden = document.hidden;
    const resize = () => {
      const size = canvas.getBoundingClientRect();
      const dpr = Math.min(window.devicePixelRatio || 1, 1.5);
      canvas.width = Math.max(1, Math.floor(size.width * dpr)); canvas.height = Math.max(1, Math.floor(size.height * dpr));
      context.setTransform(dpr, 0, 0, dpr, 0, 0);
    };
    const visibility = () => { hidden = document.hidden; };
    const draw = (time: number) => {
      const w = canvas.clientWidth, h = canvas.clientHeight, radius = Math.min(w, h) * .36;
      context.clearRect(0, 0, w, h); context.globalCompositeOperation = "lighter";
      const limit = reducedMotion ? 260 : mode === "mini" ? 650 : 2200;
      if (!hidden || time % 4 < 1) particlesRef.current?.slice(0, limit).forEach((p, index) => {
        if (!reducedMotion && !hidden) p.a += p.speed * (state === "thinking" ? 3 : state === "speaking" ? 1.8 : 1);
        const x3 = Math.cos(p.a) * p.r, y3 = Math.sin(p.a) * p.r * Math.cos(p.tilt), z3 = Math.sin(p.a) * p.r * Math.sin(p.tilt);
        const scale = 1 / (1.35 - z3); const x = w / 2 + x3 * radius * scale, y = h / 2 + y3 * radius * scale;
        context.globalAlpha = .2 + scale * .5; context.fillStyle = p.color;
        const s = p.size * scale * (state === "listening" && index % 8 === 0 ? 2 : 1); context.fillRect(x, y, s, s);
      });
      context.globalAlpha = 1; raf = requestAnimationFrame(draw);
    };
    resize(); window.addEventListener("resize", resize); document.addEventListener("visibilitychange", visibility); raf = requestAnimationFrame(draw);
    return () => { cancelAnimationFrame(raf); window.removeEventListener("resize", resize); document.removeEventListener("visibilitychange", visibility); };
  }, [mode, reducedMotion, state]);
  return <canvas ref={canvasRef} className="sh-canvas" aria-hidden="true" />;
}
