"""Self-contained HTML map of the canonical network, for human review.

No external requests: geometry is embedded, projected to screen space at build time,
and drawn to a canvas. Opens from disk with no server and no API key.

Usage: python3 -m pipeline.build.map_export [--date YYYY-MM-DD]
"""
import argparse
import json
import os
from collections import defaultdict
from datetime import datetime, timezone

OUT_ROOT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "out")
M_PER_MILE = 1609.344

LAYERS = [
    ("required_street", "REQUIRED · street", "#1b5e20"),
    ("required_trail", "REQUIRED · trail", "#00897b"),
    ("connector", "OPTIONAL_CONNECTOR", "#9c8f2e"),
    ("derived", "Derived connector (synthetic)", "#d81b60"),
    ("excluded", "EXCLUDED", "#b0aeb4"),
    # Only decisions that move the denominator. Connector-vs-connector review is real
    # work but cannot make coverage wrong, so highlighting it here would bury the
    # handful of segments that actually need a human ruling.
    ("review", "Review · affects coverage", "#e65100"),
]


def affects_coverage(p):
    return (p["role"] in ("REQUIRED", "EXCLUDED")
            and p["role_status"] in ("NEEDS_REVIEW", "PROVISIONAL"))


def bucket(p):
    if p["source"]["dataset"] == "DERIVED":
        return "derived"
    if p["role"] == "EXCLUDED":
        return "excluded"
    if p["role"] == "REQUIRED":
        return "required_trail" if p["segment_type"] == "TRAIL" else "required_street"
    return "connector"


def simplify(coords, tol=0.00002):
    """Cheap perpendicular-distance decimation — visual only, never measured."""
    if len(coords) <= 2:
        return coords
    out = [coords[0]]
    for c in coords[1:-1]:
        lx, ly = out[-1]
        if abs(c[0] - lx) > tol or abs(c[1] - ly) > tol:
            out.append(c)
    out.append(coords[-1])
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", default=datetime.now(timezone.utc).strftime("%Y-%m-%d"))
    args = ap.parse_args()
    outdir = os.path.join(OUT_ROOT, args.date)

    with open(os.path.join(outdir, "segments.geojson")) as f:
        segs = json.load(f)["features"]
    with open(os.path.join(outdir, "build-report.json")) as f:
        report = json.load(f)
    boundary_path = os.path.join(os.path.dirname(OUT_ROOT), "snapshots", "boundary",
                                 f"{args.date}.geojson")
    with open(boundary_path) as f:
        boundary = json.load(f)["features"][0]["geometry"]

    lines, stats = [], defaultdict(lambda: {"n": 0, "mi": 0.0})
    for f_ in segs:
        p = f_["properties"]
        g = f_["geometry"]
        if g["type"] != "LineString":
            continue
        b = bucket(p)
        needs = affects_coverage(p)
        stats[b]["n"] += 1
        stats[b]["mi"] += float(p["length_m"]) / M_PER_MILE
        if needs:
            stats["review"]["n"] += 1
            stats["review"]["mi"] += float(p["length_m"]) / M_PER_MILE
        lines.append([
            b, 1 if needs else 0,
            [[round(x, 6), round(y, 6)] for x, y in simplify(g["coordinates"])],
            p["id"], p["display_name"] or "", p["segment_type"], p["role"],
            p["role_status"], round(float(p["length_m"]) / M_PER_MILE, 3),
            p.get("access_type") or "", int(p.get("estimated_household_count") or 0),
        ])

    rings = boundary["coordinates"] if boundary["type"] == "Polygon" else boundary["coordinates"][0]
    payload = {
        "lines": lines,
        "boundary": [[[round(x, 6), round(y, 6)] for x, y in r] for r in rings],
        "layers": LAYERS,
        "stats": {k: {"n": v["n"], "mi": round(v["mi"], 2)} for k, v in stats.items()},
        "meta": {
            "snapshot_date": report["snapshot_date"],
            "built_at": report["built_at"],
            "eligible_miles": report["totals"]["ELIGIBLE_MILEAGE"],
            "households": report["households"]["estimated_occupied_households"],
            "held": report["households"]["estimated_housing_units"]
                    - report["households"]["housing_units_associated_to_network"],
        },
    }

    html = TEMPLATE.replace("__PAYLOAD__", json.dumps(payload, separators=(",", ":")))
    path = os.path.join(outdir, "network-map.html")
    with open(path, "w") as f:
        f.write(html)
    print(f"{len(lines)} segments -> {path} ({os.path.getsize(path)/1e6:.1f} MB)")


TEMPLATE = """<title>Blacksburg canonical walking network — review map</title>
<style>
  :root{--bg:#fbfaf8;--fg:#26232a;--mut:#6c6870;--line:#dedae2;--panel:#fff}
  @media (prefers-color-scheme:dark){:root{--bg:#141317;--fg:#eceaf0;--mut:#9a959f;--line:#2e2b33;--panel:#1c1a20}}
  :root[data-theme=dark]{--bg:#141317;--fg:#eceaf0;--mut:#9a959f;--line:#2e2b33;--panel:#1c1a20}
  :root[data-theme=light]{--bg:#fbfaf8;--fg:#26232a;--mut:#6c6870;--line:#dedae2;--panel:#fff}
  *{box-sizing:border-box}
  body{margin:0;background:var(--bg);color:var(--fg);
    font:14px/1.5 ui-sans-serif,system-ui,-apple-system,"Segoe UI",Roboto,sans-serif}
  header{padding:14px 18px;border-bottom:1px solid var(--line)}
  h1{margin:0;font-size:16px;font-weight:650;letter-spacing:-.01em}
  .sub{color:var(--mut);font-size:12.5px;margin-top:3px}
  .wrap{display:grid;grid-template-columns:minmax(0,1fr) 268px;gap:0;height:calc(100vh - 62px)}
  @media(max-width:820px){.wrap{grid-template-columns:1fr;height:auto}
    #cv{height:66vh}aside{border-left:0;border-top:1px solid var(--line)}}
  #cv{width:100%;height:100%;display:block;cursor:crosshair;touch-action:none}
  aside{border-left:1px solid var(--line);padding:14px;overflow:auto;background:var(--panel)}
  .k{display:flex;align-items:center;gap:8px;padding:5px 0;cursor:pointer;user-select:none}
  .k input{margin:0;accent-color:currentColor}
  .sw{width:22px;height:4px;border-radius:2px;flex:none}
  .nm{flex:1;font-size:12.5px}
  .ct{color:var(--mut);font-size:11.5px;font-variant-numeric:tabular-nums}
  h2{font-size:11px;text-transform:uppercase;letter-spacing:.07em;color:var(--mut);
    margin:16px 0 6px;font-weight:600}
  .stat{display:flex;justify-content:space-between;padding:3px 0;font-size:12.5px}
  .stat b{font-variant-numeric:tabular-nums;font-weight:600}
  #tip{position:fixed;pointer-events:none;background:var(--panel);border:1px solid var(--line);
    border-radius:8px;padding:8px 10px;font-size:12px;max-width:290px;opacity:0;
    box-shadow:0 6px 24px #0002;transition:opacity .1s;z-index:9}
  #tip .t{font-weight:650;margin-bottom:3px}
  #tip .r{color:var(--mut);font-size:11.5px}
  button{font:inherit;font-size:12px;padding:5px 9px;border:1px solid var(--line);
    border-radius:7px;background:transparent;color:var(--fg);cursor:pointer}
  button:hover{background:var(--line)}
  .note{color:var(--mut);font-size:11.5px;margin-top:12px;padding-top:10px;
    border-top:1px solid var(--line)}
</style>
<header>
  <h1>Blacksburg canonical walking network — review map</h1>
  <div class="sub" id="sub"></div>
</header>
<div class="wrap">
  <canvas id="cv"></canvas>
  <aside>
    <h2>Layers</h2><div id="keys"></div>
    <h2>Totals</h2><div id="stats"></div>
    <div style="margin-top:14px;display:flex;gap:6px">
      <button id="reset">Reset view</button><button id="only">Review only</button>
    </div>
    <div class="note">Scroll to zoom, drag to pan, hover a segment for detail.
      Geometry is decimated for drawing; all mileage comes from the full-precision
      build in EPSG:6594.</div>
  </aside>
</div>
<div id="tip"></div>
<script>
const D=__PAYLOAD__;
const cv=document.getElementById('cv'),cx=cv.getContext('2d'),tip=document.getElementById('tip');
const on={};D.layers.forEach(([k])=>on[k]=true);
let reviewOnly=false;

let bb={x0:1e9,y0:1e9,x1:-1e9,y1:-1e9};
for(const r of D.boundary)for(const[x,y]of r){
  if(x<bb.x0)bb.x0=x;if(x>bb.x1)bb.x1=x;if(y<bb.y0)bb.y0=y;if(y>bb.y1)bb.y1=y;}
const LAT=(bb.y0+bb.y1)/2, KX=Math.cos(LAT*Math.PI/180);
let view={s:1,tx:0,ty:0},W=0,H=0,base=1,bx=0,by=0;

function fit(){
  const dpr=Math.min(devicePixelRatio||1,2);
  W=cv.clientWidth;H=cv.clientHeight;
  cv.width=W*dpr;cv.height=H*dpr;cx.setTransform(dpr,0,0,dpr,0,0);
  const w=(bb.x1-bb.x0)*KX,h=bb.y1-bb.y0;
  base=Math.min(W/w,H/h)*0.94;
  bx=(W-w*base)/2;by=(H-h*base)/2;
}
const px=(x)=>bx+((x-bb.x0)*KX)*base*view.s+view.tx;
const py=(y)=>by+((bb.y1-y))*base*view.s+view.ty;

function draw(){
  cx.clearRect(0,0,W,H);
  cx.lineJoin=cx.lineCap='round';
  // boundary
  cx.beginPath();
  for(const r of D.boundary){r.forEach(([x,y],i)=>i?cx.lineTo(px(x),py(y)):cx.moveTo(px(x),py(y)));cx.closePath();}
  cx.fillStyle=getComputedStyle(document.body).getPropertyValue('--panel');
  cx.globalAlpha=.5;cx.fill();cx.globalAlpha=1;
  cx.strokeStyle=getComputedStyle(document.body).getPropertyValue('--line');
  cx.lineWidth=1.5;cx.stroke();

  const order=['excluded','connector','derived','required_trail','required_street'];
  const col=Object.fromEntries(D.layers.map(([k,,c])=>[k,c]));
  for(const b of order){
    if(!on[b])continue;
    cx.strokeStyle=col[b];
    cx.lineWidth=(b.startsWith('required')?1.9:1.2)*Math.min(2.4,Math.max(.65,view.s*.85));
    cx.globalAlpha=b==='excluded'?.5:.92;
    cx.beginPath();
    for(const L of D.lines){
      if(L[0]!==b)continue;
      if(reviewOnly&&!L[1])continue;
      const c=L[2];
      for(let i=0;i<c.length;i++){const X=px(c[i][0]),Y=py(c[i][1]);i?cx.lineTo(X,Y):cx.moveTo(X,Y);}
    }
    cx.stroke();
  }
  // review highlight on top
  if(on.review){
    cx.strokeStyle=col.review;cx.globalAlpha=.95;
    cx.lineWidth=2.4*Math.min(2.4,Math.max(.7,view.s*.85));
    cx.beginPath();
    for(const L of D.lines){
      if(!L[1]||!on[L[0]])continue;
      const c=L[2];
      for(let i=0;i<c.length;i++){const X=px(c[i][0]),Y=py(c[i][1]);i?cx.lineTo(X,Y):cx.moveTo(X,Y);}
    }
    cx.stroke();
  }
  cx.globalAlpha=1;
}

function hit(mx,my){
  let best=null,bd=9;
  for(const L of D.lines){
    if(!on[L[0]]||(reviewOnly&&!L[1]))continue;
    const c=L[2];
    for(let i=0;i<c.length-1;i++){
      const x1=px(c[i][0]),y1=py(c[i][1]),x2=px(c[i+1][0]),y2=py(c[i+1][1]);
      const dx=x2-x1,dy=y2-y1,L2=dx*dx+dy*dy;
      let t=L2?((mx-x1)*dx+(my-y1)*dy)/L2:0;t=Math.max(0,Math.min(1,t));
      const d=Math.hypot(mx-(x1+t*dx),my-(y1+t*dy));
      if(d<bd){bd=d;best=L;}
    }
  }
  return best;
}

cv.addEventListener('mousemove',e=>{
  const r=cv.getBoundingClientRect(),h=hit(e.clientX-r.left,e.clientY-r.top);
  if(!h){tip.style.opacity=0;return;}
  tip.innerHTML=`<div class="t">${h[4]||'(unnamed)'}</div>
    <div class="r">${h[3]} · ${h[5]} · ${h[9]||'—'}</div>
    <div class="r">${h[6]} · ${h[7]}</div>
    <div class="r">${h[8]} mi · ${h[10]} household${h[10]===1?'':'s'}</div>`;
  tip.style.opacity=1;
  tip.style.left=Math.min(e.clientX+14,innerWidth-300)+'px';
  tip.style.top=(e.clientY+14)+'px';
});
cv.addEventListener('mouseleave',()=>tip.style.opacity=0);
cv.addEventListener('wheel',e=>{
  e.preventDefault();
  const r=cv.getBoundingClientRect(),mx=e.clientX-r.left,my=e.clientY-r.top;
  const k=Math.exp(-e.deltaY*0.0016),ns=Math.max(1,Math.min(90,view.s*k)),f=ns/view.s;
  view.tx=mx-(mx-view.tx)*f;view.ty=my-(my-view.ty)*f;view.s=ns;draw();
},{passive:false});
let drag=null;
cv.addEventListener('pointerdown',e=>{drag={x:e.clientX,y:e.clientY,tx:view.tx,ty:view.ty};cv.setPointerCapture(e.pointerId);});
cv.addEventListener('pointermove',e=>{if(!drag)return;view.tx=drag.tx+e.clientX-drag.x;view.ty=drag.ty+e.clientY-drag.y;draw();});
addEventListener('pointerup',()=>drag=null);

document.getElementById('keys').innerHTML=D.layers.map(([k,n,c])=>{
  const s=D.stats[k]||{n:0,mi:0};
  return `<label class="k"><input type=checkbox data-k="${k}" checked>
    <span class="sw" style="background:${c}"></span>
    <span class="nm">${n}</span><span class="ct">${s.n} · ${s.mi} mi</span></label>`;}).join('');
document.querySelectorAll('#keys input').forEach(i=>i.onchange=()=>{on[i.dataset.k]=i.checked;draw();});

const m=D.meta;
document.getElementById('sub').textContent=
  `snapshot ${m.snapshot_date} · ${D.lines.length} segments · ${m.eligible_miles} mi required · `+
  `${m.households.toLocaleString()} estimated households · ${m.held.toLocaleString()} units held for review`;
document.getElementById('stats').innerHTML=
  `<div class="stat"><span>Required mileage</span><b>${m.eligible_miles} mi</b></div>
   <div class="stat"><span>Segments</span><b>${D.lines.length}</b></div>
   <div class="stat"><span>Est. households</span><b>${m.households.toLocaleString()}</b></div>
   <div class="stat"><span>Units held</span><b>${m.held.toLocaleString()}</b></div>`;
document.getElementById('reset').onclick=()=>{view={s:1,tx:0,ty:0};draw();};
document.getElementById('only').onclick=e=>{reviewOnly=!reviewOnly;
  e.target.textContent=reviewOnly?'Show all':'Review only';draw();};
addEventListener('resize',()=>{fit();draw();});
new MutationObserver(draw).observe(document.documentElement,{attributes:true,attributeFilter:['data-theme']});
fit();draw();
</script>
"""

if __name__ == "__main__":
    main()
