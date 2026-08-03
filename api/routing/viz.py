"""Self-contained HTML visualisation of representative routes.

One panel per scenario, each showing the whole routing graph in grey, the route drawn
over it, and its score breakdown. No external requests.

  python3 -m api.routing.viz
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone

from . import network
from .bench import LOCATIONS, minutes
from .engine import Engine
from .state import CompletionState

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "results")


def simplify(coords, tol=0.00003):
    if len(coords) <= 2:
        return coords
    out = [coords[0]]
    for c in coords[1:-1]:
        if abs(c[0] - out[-1][0]) > tol or abs(c[1] - out[-1][1]) > tol:
            out.append(c)
    out.append(coords[-1])
    return out


def panel(name, subtitle, route, score, net, state, extra=None):
    covered = route.distinct()
    lines = []
    for idx in covered:
        s = net.segments[idx]
        if not s.coords:
            continue
        kind = ("new" if s.required and not state.is_complete(idx)
                else "already" if s.required else "connector")
        lines.append([kind, simplify(s.coords)])
    start = net.segments[route.seg_seq[0]] if route.seg_seq else None
    sp = start.coords[0] if start and start.coords else None
    return dict(
        name=name, subtitle=subtitle, lines=lines, start=sp,
        miles=round(route.miles(net), 2), minutes=minutes(route.miles(net)),
        new_required=round(score.new_required_miles, 2),
        repeated=round(score.repeated_miles, 2),
        households=score.households,
        corridors=score.corridor_completions,
        dead_ends=score.dead_end_completions,
        quality=score.walk_quality, loop=round(score.loop_shape, 2),
        cohesion=round(score.cohesion, 2), turns=score.turns, uturns=score.uturns,
        efficiency=round(score.efficiency, 2), total=score.total,
        components=score.components, extra=extra or {},
    )


def build(date="2026-08-03"):
    net = network.load(date)
    eng = Engine(net)
    fresh = CompletionState(net)

    panels = []

    # 1. Five nested variants from downtown.
    start = eng.snap(-80.4139, 37.2296)
    for v in eng.variants(start, fresh):
        panels.append(panel(
            f"Downtown · {v['name']}",
            f"target {v['target_miles']} mi · "
            + ("extends " + v["extends"] if v.get("extends") else "base route")
            + ("" if v.get("nested", True) else " · independent (extension could not grow)"),
            v["route"], v["score"], net, fresh,
            extra=dict(nested=v.get("nested", True))))

    # 2. Medium route from each benchmark location.
    for nm, lon, lat in LOCATIONS:
        st = eng.snap(lon, lat)
        r, meta = eng.best_route(st, 3.5, fresh)
        if r is None:
            continue
        panels.append(panel(f"{nm} · Medium", "target 3.5 mi · fresh network",
                            r, r.score, net, fresh,
                            extra=dict(approach_miles=meta.get("approach_miles"))))

    # 3. Late-stage behaviour.
    for label, frac in (("75% complete", 0.75), ("98% complete", 0.98)):
        st_state = CompletionState.at_fraction(net, frac, seed=1)
        st = eng.snap(-80.4139, 37.2296)
        r, meta = eng.best_route(st, 3.5, st_state)
        if r is None:
            continue
        panels.append(panel(
            f"Downtown · {label}",
            f"target 3.5 mi · {st_state.incomplete_miles():.1f} mi still incomplete · "
            f"nearest un-walked {meta.get('nearest_incomplete_miles')} mi away",
            r, r.score, net, st_state,
            extra=dict(nearest_incomplete_miles=meta.get("nearest_incomplete_miles"))))

    # Background: the whole routing graph, heavily decimated.
    bg = [simplify(s.coords, 0.00008) for s in net.segments if s.coords]

    payload = dict(panels=panels, background=bg,
                   network_id=net.network_id,
                   generated_at=datetime.now(timezone.utc).isoformat())
    os.makedirs(OUT, exist_ok=True)
    path = os.path.join(OUT, "routes.html")
    with open(path, "w") as f:
        f.write(TEMPLATE.replace("__DATA__", json.dumps(payload, separators=(",", ":"))))
    print(f"{len(panels)} panels -> {path} ({os.path.getsize(path)/1e6:.1f} MB)")
    return path


TEMPLATE = """<meta charset="utf-8">
<title>Prayer-walk routing prototype — representative routes</title>
<style>
  :root{--bg:#fbfaf8;--fg:#26232a;--mut:#6c6870;--line:#dedae2;--panel:#fff;--ghost:#e6e3ea}
  @media (prefers-color-scheme:dark){:root{--bg:#141317;--fg:#eceaf0;--mut:#9a959f;--line:#2e2b33;--panel:#1c1a20;--ghost:#2a2830}}
  :root[data-theme=dark]{--bg:#141317;--fg:#eceaf0;--mut:#9a959f;--line:#2e2b33;--panel:#1c1a20;--ghost:#2a2830}
  :root[data-theme=light]{--bg:#fbfaf8;--fg:#26232a;--mut:#6c6870;--line:#dedae2;--panel:#fff;--ghost:#e6e3ea}
  *{box-sizing:border-box}
  body{margin:0;background:var(--bg);color:var(--fg);
    font:14px/1.55 ui-sans-serif,system-ui,-apple-system,"Segoe UI",Roboto,sans-serif}
  header{padding:16px 20px;border-bottom:1px solid var(--line)}
  h1{margin:0;font-size:16px;font-weight:650;letter-spacing:-.01em}
  .sub{color:var(--mut);font-size:12.5px;margin-top:4px}
  .legend{display:flex;flex-wrap:wrap;gap:14px;padding:10px 20px;font-size:12px;
    color:var(--mut);border-bottom:1px solid var(--line)}
  .legend i{display:inline-block;width:18px;height:3px;border-radius:2px;margin-right:5px;
    vertical-align:3px}
  .grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(320px,1fr));
    gap:16px;padding:16px}
  .card{border:1px solid var(--line);border-radius:12px;overflow:hidden;background:var(--panel)}
  .card h2{margin:0;padding:11px 13px 3px;font-size:13.5px;font-weight:650}
  .meta{padding:0 13px 9px;color:var(--mut);font-size:11.5px}
  canvas{width:100%;height:230px;display:block;border-top:1px solid var(--line);
    border-bottom:1px solid var(--line)}
  .facts{padding:9px 13px 11px;font-size:12px}
  .row{display:flex;justify-content:space-between;padding:2px 0}
  .row b{font-variant-numeric:tabular-nums;font-weight:600}
  .bars{padding:0 13px 12px}
  .bar{display:flex;align-items:center;gap:6px;font-size:10.5px;color:var(--mut);padding:1px 0}
  .bar span:first-child{width:96px;flex:none}
  .bar .t{flex:1;height:7px;background:var(--ghost);border-radius:4px;position:relative;overflow:hidden}
  .bar .f{position:absolute;top:0;bottom:0;border-radius:4px}
  .bar .v{width:42px;text-align:right;font-variant-numeric:tabular-nums;flex:none}
</style>
<header>
  <h1>Prayer-walk routing prototype — representative routes</h1>
  <div class="sub" id="sub"></div>
</header>
<div class="legend">
  <span><i style="background:#c2185b"></i>newly covered required</span>
  <span><i style="background:#1b5e20"></i>required, already walked</span>
  <span><i style="background:#9c8f2e"></i>connector</span>
  <span><i style="background:#c9c5cf"></i>rest of network</span>
  <span>● start</span>
</div>
<div class="grid" id="grid"></div>
<script>
const D=__DATA__;
document.getElementById('sub').textContent =
  `${D.panels.length} routes · network ${D.network_id} · grey shows the full routing graph`;
const COL={new:'#c2185b',already:'#1b5e20',connector:'#9c8f2e'};
const grid=document.getElementById('grid');

D.panels.forEach((p,i)=>{
  const c=document.createElement('div'); c.className='card';
  const comp=Object.entries(p.components).filter(([,v])=>Math.abs(v)>0.5)
    .sort((a,b)=>Math.abs(b[1])-Math.abs(a[1])).slice(0,7);
  const mx=Math.max(...comp.map(([,v])=>Math.abs(v)),1);
  c.innerHTML=`<h2>${p.name}</h2><div class="meta">${p.subtitle}</div>
    <canvas id="cv${i}"></canvas>
    <div class="facts">
      <div class="row"><span>Distance / time</span><b>${p.miles} mi · ${p.minutes} min</b></div>
      <div class="row"><span>New required mileage</span><b>${p.new_required} mi</b></div>
      <div class="row"><span>Repeated mileage</span><b>${p.repeated} mi</b></div>
      <div class="row"><span>Households</span><b>${p.households.toLocaleString()}</b></div>
      <div class="row"><span>Corridors / dead ends done</span><b>${p.corridors} / ${p.dead_ends}</b></div>
      <div class="row"><span>Efficiency · loop · cohesion</span><b>${p.efficiency} · ${p.loop} · ${p.cohesion}</b></div>
      <div class="row"><span>Turns / U-turns</span><b>${p.turns} / ${p.uturns}</b></div>
      <div class="row"><span>Walk quality · score</span><b>${p.quality} · ${Math.round(p.total)}</b></div>
    </div>
    <div class="bars">${comp.map(([k,v])=>`<div class="bar"><span>${k.replace(/_/g,' ')}</span>
      <span class="t"><span class="f" style="background:${v>=0?'#2e7d32':'#c62828'};
        ${v>=0?'left:50%':'right:50%'};width:${Math.abs(v)/mx*50}%"></span></span>
      <span class="v">${Math.round(v)}</span></div>`).join('')}</div>`;
  grid.appendChild(c);
});

function draw(){
 D.panels.forEach((p,i)=>{
  const cv=document.getElementById('cv'+i); if(!cv) return;
  const cx=cv.getContext('2d'),dpr=Math.min(devicePixelRatio||1,2);
  const W=cv.clientWidth,H=cv.clientHeight;
  cv.width=W*dpr; cv.height=H*dpr; cx.setTransform(dpr,0,0,dpr,0,0); cx.clearRect(0,0,W,H);
  let x0=1e9,y0=1e9,x1=-1e9,y1=-1e9;
  for(const [,cs] of p.lines) for(const [x,y] of cs){
    if(x<x0)x0=x; if(x>x1)x1=x; if(y<y0)y0=y; if(y>y1)y1=y;}
  if(x0>x1) return;
  const padx=(x1-x0)*0.35+0.002, pady=(y1-y0)*0.35+0.002;
  x0-=padx;x1+=padx;y0-=pady;y1+=pady;
  const KX=Math.cos((y0+y1)/2*Math.PI/180),w=(x1-x0)*KX,h=y1-y0;
  const s=Math.min(W/w,H/h),bx=(W-w*s)/2,by=(H-h*s)/2;
  const px=x=>bx+(x-x0)*KX*s, py=y=>by+(y1-y)*s;
  cx.lineJoin=cx.lineCap='round';
  // background network
  cx.strokeStyle=getComputedStyle(document.body).getPropertyValue('--ghost');
  cx.lineWidth=1; cx.beginPath();
  for(const cs of D.background){
    let vis=false;
    for(const [x,y] of cs){ if(x>x0&&x<x1&&y>y0&&y<y1){vis=true;break;} }
    if(!vis) continue;
    cs.forEach(([x,y],k)=>k?cx.lineTo(px(x),py(y)):cx.moveTo(px(x),py(y)));
  }
  cx.stroke();
  for(const kind of ['connector','already','new']){
    cx.strokeStyle=COL[kind]; cx.lineWidth=kind==='new'?2.6:1.8;
    cx.globalAlpha=kind==='connector'?.75:1; cx.beginPath();
    for(const [k,cs] of p.lines){ if(k!==kind) continue;
      cs.forEach(([x,y],j)=>j?cx.lineTo(px(x),py(y)):cx.moveTo(px(x),py(y))); }
    cx.stroke();
  }
  cx.globalAlpha=1;
  if(p.start){ cx.fillStyle='#111'; cx.strokeStyle='#fff'; cx.lineWidth=2;
    cx.beginPath(); cx.arc(px(p.start[0]),py(p.start[1]),4.5,0,7); cx.fill(); cx.stroke(); }
 });
}
addEventListener('resize',draw);
new MutationObserver(draw).observe(document.documentElement,{attributes:true,attributeFilter:['data-theme']});
draw();
</script>
"""

if __name__ == "__main__":
    build()
