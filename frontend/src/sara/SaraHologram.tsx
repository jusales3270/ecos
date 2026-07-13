import { useEffect, useRef } from "react";
import { createSaraHologramEngine } from "./saraHologramEngine";
import type { HologramEngine } from "./saraHologramTypes";
import type { SaraMode, SaraState } from "./saraTypes";

export type SaraHologramProps = { mode:Exclude<SaraMode,"closed">; state:SaraState; reducedMotion:boolean; speakPulse:number };

export function SaraHologram({mode,state,reducedMotion,speakPulse}:SaraHologramProps){
  const canvasRef=useRef<HTMLCanvasElement>(null),engineRef=useRef<HologramEngine|null>(null),drag=useRef({active:false,moved:false,x:0,y:0}),initial=useRef({mode,state,reducedMotion,speakPulse});
  useEffect(()=>{const canvas=canvasRef.current;if(!canvas)return;const engine=createSaraHologramEngine(canvas,initial.current);engineRef.current=engine;const observer=typeof ResizeObserver!=="undefined"?new ResizeObserver(()=>engine.resize()):null;observer?.observe(canvas);window.addEventListener("resize",engine.resize);engine.start();return()=>{observer?.disconnect();window.removeEventListener("resize",engine.resize);engine.destroy();engineRef.current=null;};},[]);
  useEffect(()=>engineRef.current?.update({mode,state,reducedMotion,speakPulse}),[mode,state,reducedMotion,speakPulse]);
  return <canvas ref={canvasRef} className="sh-canvas" aria-hidden="true" data-particles={reducedMotion?320:mode==="mini"?720:2200}
    onPointerDown={e=>{if(mode!=="full")return;drag.current={active:true,moved:false,x:e.clientX,y:e.clientY};e.currentTarget.setPointerCapture?.(e.pointerId);}}
    onPointerMove={e=>{const d=drag.current;if(mode!=="full"||!d.active)return;const dx=e.clientX-d.x,dy=e.clientY-d.y;if(Math.abs(dx)+Math.abs(dy)>3)d.moved=true;engineRef.current?.rotate(dx,dy);d.x=e.clientX;d.y=e.clientY;}}
    onPointerUp={()=>{drag.current.active=false;}} onPointerCancel={()=>{drag.current.active=false;}} />;
}
