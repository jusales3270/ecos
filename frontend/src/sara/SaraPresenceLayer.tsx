import { Mic, MicOff, Minimize2, Send, Volume2, VolumeX, X } from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import { ApiError } from "../api";
import { useAuth } from "../auth";
import { isSaraAction, runSaraAction } from "./saraActions";
import { sendSaraInteraction } from "./saraApi";
import { SaraHologram } from "./SaraHologram";
import { loadSaraPreferences, saveSaraPreferences } from "./saraStorage";
import type { SaraHistoryItem, SaraMode, SaraPoint, SaraState } from "./saraTypes";
import "./sara-live.css";

const greeting = "Sou a SARA, uma interface cognitiva do E.C.O.S. Posso registrar objetivos e abrir áreas permitidas; decisões, aprovações e execuções permanecem sob governança humana.";
const ttsUrl = import.meta.env.VITE_SARA_TTS_URL as string | undefined;
const labels: Record<SaraState, string> = { idle: "DISPONÍVEL", listening: "ESCUTANDO", thinking: "PROCESSANDO", speaking: "TRANSMITINDO", offline: "INDISPONÍVEL", error: "ERRO", waiting_approval: "AGUARDANDO APROVAÇÃO", executing: "ACOMPANHANDO EXECUÇÃO" };

export function SaraPresenceLayer() {
  const { auth } = useAuth(); const navigate = useNavigate(); const location = useLocation();
  const org = auth!.organization.organization_id, user = auth!.principal.user_id;
  const initial = useMemo(() => loadSaraPreferences(org, user), [org, user]);
  const [mode, setMode] = useState<SaraMode>(initial.mode); const [position, setPosition] = useState(initial.position);
  const [voice, setVoice] = useState(initial.voice); const [state, setState] = useState<SaraState>("idle");
  const [caption, setCaption] = useState(greeting); const [input, setInput] = useState(""); const [sessionId, setSessionId] = useState<string | null>(null);
  const [rotation, setRotation] = useState(0); const audio = useRef<HTMLAudioElement | null>(null); const audioUrl = useRef<string | null>(null);
  const history = useRef<SaraHistoryItem[]>([]); const inputRef = useRef<HTMLInputElement>(null); const previousFocus = useRef<HTMLElement | null>(null);
  const drag = useRef({ active: false, moved: false, x: 0, y: 0, origin: initial.position });
  const recognition = useRef<SpeechRecognitionLike | null>(null);
  const reducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  const persist = useCallback((nextMode = mode, nextPosition = position, nextVoice = voice) => saveSaraPreferences(org, user, { mode: nextMode, position: nextPosition, voice: nextVoice, expansionAllowed: initial.expansionAllowed }), [initial.expansionAllowed, mode, org, position, user, voice]);
  const changeMode = useCallback((next: SaraMode) => { setMode(next); persist(next); }, [persist]);
  const clamp = useCallback((point: SaraPoint): SaraPoint => ({ x: Math.max(8, Math.min(point.x, window.innerWidth - 128)), y: Math.max(8, Math.min(point.y, window.innerHeight - 128)) }), []);
  useEffect(() => { if (mode === "full") { previousFocus.current = document.activeElement as HTMLElement; window.setTimeout(() => inputRef.current?.focus(), 0); } else previousFocus.current?.focus?.(); }, [mode]);
  useEffect(() => { const resize = () => setPosition((old) => { const next = clamp(old); persist(mode, next); return next; }); window.addEventListener("resize", resize); return () => window.removeEventListener("resize", resize); }, [clamp, mode, persist]);
  useEffect(() => { const onKey = (event: KeyboardEvent) => { const target = event.target; const typing = target instanceof Element && target.matches("input,textarea,[contenteditable=true]"); if (!typing && event.altKey && event.key.toLowerCase() === "s") { event.preventDefault(); changeMode(mode === "closed" ? "full" : "closed"); } if (event.key === "Escape" && mode === "full") changeMode("mini"); }; window.addEventListener("keydown", onKey); return () => window.removeEventListener("keydown", onKey); }, [changeMode, mode]);
  const stopAudio = useCallback(() => { audio.current?.pause(); audio.current = null; if (audioUrl.current) URL.revokeObjectURL(audioUrl.current); audioUrl.current = null; }, []);
  useEffect(() => () => { recognition.current?.abort?.(); window.speechSynthesis?.cancel(); stopAudio(); }, [stopAudio]);
  const speakBrowser = useCallback((text: string) => { if (!window.speechSynthesis) return setState("idle"); window.speechSynthesis.cancel(); const utterance = new SpeechSynthesisUtterance(text); utterance.lang = "pt-BR"; utterance.onstart = () => setState("speaking"); utterance.onend = () => setState("idle"); utterance.onerror = () => setState("error"); window.speechSynthesis.speak(utterance); }, []);
  const speak = useCallback(async (text: string) => { if (!voice) return setState("idle"); stopAudio(); if (!ttsUrl) return speakBrowser(text); try { const response = await fetch(ttsUrl, { method: "POST", credentials: "include", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ text }) }); if (!response.ok) throw new Error("TTS unavailable"); const blob = await response.blob(); const url = URL.createObjectURL(blob); const player = new Audio(url); audio.current = player; audioUrl.current = url; player.onplay = () => setState("speaking"); player.onended = () => { stopAudio(); setState("idle"); }; player.onerror = () => { stopAudio(); speakBrowser(text); }; await player.play(); } catch { stopAudio(); speakBrowser(text); } }, [speakBrowser, stopAudio, voice]);
  const send = useCallback(async (forced?: string) => { const message = (forced ?? input).trim().slice(0, 2000); if (!message || state === "thinking") return; setInput(""); setState("thinking"); try { const result = await sendSaraInteraction(message, history.current, sessionId, location.pathname); const additions: SaraHistoryItem[] = [{ role: "user", content: message }, { role: "assistant", content: result.response }]; history.current = [...history.current, ...additions].slice(-12); setSessionId(result.session_id); setCaption(result.response); setState(result.cognitive_state === "waiting_approval" ? "waiting_approval" : result.cognitive_state === "executing" ? "executing" : "idle"); result.ui_actions.filter(isSaraAction).forEach((action) => runSaraAction(action, navigate, () => changeMode("mini"))); if (voice) speak(result.response); } catch (error) { setState(error instanceof ApiError && error.status === 0 ? "offline" : "error"); setCaption(error instanceof Error ? error.message : "SARA indisponível no momento."); } }, [changeMode, input, location.pathname, navigate, sessionId, speak, state, voice]);
  const toggleMic = () => { if (state === "listening") return recognition.current?.stop(); const Constructor = (window as SpeechWindow).SpeechRecognition ?? (window as SpeechWindow).webkitSpeechRecognition; if (!Constructor) { setState("error"); setCaption("O reconhecimento de voz não está disponível neste navegador. Use o campo de texto."); return; } const rec = new Constructor(); rec.lang = "pt-BR"; rec.interimResults = true; rec.onresult = (event) => { const value = Array.from(event.results).map((item) => item[0].transcript).join(" "); setInput(value); if (event.results[event.results.length - 1]?.isFinal) void send(value); }; rec.onend = () => setState((old) => old === "listening" ? "idle" : old); rec.onerror = () => setState("error"); recognition.current = rec; setState("listening"); rec.start(); };
  const pointerDown = (event: React.PointerEvent) => { drag.current = { active: true, moved: false, x: event.clientX, y: event.clientY, origin: position }; event.currentTarget.setPointerCapture?.(event.pointerId); };
  const pointerMove = (event: React.PointerEvent) => { if (!drag.current.active) return; const dx = event.clientX - drag.current.x, dy = event.clientY - drag.current.y; if (Math.abs(dx) + Math.abs(dy) > 5) drag.current.moved = true; if (mode === "mini") setPosition(clamp({ x: drag.current.origin.x + dx, y: drag.current.origin.y + dy })); else { setRotation((old) => old + dx * .3); drag.current.x = event.clientX; drag.current.y = event.clientY; } };
  const pointerUp = () => { if (!drag.current.active) return; drag.current.active = false; if (mode === "mini" && !drag.current.moved) changeMode("full"); else persist(mode, position); };
  return <div className={`sh-root sh-${mode}`}>
    {mode === "closed" ? <button className="sh-summon" aria-label="Invocar SARA" onClick={() => changeMode("full")}><span className="sh-halo" /><span className="sh-spark" /><span className="sh-label">SARA</span></button> : null}
    {mode !== "closed" ? <div className="sh-holo" role={mode === "full" ? "dialog" : undefined} aria-modal={mode === "full" ? "true" : undefined} aria-label="Presença SARA">
      {mode === "full" ? <div className="sh-dim" /> : null}
      <div className="sh-stage" style={mode === "mini" ? { left: position.x, top: position.y } : undefined} onPointerDown={pointerDown} onPointerMove={pointerMove} onPointerUp={pointerUp} onPointerCancel={pointerUp}>
        <div className="sh-orbit" style={{ transform: `rotate(${rotation}deg)` }}><SaraHologram mode={mode} state={state} reducedMotion={reducedMotion} /></div><div className="sh-name"><strong>S A R A</strong><span>INTERFACE COGNITIVA</span></div>
      </div>
      {mode === "full" ? <div className="sh-tools"><button aria-label="Minimizar SARA" onClick={() => changeMode("mini")}><Minimize2 /></button><button aria-label="Fechar SARA" onClick={() => { stopAudio(); window.speechSynthesis?.cancel(); changeMode("closed"); }}><X /></button></div> : null}
      {mode === "full" ? <><div className="sh-status" aria-live="polite"><i />{labels[state]}</div><div className="sh-caption"><span>S A R A</span><p>{caption}</p></div><form className="sh-console" onSubmit={(event) => { event.preventDefault(); void send(); }}><button type="button" aria-label={state === "listening" ? "Parar microfone" : "Usar microfone"} onClick={toggleMic}>{state === "listening" ? <MicOff /> : <Mic />}</button><label><span className="sr-only">Objetivo ou interação cognitiva</span><input ref={inputRef} maxLength={2000} value={input} onChange={(event) => setInput(event.target.value)} placeholder="Digite um objetivo ou interação..." /></label><button type="submit" aria-label="Enviar interação" disabled={!input.trim() || state === "thinking"}><Send /></button><button type="button" aria-label={voice ? "Desativar voz" : "Ativar voz"} onClick={() => { setVoice(!voice); persist(mode, position, !voice); window.speechSynthesis?.cancel(); }}>{voice ? <Volume2 /> : <VolumeX />}</button></form></> : null}
    </div> : null}
  </div>;
}

type SpeechRecognitionEventLike = { results: ArrayLike<{ 0: { transcript: string }; isFinal: boolean }> };
type SpeechRecognitionLike = { start(): void; stop(): void; abort?(): void; onresult: ((event: SpeechRecognitionEventLike) => void) | null; onend: (() => void) | null; onerror: (() => void) | null; lang: string; interimResults: boolean };
type SpeechWindow = Window & { SpeechRecognition?: new () => SpeechRecognitionLike; webkitSpeechRecognition?: new () => SpeechRecognitionLike };
