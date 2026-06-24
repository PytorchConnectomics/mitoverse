#!/usr/bin/env python3
"""Generate a self-contained HTML explorer (web/index.html) for the MitoVerse catalog.

Multi-tab pivot over the benchmark's stratification axes (per .agent/plan.md): All volumes,
By modality, By organism, By resolution, By tissue, By dataset, By provenance. Data is embedded,
so the page is fully portable (open the file, or host on GitHub Pages).

  python scripts/build_web.py [data-root]
"""
import json, os, sys

DATA_ROOT = sys.argv[1] if len(sys.argv) > 1 else "/projects/weilab/dataset/mitoverse"
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(HERE, "docs", "index.html")   # docs/ so GitHub Pages can serve it (main /docs)

cat = json.load(open(os.path.join(DATA_ROOT, "catalog.json")))
vols = []
for vid, m in cat.items():
    sh = m.get("shape_zyx", [0, 0, 0]); vx = m.get("voxel_nm", [0, 0, 0])
    iso = len(set(vx)) == 1 and vx != [0, 0, 0]
    vols.append({
        "id": vid, "dataset": m.get("dataset_id", ""),
        "modality": m.get("modality") or "—", "species": m.get("species") or "—",
        "tissue": m.get("tissue") or "—",
        "res": ("×".join(str(int(x)) for x in vx)) if vx != [0, 0, 0] else "TBD",
        "iso": iso, "shape": [int(sh[2]), int(sh[1]), int(sh[0])],
        "n": int(m.get("n_instances", 0)), "prov": m.get("provenance") or "—",
    })
vols.sort(key=lambda v: (v["dataset"], v["id"]))

TEMPLATE = r"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>MitoVerse — dataset explorer</title>
<style>
:root{--bg:#0b1020;--panel:#141b30;--line:#243049;--txt:#e6ecf5;--mut:#94a3b8;--accent:#38bdf8}
*{box-sizing:border-box}
body{margin:0;font:14px/1.5 -apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;background:var(--bg);color:var(--txt)}
header{padding:24px 28px 8px}
h1{margin:0;font-size:22px;letter-spacing:.3px}
h1 small{color:var(--mut);font-weight:400;font-size:13px;margin-left:10px}
a{color:var(--accent);text-decoration:none}
.wrap{padding:0 28px 60px}
.cards{display:flex;gap:12px;flex-wrap:wrap;margin:14px 0 18px}
.card{background:var(--panel);border:1px solid var(--line);border-radius:10px;padding:12px 18px;min-width:110px}
.card .num{font-size:22px;font-weight:700}
.card .lbl{color:var(--mut);font-size:12px;text-transform:uppercase;letter-spacing:.5px}
.tabs{display:flex;gap:6px;flex-wrap:wrap;border-bottom:1px solid var(--line);margin-bottom:14px}
.tabs button{background:none;border:0;color:var(--mut);padding:9px 14px;font-size:13px;cursor:pointer;border-bottom:2px solid transparent}
.tabs button:hover{color:var(--txt)}
.tabs button.active{color:var(--txt);border-bottom-color:var(--accent)}
table{width:100%;border-collapse:collapse;font-size:13px}
th,td{text-align:left;padding:8px 10px;border-bottom:1px solid var(--line);white-space:nowrap}
th{position:sticky;top:0;background:var(--bg);color:var(--mut);font-weight:600;cursor:pointer;user-select:none}
th.num,td.num{text-align:right}
tr.grp{cursor:pointer}tr.grp:hover{background:#1b2440}
tr.grp td{font-weight:600}
tr.sub td{color:var(--mut);font-weight:400;background:#0e1424}
.badge{display:inline-block;padding:2px 8px;border-radius:20px;color:#fff;font-size:11px;font-weight:600}
.bar{height:8px;border-radius:4px;background:var(--accent);display:inline-block;vertical-align:middle}
input[type=search]{background:var(--panel);border:1px solid var(--line);color:var(--txt);border-radius:8px;padding:8px 12px;width:280px;margin-bottom:12px;font-size:13px}
.muted{color:var(--mut)}
.pill{font-size:11px;color:var(--mut);border:1px solid var(--line);border-radius:20px;padding:1px 8px;margin-left:6px}
</style></head>
<body>
<header>
  <h1>MitoVerse <small>generalist 3D-EM mitochondria benchmark · explorer</small></h1>
  <div class="muted" style="font-size:12px;margin-top:4px">
    Code: <a href="https://github.com/PytorchConnectomics/mitoverse">github.com/PytorchConnectomics/mitoverse</a> ·
    Data: <a href="https://huggingface.co/datasets/pytc/MitoVerse">huggingface.co/datasets/pytc/MitoVerse</a>
  </div>
</header>
<div class="wrap">
  <div class="cards" id="stats"></div>
  <div class="tabs" id="tabs"></div>
  <div id="view"></div>
</div>
<script>
const DATA = __DATA__;
const fmt = n => n.toLocaleString();
const MOD = {'FIB-SEM':'#2563eb','ssSEM':'#16a34a','ssTEM':'#9333ea','SBF-SEM':'#ea580c','various':'#64748b'};
const badge = m => `<span class="badge" style="background:${MOD[m]||'#64748b'}">${m}</span>`;
const uniq = (a,f)=>new Set(a.map(f)).size;
const sum  = (a,f)=>a.reduce((s,v)=>s+f(v),0);

document.getElementById('stats').innerHTML = [
  ['Volumes',DATA.length],['Datasets',uniq(DATA,v=>v.dataset)],
  ['Mitochondria',sum(DATA,v=>v.n)],['Modalities',uniq(DATA,v=>v.modality)],
  ['Organisms',uniq(DATA,v=>v.species)],
].map(([k,v])=>`<div class="card"><div class="num">${fmt(v)}</div><div class="lbl">${k}</div></div>`).join('');

const TABS=[['all','All volumes'],['modality','By modality'],['species','By organism'],
  ['res','By resolution'],['tissue','By tissue'],['dataset','By dataset'],['prov','By provenance']];
const AX={modality:v=>v.modality,species:v=>v.species,res:v=>v.res,tissue:v=>v.tissue,dataset:v=>v.dataset,prov:v=>v.prov};
const tabbar=document.getElementById('tabs');
TABS.forEach(([k,l],i)=>{const b=document.createElement('button');b.textContent=l;
  if(i===0)b.classList.add('active');b.onclick=()=>{[...tabbar.children].forEach(c=>c.classList.remove('active'));b.classList.add('active');render(k);};
  tabbar.appendChild(b);});

const shp = v => `${v.shape[0]}×${v.shape[1]}×${v.shape[2]}`;
function volRows(vs){return vs.map(v=>`<tr class="sub"><td>${v.id}</td><td>${v.dataset}</td><td>${badge(v.modality)}</td>
  <td>${v.species}</td><td>${v.tissue}</td><td>${v.res}${v.iso?' <span class=pill>iso</span>':''}</td><td>${shp(v)}</td><td class="num">${fmt(v.n)}</td></tr>`).join('');}

function flatTable(vs){
  return `<input type="search" id="q" placeholder="filter ${vs.length} volumes (id, dataset, organism, tissue…)">
  <div style="overflow:auto;max-height:70vh"><table id="tbl"><thead><tr>
  <th data-k="id">Volume</th><th data-k="dataset">Dataset</th><th data-k="modality">Modality</th>
  <th data-k="species">Organism</th><th data-k="tissue">Tissue / region</th><th data-k="res">Resolution (nm)</th>
  <th data-k="shape">Shape (x,y,z)</th><th class="num" data-k="n"># Mito</th></tr></thead>
  <tbody>${vs.map(v=>`<tr><td>${v.id}</td><td>${v.dataset}</td><td>${badge(v.modality)}</td><td>${v.species}</td>
  <td>${v.tissue}</td><td>${v.res}${v.iso?' <span class=pill>iso</span>':''}</td><td>${shp(v)}</td><td class="num">${fmt(v.n)}</td></tr>`).join('')}</tbody></table></div>`;
}
function groupTable(rows,maxMito){
  return `<div style="overflow:auto;max-height:74vh"><table><thead><tr><th>Group</th><th class="num"># Vols</th>
  <th class="num"># Mito</th><th>share</th><th class="num"># Datasets</th><th>modalities</th></tr></thead><tbody>
  ${rows.map((r,i)=>`<tr class="grp" data-i="${i}"><td>▸ ${r.g}</td><td class="num">${fmt(r.n)}</td>
   <td class="num">${fmt(r.mito)}</td><td><span class="bar" style="width:${Math.max(2,140*r.mito/maxMito)}px"></span></td>
   <td class="num">${r.ds}</td><td>${[...r.mods].map(badge).join(' ')}</td></tr>
   <tr class="det" data-d="${i}" style="display:none"><td colspan="6" style="padding:0">
     <table><tbody>${volRows(r.vs)}</tbody></table></td></tr>`).join('')}</tbody></table></div>`;
}
function render(k){
  const el=document.getElementById('view');
  if(k==='all'){
    el.innerHTML=flatTable(DATA);
    const q=document.getElementById('q'), tb=document.querySelector('#tbl tbody');
    q.oninput=()=>{const s=q.value.toLowerCase();[...tb.rows].forEach(r=>{r.style.display=r.textContent.toLowerCase().includes(s)?'':'none';});};
    let asc={};
    document.querySelectorAll('#tbl th').forEach(th=>th.onclick=()=>{const k2=th.dataset.k;asc[k2]=!asc[k2];
      const vs=[...DATA].sort((a,b)=>{let x=k2==='shape'?a.shape.reduce((p,c)=>p*c,1):a[k2],y=k2==='shape'?b.shape.reduce((p,c)=>p*c,1):b[k2];
        return (x<y?-1:x>y?1:0)*(asc[k2]?1:-1);});
      tb.innerHTML=flatTable(vs).split('<tbody>')[1].split('</tbody>')[0];q.oninput&&q.oninput();});
    return;
  }
  const f=AX[k], g={};
  DATA.forEach(v=>{(g[f(v)]=g[f(v)]||[]).push(v);});
  const rows=Object.entries(g).map(([name,vs])=>({g:name,vs,n:vs.length,mito:sum(vs,v=>v.n),
    ds:uniq(vs,v=>v.dataset),mods:new Set(vs.map(v=>v.modality))}));
  rows.sort((a,b)=>b.mito-a.mito);
  el.innerHTML=groupTable(rows,Math.max(...rows.map(r=>r.mito),1));
  document.querySelectorAll('tr.grp').forEach(tr=>tr.onclick=()=>{
    const d=document.querySelector(`tr.det[data-d="${tr.dataset.i}"]`);
    const open=d.style.display!=='none';d.style.display=open?'none':'';
    tr.cells[0].textContent=(open?'▸ ':'▾ ')+tr.cells[0].textContent.slice(2);});
}
render('all');
</script></body></html>"""

html = TEMPLATE.replace("__DATA__", json.dumps(vols, separators=(",", ":")))
os.makedirs(os.path.dirname(OUT), exist_ok=True)
open(OUT, "w").write(html)
print(f"wrote {OUT} ({len(vols)} volumes, {sum(v['n'] for v in vols)} mitos)")
