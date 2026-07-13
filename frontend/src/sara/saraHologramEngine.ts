import type { Effect, HologramEngine, HologramEngineOptions, HologramParticle, HologramSystem, HologramVisualState, PlaneBasis } from "./saraHologramTypes";

export const FULL_PARTICLE_COUNT = 2200;
export const MINI_PARTICLE_COUNT = 720;
export const REDUCED_PARTICLE_COUNT = 320;
export const ORBITAL_ARC_COUNT = 42;
export const NEURAL_NODE_COUNT = 13;
export const EFFECT_LIMITS = { flares:24, waves:12, sparks:96, comets:40, rings:8, bolts:16 } as const;
const PALETTE = ["#FFB54D","#FF8C1A","#FFD591","#C25607","#FFEDC4","#FF7A00"];
const TAU = Math.PI * 2;

export function planeBasis(nx:number,ny:number,nz:number):PlaneBasis { const l0=Math.hypot(nx,ny,nz)||1; nx/=l0;ny/=l0;nz/=l0; let ux:number,uy:number,uz:number; if(Math.abs(nz)<.9){ux=-ny;uy=nx;uz=0;}else{ux=0;uy=-nz;uz=ny;} const l=Math.hypot(ux,uy,uz)||1;ux/=l;uy/=l;uz/=l;return [ux,uy,uz,ny*uz-nz*uy,nz*ux-nx*uz,nx*uy-ny*ux]; }

export function makeParticleSystem(random:()=>number=Math.random):HologramSystem {
  const normals = Array.from({length:7},(_,b)=>{const th=b*2.399963,ph=Math.acos(1-(2*(b+.5))/7);return [Math.sin(ph)*Math.cos(th),Math.cos(ph),Math.sin(ph)*Math.sin(th)] as const;});
  const particles:HologramParticle[]=[];
  for(let i=0;i<FULL_PARTICLE_COUNT;i++){const band=Math.floor(random()*7),n=normals[band];particles.push({a:random()*TAU,r:.24+band*.115+(random()-.5)*.09,sp:(band%2?-1:1)*(.0016+random()*.003)*(1+band*.12),sz:.5+random()*1.9,al:.15+random()*.6,col:PALETTE[Math.floor(random()*PALETTE.length)],wf:.4+random()*1.6,ph:random()*TAU,streak:random()<.12,cl:random()<.55?Math.floor(random()*NEURAL_NODE_COUNT):-1,cm:.5+random()*.45,B:planeBasis(n[0]+(random()-.5)*.5,n[1]+(random()-.5)*.5,n[2]+(random()-.5)*.5),ps:1,tx:0,ty:0,pz:0});}
  const arcs=Array.from({length:ORBITAL_ARC_COUNT},(_,i)=>{const n=normals[i%7];return {r:.28+random()*.74,a:random()*TAU,len:.15+random()*1.5,w:.5+random()*1.6,sp:(random()<.5?-1:1)*(.001+random()*.004),col:PALETTE[Math.floor(random()*PALETTE.length)],al:.1+random()*.4,B:planeBasis(n[0]+(random()-.5)*.6,n[1]+(random()-.5)*.6,n[2]+(random()-.5)*.6)};});
  const tickRings=Array.from({length:3},(_,i)=>{const th=i*2.1+.7,ph=.5+i*.75;return {B:planeBasis(Math.sin(ph)*Math.cos(th),Math.cos(ph),Math.sin(ph)*Math.sin(th)),r:.5+i*.24,step:1+i};});
  const nodes=Array.from({length:NEURAL_NODE_COUNT},()=>({f1:.11+random()*.22,f2:.09+random()*.24,f3:.08+random()*.2,p1:random()*TAU,p2:random()*TAU,p3:random()*TAU,x:0,y:0,z:0,sx:0,sy:0}));
  return {particles,arcs,tickRings,nodes,flares:[],waves:[],sparks:[],comets:[],rings:[],bolts:[],coreFlash:0,sonarClock:0,lastWave:-1};
}

export function mapVisualState(state:HologramEngineOptions["state"]):HologramVisualState { if(state==="waiting_approval")return "thinking";if(state==="executing")return "speaking";if(state==="offline"||state==="error")return "idle";return state; }
function cap(a:Effect[],key:keyof typeof EFFECT_LIMITS){if(a.length>EFFECT_LIMITS[key])a.splice(0,a.length-EFFECT_LIMITS[key]);}

export function createSaraHologramEngine(canvas:HTMLCanvasElement,initial:HologramEngineOptions):HologramEngine {
  const ctx=canvas.getContext("2d"); if(!ctx) throw new Error("Canvas 2D is required for SARA");
  const system=makeParticleSystem(); let options={...initial},raf=0,running=false,hidden=document.hidden,last=0,t=0,amp=.14,pulse=0;
  const weights={idle:1,listening:0,thinking:0,speaking:0}; const rot={x:-.28,y:0,vx:0,vy:.0016};
  const count=()=>options.reducedMotion?REDUCED_PARTICLE_COUNT:options.mode==="mini"?MINI_PARTICLE_COUNT:FULL_PARTICLE_COUNT;
  const resize=()=>{const r=canvas.getBoundingClientRect(),dpr=Math.min(window.devicePixelRatio||1,2);canvas.width=Math.max(1,Math.floor(r.width*dpr));canvas.height=Math.max(1,Math.floor(r.height*dpr));ctx.setTransform(dpr,0,0,dpr,0,0);};
  const draw=(now:number)=>{
    if(!running)return; if(hidden){raf=0;return;} const dt=Math.min(2,Math.max(.25,(now-last)/16.67||1));last=now;t+=.016*dt;
    const state=mapVisualState(options.state); for(const k of Object.keys(weights) as HologramVisualState[])weights[k]+=((state===k?1:0)-weights[k])*.05*dt;
    const wl=weights.listening,wt=weights.thinking,ws=weights.speaking,offline=options.state==="offline"?.28:1,error=options.state==="error"?.72:1,approval=options.state==="waiting_approval"?.18*(.5+.5*Math.sin(t*1.4)):0;
    pulse=Math.max(pulse,options.speakPulse); pulse*=.88; const target=(.14+wl*.16+wt*.36+ws*.22+pulse*.6+approval)*offline*error;amp+=(target-amp)*.08;
    const motion=options.state==="offline"?.08:options.reducedMotion?.22:1;rot.vy+=(.0016+wt*.0022-rot.vy)*.02;rot.y+=(rot.vy+rot.vx)*motion*dt;rot.x=Math.max(-1.2,Math.min(1.2,rot.x));rot.vx*=.86;
    const cy0=Math.cos(rot.y),sy0=Math.sin(rot.y),cx0=Math.cos(rot.x),sx0=Math.sin(rot.x);const rotate=(x:number,y:number,z:number):[number,number,number]=>{const x1=x*cy0+z*sy0,z1=-x*sy0+z*cy0;return [x1,y*cx0-z1*sx0,y*sx0+z1*cx0];};
    const W=canvas.clientWidth||canvas.getBoundingClientRect().width,H=canvas.clientHeight||canvas.getBoundingClientRect().height,cx=W/2,cy=H/2,R=Math.min(W,H)*.4*(.93+amp*.16),FOV=R*3,CAM=R*3.4;const project=(x:number,y:number,z:number):[number,number,number]=>{const s=FOV/(CAM-z);return[cx+x*s,cy+y*s,s];};
    ctx.globalCompositeOperation="source-over";ctx.clearRect(0,0,W,H);ctx.fillStyle="rgba(3,2,0,.26)";ctx.fillRect(0,0,W,H);ctx.save();ctx.globalCompositeOperation="lighter";
    const coreR=R*.16*(.7+amp*.9+system.coreFlash+wl*.2*Math.sin(t*1.15)+(options.state==="error"?.08*Math.sin(t*5.1):0))*FOV/CAM;system.coreFlash*=.9;const core=()=>{const g=ctx.createRadialGradient(cx,cy,0,cx,cy,coreR*2.4);g.addColorStop(0,"rgba(255,236,196,.9)");g.addColorStop(.35,`rgba(255,158,44,${.28+amp*.4})`);g.addColorStop(1,"rgba(255,122,0,0)");ctx.fillStyle=g;ctx.beginPath();ctx.arc(cx,cy,coreR*2.4,0,TAU);ctx.fill();};
    for(const n of system.nodes){const p=rotate(Math.cos(t*n.f1*2+n.p1)*R*.6,Math.sin(t*n.f2*2+n.p2)*R*.55,Math.sin(t*n.f3*2+n.p3)*R*.6);n.x=p[0];n.y=p[1];n.z=p[2];[n.sx,n.sy]=project(...p);}
    const limit=count(),contract=wl*(.2+.06*Math.sin(t*1.15));for(let i=0;i<limit;i++){const p=system.particles[i];p.a+=p.sp*(1+amp*2)*motion*dt;let rr=p.r*R*(1+Math.sin(t*p.wf+p.ph)*.035*(1+amp*1.6));rr*=1-contract;const ca=Math.cos(p.a)*rr,sa=Math.sin(p.a)*rr,B=p.B,v=rotate(B[0]*ca+B[3]*sa,B[1]*ca+B[4]*sa,B[2]*ca+B[5]*sa),q=project(...v);p.tx=q[0];p.ty=q[1];p.ps=q[2];p.pz=v[2];if(p.cl>=0&&wt>.02){const n=system.nodes[p.cl],k=wt*p.cm;p.tx+=(n.sx-p.tx)*k;p.ty+=(n.sy-p.ty)*k;p.pz+=(n.z-p.pz)*k;}}
    sortParticleRange(system.particles,limit);let split=0;while(split<limit&&system.particles[split].pz<0)drawPart(ctx,system.particles[split++],amp,CAM,R);core();while(split<limit)drawPart(ctx,system.particles[split++],amp,CAM,R);
    const secondary=options.mode==="full"&&!options.reducedMotion,arcLimit=secondary?system.arcs.length:18;for(let ai=0;ai<arcLimit;ai++){const a=system.arcs[ai];a.a+=a.sp*(1+amp*1.4)*motion;ctx.globalAlpha=a.al*(.3+amp*.8);ctx.strokeStyle=a.col;ctx.lineWidth=a.w;ctx.beginPath();for(let k=0;k<=16;k++){const an=a.a+a.len*k/16,ca=Math.cos(an)*a.r*R,sa=Math.sin(an)*a.r*R,B=a.B,q=project(...rotate(B[0]*ca+B[3]*sa,B[1]*ca+B[4]*sa,B[2]*ca+B[5]*sa));if(k)ctx.lineTo(q[0],q[1]);else ctx.moveTo(q[0],q[1]);}ctx.stroke();}
    for(const tr of system.tickRings){ctx.globalAlpha=.1+amp*.22;ctx.strokeStyle="#FF9E2C";ctx.lineWidth=.7;for(let i=0;i<72;i+=tr.step*(secondary?1:3)){const an=t*.05+(i/72)*TAU,ca=Math.cos(an),sa=Math.sin(an),B=tr.B,r1=tr.r*R-3,r2=r1+6,p1=project(...rotate(B[0]*ca*r1+B[3]*sa*r1,B[1]*ca*r1+B[4]*sa*r1,B[2]*ca*r1+B[5]*sa*r1)),p2=project(...rotate(B[0]*ca*r2+B[3]*sa*r2,B[1]*ca*r2+B[4]*sa*r2,B[2]*ca*r2+B[5]*sa*r2));ctx.beginPath();ctx.moveTo(p1[0],p1[1]);ctx.lineTo(p2[0],p2[1]);ctx.stroke();}}
    if(secondary&&Math.random()<amp*.12)system.flares.push({a:Math.random()*TAU,r:R*.4,life:1});if(wl>.2&&Math.random()<wl*.2)system.comets.push({a:Math.random()*TAU,r:R*1.15,life:1});if(wl>.2&&system.sonarClock++%55===0)system.rings.push({r:R*1.05,life:1});if(wt>.03&&secondary&&Math.random()<wt*.06)system.bolts.push({a:Math.floor(Math.random()*13),b:Math.floor(Math.random()*13),life:1});if(ws>.2&&pulse>.35&&t-system.lastWave>.14){system.lastWave=t;system.waves.push({r:R*.18,life:1});for(let i=0;i<8;i++)system.sparks.push({a:Math.random()*TAU,r:R*.17,life:1,col:PALETTE[i%6]});}
    drawEffects(ctx,system,R,cx,cy,wl,wt,ws,amp,t);for(const key of Object.keys(EFFECT_LIMITS) as (keyof typeof EFFECT_LIMITS)[])cap(system[key],key);
    ctx.restore();ctx.globalAlpha=1;raf=requestAnimationFrame(draw);
  };
  const visibility=()=>{hidden=document.hidden;if(!hidden&&running&&!raf){last=0;raf=requestAnimationFrame(draw);}else if(hidden&&raf){cancelAnimationFrame(raf);raf=0;}};document.addEventListener("visibilitychange",visibility);
  return {system,update(next){options={...options,...next};},resize,rotate(dx,dy){if(options.mode!=="full")return;rot.vx+=dx*.006;rot.x=Math.max(-1.2,Math.min(1.2,rot.x-dy*.006));},start(){if(!running){running=true;resize();raf=requestAnimationFrame(draw);}},stop(){running=false;if(raf)cancelAnimationFrame(raf);raf=0;},destroy(){this.stop();document.removeEventListener("visibilitychange",visibility);}};
}

function sortParticleRange(parts:HologramParticle[],length:number){
  const stack:number[]=[0,length-1];
  while(stack.length){const hi=stack.pop()!,lo=stack.pop()!;if(lo>=hi)continue;const pivot=parts[(lo+hi)>>1].pz;let i=lo,j=hi;while(i<=j){while(parts[i].pz<pivot)i++;while(parts[j].pz>pivot)j--;if(i<=j){const p=parts[i];parts[i]=parts[j];parts[j]=p;i++;j--;}}if(lo<j)stack.push(lo,j);if(i<hi)stack.push(i,hi);}
}

function drawPart(ctx:CanvasRenderingContext2D,p:HologramParticle,A:number,CAM:number,R:number){const depth=.4+.6*(p.ps*CAM/(R*3)),sz=p.sz*(.6+p.ps*.9);ctx.globalAlpha=p.al*(.22+A*.85)*depth;ctx.fillStyle=p.col;if(p.streak){ctx.strokeStyle=p.col;ctx.lineWidth=sz*.7;ctx.beginPath();ctx.moveTo(p.tx,p.ty);ctx.lineTo(p.tx-Math.cos(p.a)*6*p.ps,p.ty-Math.sin(p.a)*6*p.ps);ctx.stroke();}else ctx.fillRect(p.tx-sz/2,p.ty-sz/2,sz,sz);}
function drawEffects(ctx:CanvasRenderingContext2D,s:HologramSystem,R:number,cx:number,cy:number,wl:number,wt:number,ws:number,A:number,t:number){
  for(let i=s.flares.length-1;i>=0;i--){const f=s.flares[i],life=(f.life as number)-=.05;if(life<=0){s.flares.splice(i,1);continue;}const a=f.a as number,r=f.r as number;ctx.globalAlpha=life*.7;ctx.strokeStyle="#FFD591";ctx.beginPath();ctx.moveTo(cx+Math.cos(a)*r,cy+Math.sin(a)*r);ctx.lineTo(cx+Math.cos(a)*(r+R*.2*(1-life)),cy+Math.sin(a)*(r+R*.2*(1-life)));ctx.stroke();}
  for(let i=s.comets.length-1;i>=0;i--){const e=s.comets[i];e.r=(e.r as number)-R*.012;e.life=(e.life as number)-.012;if((e.r as number)<R*.16){s.coreFlash+=.3;s.comets.splice(i,1);continue;}ctx.globalAlpha=wl*.8;ctx.strokeStyle="#FFEDC4";ctx.beginPath();ctx.moveTo(cx+Math.cos(e.a as number)*(e.r as number),cy+Math.sin(e.a as number)*(e.r as number));ctx.lineTo(cx+Math.cos(e.a as number)*((e.r as number)+R*.09),cy+Math.sin(e.a as number)*((e.r as number)+R*.09));ctx.stroke();}
  for(let i=s.rings.length-1;i>=0;i--){const e=s.rings[i];e.r=(e.r as number)-R*.0075;e.life=(e.life as number)-.011;if((e.life as number)<=0){s.rings.splice(i,1);continue;}ctx.globalAlpha=(e.life as number)*wl*.4;ctx.strokeStyle="#FFEDC4";ctx.beginPath();ctx.arc(cx,cy,e.r as number,0,TAU);ctx.stroke();}
  if(wt>.03){for(let i=0;i<s.nodes.length;i++){const a=s.nodes[i];ctx.globalAlpha=wt*.45;ctx.fillStyle="#FFD591";ctx.fillRect(a.sx-1.4,a.sy-1.4,2.8,2.8);for(let j=i+1;j<s.nodes.length;j++){const b=s.nodes[j],d=Math.hypot(b.x-a.x,b.y-a.y,b.z-a.z);if(d<R*.62){ctx.globalAlpha=wt*.13*(1-d/(R*.62));ctx.strokeStyle="#FF9E2C";ctx.beginPath();ctx.moveTo(a.sx,a.sy);ctx.lineTo(b.sx,b.sy);ctx.stroke();}}}}
  for(let i=s.bolts.length-1;i>=0;i--){const e=s.bolts[i],a=s.nodes[e.a as number],b=s.nodes[e.b as number];e.life=(e.life as number)-.13;if((e.life as number)<=0){s.bolts.splice(i,1);continue;}ctx.globalAlpha=(e.life as number)*wt;ctx.strokeStyle="#FFEDC4";ctx.beginPath();ctx.moveTo(a.sx,a.sy);ctx.lineTo((a.sx+b.sx)/2+Math.sin(t*31)*8,(a.sy+b.sy)/2+Math.cos(t*27)*8);ctx.lineTo(b.sx,b.sy);ctx.stroke();}
  for(let i=s.waves.length-1;i>=0;i--){const e=s.waves[i];e.r=(e.r as number)+R*.03;e.life=(e.life as number)-.016;if((e.life as number)<=0){s.waves.splice(i,1);continue;}ctx.globalAlpha=(e.life as number)*ws*.42;ctx.strokeStyle="#FFB54D";ctx.beginPath();ctx.arc(cx,cy,e.r as number,0,TAU);ctx.stroke();}
  if(ws>.03)for(let i=0;i<60;i++){const a=i/60*TAU,v=A*(.35+.65*Math.abs(Math.sin(t*6.3+i*1.93)));ctx.globalAlpha=ws*(.22+v*.5);ctx.strokeStyle=PALETTE[i%6];ctx.beginPath();ctx.moveTo(cx+Math.cos(a)*R,cy+Math.sin(a)*R);ctx.lineTo(cx+Math.cos(a)*R*(1+.14*v),cy+Math.sin(a)*R*(1+.14*v));ctx.stroke();}
  for(let i=s.sparks.length-1;i>=0;i--){const e=s.sparks[i];e.r=(e.r as number)+R*.025;e.life=(e.life as number)-.035;if((e.life as number)<=0){s.sparks.splice(i,1);continue;}ctx.globalAlpha=(e.life as number)*.8;ctx.strokeStyle=e.col as string;ctx.beginPath();ctx.moveTo(cx+Math.cos(e.a as number)*(e.r as number),cy+Math.sin(e.a as number)*(e.r as number));ctx.lineTo(cx+Math.cos(e.a as number)*((e.r as number)-R*.04),cy+Math.sin(e.a as number)*((e.r as number)-R*.04));ctx.stroke();}
}
