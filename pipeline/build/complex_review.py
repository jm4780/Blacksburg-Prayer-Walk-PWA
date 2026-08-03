"""Focused review of the three calibration complexes, plus a map to look at them on.

Terrace View, Hunters Ridge and The Mill were named for review. Two of them pass the
automatic test and one fails it, which makes them the calibration set: whichever way a
human rules on these three tells us how to tune the rule for the other 55.

Produces:
  review/complex-calibration.json    per-complex facts and a recommendation
  complex-review-map.html            three focused panels, self-contained

Usage: python3 -m pipeline.build.complex_review [--date YYYY-MM-DD]
"""
import argparse
import json
import os
from collections import Counter, defaultdict
from datetime import datetime, timezone

from shapely.geometry import MultiPoint, shape
from shapely.ops import transform
from shapely.strtree import STRtree

from . import curation, geo, households as hh
from .names import address_name

OUT_ROOT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "out")
M_PER_MILE = 1609.344

TARGETS = ["Terrace View", "Hunters Ridge", "The Mill"]
# How far around the site footprint to pull context geometry for the map.
CONTEXT_BUFFER_M = 90.0


def load_segments(date):
    with open(os.path.join(OUT_ROOT, date, "segments.geojson")) as f:
        feats = json.load(f)["features"]
    segs = []
    for f in feats:
        p = dict(f["properties"])
        p["_geom"] = transform(geo._to_proj, shape(f["geometry"]))
        p["_wgs"] = f["geometry"]
        segs.append(p)
    return segs


def profile(date):
    segs = load_segments(date)
    address = geo.load("address", date)
    hs, _ = hh.build_households(address, address_name, [])

    eligible = [s for s in segs
                if s["role"] in ("REQUIRED", "OPTIONAL_CONNECTOR") and s["walkable"]]
    elig_geoms = [s["_geom"] for s in eligible]
    elig_tree = STRtree(elig_geoms)
    all_geoms = [s["_geom"] for s in segs]
    all_tree = STRtree(all_geoms)

    by_place = defaultdict(list)
    for h in hs:
        if h["place_name"]:
            by_place[h["place_name"]].append(h)

    out = []
    for target in TARGETS:
        matches = [p for p in by_place if target.lower() in p.lower()]
        for place in matches:
            members = by_place[place]
            pts = [h["point"] for h in members]
            hull = MultiPoint(pts).convex_hull
            if hull.geom_type in ("Point", "LineString"):
                hull = hull.buffer(20.0)
            hull = hull.buffer(15.0)
            context = hull.buffer(CONTEXT_BUFFER_M)

            # Everything in and around the site.
            inside, nearby = [], []
            for k in all_tree.query(context):
                s = segs[k]
                mid = s["_geom"].interpolate(0.5, normalized=True)
                (inside if hull.contains(mid) else nearby).append(s)

            def summarize(rows):
                agg = defaultdict(lambda: {"n": 0, "m": 0.0, "names": set()})
                for s in rows:
                    key = (s["segment_type"], s["role"], s.get("access_type"))
                    agg[key]["n"] += 1
                    agg[key]["m"] += s["_geom"].length
                    if s["display_name"]:
                        agg[key]["names"].add(s["display_name"])
                return [dict(segment_type=k[0], role=k[1], access_type=k[2],
                             segments=v["n"], miles=round(v["m"] / M_PER_MILE, 4),
                             names=sorted(v["names"])[:8])
                        for k, v in sorted(agg.items(), key=lambda x: -x[1]["m"])]

            # Distance of every unit to the nearest eligible segment.
            dists = sorted(elig_geoms[elig_tree.nearest(h["point"])].distance(h["point"])
                           for h in members)
            beyond = sum(1 for d in dists if d > curation.ASSOCIATION_CAP_M)
            internal_m = sum(s["_geom"].length for s in inside
                             if s["role"] in ("REQUIRED", "OPTIONAL_CONNECTOR")
                             and s["walkable"])

            prof = dict(place_name=place, units=len(members),
                        internal_network_m=internal_m, units_beyond_cap=beyond,
                        share_beyond_cap=round(beyond / len(members), 3),
                        footprint_area_m2=hull.area)
            disposition, hold_mode, reasons, flags = hh.complex_disposition(prof)
            v1_status, _, trigger = hh.complex_status(prof)

            out.append(dict(
                place_name=place,
                units=len(members),
                footprint_acres=round(hull.area / 4046.86, 2),
                inside_site=summarize(inside),
                frontage_context=summarize(nearby),
                internal_eligible_miles=round(internal_m / M_PER_MILE, 4),
                private_miles_inside=round(sum(
                    s["_geom"].length for s in inside if s.get("access_type") == "PRIVATE"
                ) / M_PER_MILE, 4),
                public_miles_inside=round(sum(
                    s["_geom"].length for s in inside if s.get("access_type") == "PUBLIC"
                ) / M_PER_MILE, 4),
                pedestrian_miles_inside=round(sum(
                    s["_geom"].length for s in inside
                    if s["segment_type"] in ("TRAIL", "PEDESTRIAN_CONNECTOR")
                ) / M_PER_MILE, 4),
                distance_to_eligible=dict(
                    median_m=round(dists[len(dists) // 2], 1),
                    p90_m=round(dists[int(0.9 * len(dists))], 1),
                    max_m=round(dists[-1], 1),
                    within_25m=sum(1 for d in dists if d <= 25),
                    within_75m=sum(1 for d in dists if d <= 75),
                    within_150m=sum(1 for d in dists if d <= 150),
                ),
                units_beyond_cap=beyond,
                share_beyond_cap=round(beyond / len(members), 3),
                disposition=disposition,
                hold_mode=hold_mode,
                v1_status=v1_status,
                trigger=trigger,
                reasons=reasons,
                flags=flags,
                units_currently_associated=(0 if hold_mode == "ALL"
                                            else len(members) - beyond),
                units_currently_held=(len(members) if hold_mode == "ALL"
                                      else beyond if hold_mode == "BEYOND_CAP_ONLY" else 0),
                recommendation=recommend(place, len(members), internal_m, beyond,
                                         len(members), hull.area, inside),
                _hull=hull, _context=context, _inside=inside, _nearby=nearby,
                _points=pts,
            ))
    return out, segs


def recommend(place, units, internal_m, beyond, total, area_m2, inside):
    """A specific recommendation for this complex, not a generic bucket."""
    ped_m = sum(s["_geom"].length for s in inside
                if s["segment_type"] in ("TRAIL", "PEDESTRIAN_CONNECTOR"))
    priv_m = sum(s["_geom"].length for s in inside if s.get("access_type") == "PRIVATE")
    share = beyond / total if total else 0

    if internal_m < 25:
        return dict(
            action="ADD_AUTHORITATIVE_PEDESTRIAN_NETWORK",
            interim="EXCLUDE_FROM_ESTIMATE",
            detail=(f"{units} units and no walkable network inside the site at all. "
                    f"Nothing a walker on the frontage street passes. Source or "
                    f"digitise the internal walkways before counting these units."))
    if priv_m > 0 and ped_m < 50:
        return dict(
            action="ASSOCIATE_WITH_FRONTAGE_STREETS",
            interim="PARTIAL_COUNT",
            detail=(f"Internal circulation exists but is private drive "
                    f"({priv_m / M_PER_MILE:.2f} mi) with almost no pedestrian "
                    f"geometry. Private drives are EXCLUDED, so they carry no "
                    f"obligation — but units fronting them are genuinely passed from "
                    f"the public street. Assign by frontage, by hand."))
    if share > 0.10:
        return dict(
            action="ASSOCIATE_WITH_FRONTAGE_STREETS",
            interim="PARTIAL_COUNT",
            detail=(f"{beyond} of {total} units ({share:.0%}) sit beyond the 75 m cap. "
                    f"The site has real internal network "
                    f"({internal_m / M_PER_MILE:.2f} mi), so most units associate "
                    f"honestly; hand-assign the tail rather than holding the whole site."))
    return dict(
        action="ACCEPT_AUTOMATIC_ASSOCIATION",
        interim="COUNT",
        detail=(f"{internal_m / M_PER_MILE:.2f} mi of internal walkable network and "
                f"only {beyond} of {total} units ({share:.0%}) beyond the cap. The "
                f"automatic association is honest here."))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", default=datetime.now(timezone.utc).strftime("%Y-%m-%d"))
    args = ap.parse_args()
    geo.assert_metric()
    date = args.date

    profiles, segs = profile(date)

    report = dict(
        generated_at=datetime.now(timezone.utc).isoformat(),
        snapshot_date=date,
        association_cap_m=curation.ASSOCIATION_CAP_M,
        complexes=[{k: v for k, v in p.items() if not k.startswith("_")} for p in profiles],
    )
    path = os.path.join(OUT_ROOT, date, "review", "complex-calibration.json")
    with open(path, "w") as f:
        json.dump(report, f, indent=2, default=str)

    write_map(date, profiles)

    for p in profiles:
        print(f"\n=== {p['place_name']} — {p['units']} units, {p['footprint_acres']} acres ===")
        print(f"  internal eligible {p['internal_eligible_miles']:.3f} mi  "
              f"(public {p['public_miles_inside']:.3f} / private {p['private_miles_inside']:.3f} / "
              f"pedestrian {p['pedestrian_miles_inside']:.3f})")
        d = p["distance_to_eligible"]
        print(f"  distance to eligible: median {d['median_m']} m, p90 {d['p90_m']} m, "
              f"max {d['max_m']} m")
        print(f"  within 25 m {d['within_25m']} | 75 m {d['within_75m']} | 150 m {d['within_150m']}")
        print(f"  beyond cap {p['units_beyond_cap']} ({p['share_beyond_cap']:.0%})")
        print(f"  disposition: {p['disposition']} hold={p['hold_mode']} "
              f"(v1 said {p['v1_status']}, trigger {p['trigger']})")
        print(f"  units associated {p['units_currently_associated']} / held {p['units_currently_held']}")
        print(f"  inside site:")
        for row in p["inside_site"][:6]:
            print(f"     {row['segment_type']:<22}{row['role']:<20}{str(row['access_type']):<9}"
                  f"{row['segments']:>3} segs {row['miles']:>7.3f} mi  {', '.join(row['names'][:3])}")
        print(f"  RECOMMEND: {p['recommendation']['action']} "
              f"(interim {p['recommendation']['interim']})")
        print(f"     {p['recommendation']['detail']}")
    print(f"\n-> {path}")


def write_map(date, profiles):
    panels = []
    for p in profiles:
        ctx = p["_context"]
        minx, miny, maxx, maxy = ctx.bounds
        lines = []
        for s in p["_inside"] + p["_nearby"]:
            g = s["_wgs"]
            if g["type"] != "LineString":
                continue
            lines.append([
                s["role"], s["segment_type"], s.get("access_type") or "",
                s["display_name"] or "", round(s["_geom"].length / M_PER_MILE, 4),
                [[round(x, 6), round(y, 6)] for x, y in g["coordinates"]],
            ])
        pts = [[round(x, 6), round(y, 6)] for x, y in
               ((geo._to_wgs(pt.x, pt.y)) for pt in p["_points"])]
        hull_wgs = transform(geo._to_wgs, p["_hull"])
        panels.append(dict(
            name=p["place_name"], units=p["units"], acres=p["footprint_acres"],
            lines=lines, points=pts,
            hull=[[round(x, 6), round(y, 6)] for x, y in hull_wgs.exterior.coords],
            internal=p["internal_eligible_miles"], beyond=p["units_beyond_cap"],
            share=p["share_beyond_cap"], status=p["hold_mode"],
            trigger=p["trigger"], associated=p["units_currently_associated"], held=p["units_currently_held"], action=p["recommendation"]["action"],
            detail=p["recommendation"]["detail"],
            d=p["distance_to_eligible"],
        ))
    html = MAP_TEMPLATE.replace("__PANELS__", json.dumps(panels, separators=(",", ":")))
    path = os.path.join(OUT_ROOT, date, "complex-review-map.html")
    with open(path, "w") as f:
        f.write(html)
    print(f"map -> {path} ({os.path.getsize(path)/1024:.0f} KB)")


MAP_TEMPLATE = """<meta charset="utf-8">
<title>Apartment-complex calibration — Terrace View, Hunters Ridge, The Mill</title>
<style>
  :root{--bg:#fbfaf8;--fg:#26232a;--mut:#6c6870;--line:#dedae2;--panel:#fff}
  @media (prefers-color-scheme:dark){:root{--bg:#141317;--fg:#eceaf0;--mut:#9a959f;--line:#2e2b33;--panel:#1c1a20}}
  :root[data-theme=dark]{--bg:#141317;--fg:#eceaf0;--mut:#9a959f;--line:#2e2b33;--panel:#1c1a20}
  :root[data-theme=light]{--bg:#fbfaf8;--fg:#26232a;--mut:#6c6870;--line:#dedae2;--panel:#fff}
  *{box-sizing:border-box}
  body{margin:0;background:var(--bg);color:var(--fg);
    font:14px/1.55 ui-sans-serif,system-ui,-apple-system,"Segoe UI",Roboto,sans-serif}
  header{padding:16px 20px;border-bottom:1px solid var(--line)}
  h1{margin:0;font-size:16px;font-weight:650;letter-spacing:-.01em}
  .sub{color:var(--mut);font-size:12.5px;margin-top:4px;max-width:78ch}
  .grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(340px,1fr));gap:18px;padding:18px}
  .card{border:1px solid var(--line);border-radius:12px;overflow:hidden;background:var(--panel)}
  .card h2{margin:0;padding:12px 14px 8px;font-size:14.5px;font-weight:650}
  .meta{padding:0 14px 10px;color:var(--mut);font-size:12px}
  canvas{width:100%;height:250px;display:block;border-top:1px solid var(--line);
    border-bottom:1px solid var(--line)}
  .facts{padding:11px 14px;font-size:12.5px}
  .row{display:flex;justify-content:space-between;gap:10px;padding:2.5px 0}
  .row b{font-variant-numeric:tabular-nums;font-weight:600}
  .rec{margin:0 14px 13px;padding:10px 11px;border-radius:9px;font-size:12.5px;
    background:color-mix(in srgb,var(--fg) 5%,transparent)}
  .rec .a{font-weight:650;letter-spacing:.01em}
  .tag{display:inline-block;padding:1px 7px;border-radius:20px;font-size:11px;
    border:1px solid var(--line);margin-left:6px;vertical-align:1px}
  .legend{display:flex;flex-wrap:wrap;gap:12px;padding:0 20px 16px;font-size:12px;color:var(--mut)}
  .legend i{display:inline-block;width:16px;height:3px;border-radius:2px;margin-right:5px;
    vertical-align:3px}
  .dot{display:inline-block;width:6px;height:6px;border-radius:50%;background:#c2185b;
    margin-right:5px;vertical-align:1px}
</style>
<header>
  <h1>Apartment-complex calibration</h1>
  <div class="sub">Three complexes named for review. Two pass the automatic test and one
    fails it — how these are ruled on tunes the rule for the other 55 unresolved
    complexes. Each panel shows every residential unit as a dot, the site footprint,
    and the network in and around it.</div>
</header>
<div class="legend">
  <span><i style="background:#1b5e20"></i>REQUIRED street</span>
  <span><i style="background:#00897b"></i>REQUIRED trail</span>
  <span><i style="background:#9c8f2e"></i>connector</span>
  <span><i style="background:#b0aeb4"></i>EXCLUDED (private drive)</span>
  <span><span class="dot"></span>residential unit</span>
</div>
<div class="grid" id="grid"></div>
<script>
const P=__PANELS__;
const COL={REQUIRED:{STREET:'#1b5e20',TRAIL:'#00897b',PEDESTRIAN_CONNECTOR:'#00897b',
  OUT_OF_AREA_CONNECTOR:'#9c8f2e'},OPTIONAL_CONNECTOR:'#9c8f2e',EXCLUDED:'#b0aeb4'};
function col(role,type){const r=COL[role];return typeof r==='string'?r:(r&&r[type])||'#9c8f2e';}
const grid=document.getElementById('grid');
P.forEach((p,i)=>{
  const c=document.createElement('div');c.className='card';
  c.innerHTML=`<h2>${p.name}<span class="tag">${p.action.replace(/_/g,' ').toLowerCase()}</span></h2>
    <div class="meta">${p.units.toLocaleString()} units · ${p.acres} acres · hold ${p.status}</div>
    <canvas id="cv${i}"></canvas>
    <div class="facts">
      <div class="row"><span>Internal eligible network</span><b>${p.internal} mi</b></div>
      <div class="row"><span>Units within 25 m</span><b>${p.d.within_25m} / ${p.units}</b></div>
      <div class="row"><span>Units within 75 m (cap)</span><b>${p.d.within_75m} / ${p.units}</b></div>
      <div class="row"><span>Units beyond cap</span><b>${p.beyond} (${Math.round(p.share*100)}%)</b></div>
      <div class="row"><span>Distance median / p90 / max</span><b>${p.d.median_m} / ${p.d.p90_m} / ${p.d.max_m} m</b></div>
      <div class="row"><span>Units associated / held</span><b>${p.associated} / ${p.held}</b></div>
    </div>
    <div class="rec"><div class="a">${p.action.replace(/_/g,' ')}</div>${p.detail}</div>`;
  grid.appendChild(c);
});
function draw(){
 P.forEach((p,i)=>{
  const cv=document.getElementById('cv'+i),cx=cv.getContext('2d');
  const dpr=Math.min(devicePixelRatio||1,2),W=cv.clientWidth,H=cv.clientHeight;
  cv.width=W*dpr;cv.height=H*dpr;cx.setTransform(dpr,0,0,dpr,0,0);cx.clearRect(0,0,W,H);
  let x0=1e9,y0=1e9,x1=-1e9,y1=-1e9;
  const all=[...p.hull,...p.points,...p.lines.flatMap(l=>l[5])];
  for(const [x,y] of all){if(x<x0)x0=x;if(x>x1)x1=x;if(y<y0)y0=y;if(y>y1)y1=y;}
  const KX=Math.cos((y0+y1)/2*Math.PI/180),w=(x1-x0)*KX,h=y1-y0;
  const s=Math.min(W/w,H/h)*0.9,bx=(W-w*s)/2,by=(H-h*s)/2;
  const px=x=>bx+(x-x0)*KX*s, py=y=>by+(y1-y)*s;
  cx.lineJoin=cx.lineCap='round';
  cx.beginPath();p.hull.forEach(([x,y],k)=>k?cx.lineTo(px(x),py(y)):cx.moveTo(px(x),py(y)));
  cx.closePath();cx.fillStyle='rgba(120,120,140,.10)';cx.fill();
  cx.strokeStyle='rgba(120,120,140,.45)';cx.setLineDash([4,3]);cx.lineWidth=1;cx.stroke();
  cx.setLineDash([]);
  for(const L of p.lines){
    cx.strokeStyle=col(L[0],L[1]);cx.lineWidth=L[0]==='REQUIRED'?2.2:1.4;
    cx.globalAlpha=L[0]==='EXCLUDED'?.65:.95;cx.beginPath();
    L[5].forEach(([x,y],k)=>k?cx.lineTo(px(x),py(y)):cx.moveTo(px(x),py(y)));cx.stroke();
  }
  cx.globalAlpha=.85;cx.fillStyle='#c2185b';
  for(const [x,y] of p.points){cx.beginPath();cx.arc(px(x),py(y),1.7,0,7);cx.fill();}
  cx.globalAlpha=1;
 });
}
addEventListener('resize',draw);
new MutationObserver(draw).observe(document.documentElement,{attributes:true,attributeFilter:['data-theme']});
draw();
</script>
"""

if __name__ == "__main__":
    main()
