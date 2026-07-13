import type { SaraMode, SaraState } from "./saraTypes";

export type HologramVisualState = "idle" | "listening" | "thinking" | "speaking";
export type Vec3 = { x: number; y: number; z: number };
export type PlaneBasis = readonly [number, number, number, number, number, number];
export type HologramParticle = { a:number; r:number; sp:number; sz:number; al:number; col:string; wf:number; ph:number; streak:boolean; cl:number; cm:number; B:PlaneBasis; ps:number; tx:number; ty:number; pz:number };
export type OrbitalArc = { r:number; a:number; len:number; w:number; sp:number; col:string; al:number; B:PlaneBasis };
export type NeuralNode = { f1:number; f2:number; f3:number; p1:number; p2:number; p3:number; x:number; y:number; z:number; sx:number; sy:number };
export type Effect = Record<string, number | string | PlaneBasis | number[]>;
export type HologramSystem = {
  particles:HologramParticle[]; arcs:OrbitalArc[]; tickRings:{ B:PlaneBasis; r:number; step:number }[]; nodes:NeuralNode[];
  flares:Effect[]; waves:Effect[]; sparks:Effect[]; comets:Effect[]; rings:Effect[]; bolts:Effect[];
  coreFlash:number; sonarClock:number; lastWave:number;
};
export type HologramEngineOptions = { mode:Exclude<SaraMode,"closed">; state:SaraState; reducedMotion:boolean; speakPulse:number };
export type HologramEngine = { system:Readonly<HologramSystem>; update(options:Partial<HologramEngineOptions>):void; resize():void; rotate(dx:number,dy:number):void; start():void; stop():void; destroy():void };
