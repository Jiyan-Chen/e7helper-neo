"""训练曲线页（B14b，`e7helper rta watch`）：只监听 127.0.0.1，读 runs 目录，页面每 5 秒刷新。

不依赖 torch。接口：
- `GET /api/runs`：各 run 的设置摘要、状态（status.json）、结果（result.json）；
- `GET /api/runs/{name}/metrics?since=N`：metrics.jsonl 第 N 行以后的新行（增量）。
图用内联 SVG 手画，不引外部脚本。
"""

from __future__ import annotations

import json
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse

CONFIG_KEYS = ("model", "d", "layers", "heads", "lam", "k", "lr", "weight_decay", "schedule", "batch", "epochs", "patience",
               "full", "device",
               "params", "vocab_size", "data")


def _read_json(path: Path) -> dict | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def list_runs(root: Path) -> list[dict]:
    runs = []
    for d in sorted(root.glob("*/"), key=lambda p: p.stat().st_mtime, reverse=True):
        if not (d / "metrics.jsonl").exists():
            continue
        config = _read_json(d / "config.json") or {}
        runs.append({"name": d.name, "config": {k: config.get(k) for k in CONFIG_KEYS},
                     "status": _read_json(d / "status.json"), "result": _read_json(d / "result.json"),
                     "mtime": (d / "metrics.jsonl").stat().st_mtime})
    return runs


def read_metrics(root: Path, name: str, since: int = 0) -> dict:
    path = root / name / "metrics.jsonl"
    if "/" in name or "\\" in name or name.startswith(".") or not path.exists():
        raise FileNotFoundError(name)
    lines = path.read_text(encoding="utf-8").splitlines()
    out = []
    for line in lines[since:]:
        try:
            out.append(json.loads(line))
        except ValueError:  # 正在写的半行，下次再取
            break
    return {"lines": out, "next": since + len(out)}


def create_app(root: Path) -> FastAPI:
    app = FastAPI(title="RTA 训练曲线", docs_url=None, redoc_url=None)

    @app.get("/", response_class=HTMLResponse)
    def index() -> str:
        return PAGE

    @app.get("/api/runs")
    def runs() -> dict:
        return {"root": str(root), "runs": list_runs(root)}

    @app.get("/api/runs/{name}/metrics")
    def metrics(name: str, since: int = 0) -> dict:
        try:
            return read_metrics(root, name, max(0, since))
        except FileNotFoundError:
            raise HTTPException(404, f"没有这个 run：{name}") from None

    return app


PAGE = r"""<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>RTA 训练曲线</title>
<style>
:root{--bg:#0d1220;--panel:rgba(22,29,46,.92);--line:#2a3550;--text:#dfe6f3;--dim:#8a96ad;--gold:#e2c27a;--ok:#5fd39a;--warn:#f0b35a;--bad:#ef6f6f}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--text);font:13px/1.5 "Microsoft YaHei UI","PingFang SC",system-ui,sans-serif}
header{display:flex;align-items:center;gap:16px;padding:12px 20px;border-bottom:1px solid var(--line)}
header h1{font-size:16px;margin:0;color:var(--gold);letter-spacing:.05em}header .dim{color:var(--dim)}
main{display:grid;grid-template-columns:330px 1fr;gap:14px;padding:14px 20px}
.panel{background:var(--panel);border:1px solid var(--line);border-radius:8px;padding:12px}
.run{display:grid;grid-template-columns:18px 1fr;gap:6px;padding:8px 6px;border-bottom:1px solid var(--line);cursor:pointer}
.run:last-child{border-bottom:0}.run .name{font-weight:600}.run .meta{color:var(--dim);font-size:12px}
.sw{width:12px;height:12px;border-radius:3px;margin-top:4px;border:2px solid transparent}
.badge{display:inline-block;font-size:11px;padding:0 6px;border-radius:9px;margin-left:6px;border:1px solid}
.running{color:var(--warn);border-color:var(--warn)}.done{color:var(--ok);border-color:var(--ok)}.stopped{color:var(--dim);border-color:var(--dim)}
.bar{height:4px;background:var(--line);border-radius:2px;margin-top:4px;overflow:hidden}.bar i{display:block;height:100%;background:var(--gold)}
.charts{display:grid;grid-template-columns:repeat(auto-fill,minmax(420px,1fr));gap:14px}
.chart h3{margin:0 0 6px;font-size:13px;font-weight:600}.chart h3 span{color:var(--dim);font-weight:400;margin-left:6px}
svg text{fill:var(--dim);font-size:10px}.legend{font-size:11px;color:var(--dim);margin-top:4px}
table{border-collapse:collapse;width:100%;font-size:12px}td,th{padding:3px 6px;border-bottom:1px solid var(--line);text-align:right}
th{color:var(--dim);font-weight:400}td:first-child,th:first-child{text-align:left}
.off{opacity:.45}
@media(max-width:900px){main{grid-template-columns:1fr}.charts{grid-template-columns:1fr}}
</style></head><body>
<header><h1>RTA 训练曲线</h1><span class="dim" id="root"></span><span class="dim" id="clock"></span></header>
<main>
<section><div class="panel" id="runs"></div><div class="panel" style="margin-top:14px"><h3 style="margin:0 0 6px;font-size:13px">最佳轮的验证指标</h3><div id="table"></div></div></section>
<section class="charts" id="charts"></section>
</main>
<script>
const COLORS=["#e2c27a","#5fb4ef","#5fd39a","#ef6f6f","#b48cf2","#f0b35a","#4fd1c5","#f28cc5","#a3e635","#94a3b8"];
const state={runs:[],data:{},next:{},picked:null,color:{}};
const CHARTS=[
 {id:"win",title:"胜率损失",sub:"训练批次（细线）· 验证 12 个局面平均（实线点）· 训练子集同口径（虚线点）",train:r=>r.win,val:v=>v.win_loss,val2:v=>v.train_win_loss},
 {id:"pick",title:"选人交叉熵",sub:"训练（细线）· 验证（点）",train:r=>r.pick,val:v=>v.pick&&v.pick.ce},
 {id:"ll11",title:"验证 log loss · 后禁后（n=11）",sub:"实线全部 · 虚线双方 ≥ 优胜者",val:v=>v.n11&&v.n11.log_loss,val2:v=>v.n11_champ&&v.n11_champ.log_loss},
 {id:"auc11",title:"验证 AUC · 后禁后（n=11）",sub:"实线全部 · 虚线双方 ≥ 优胜者",val:v=>v.n11&&v.n11.auc,val2:v=>v.n11_champ&&v.n11_champ.auc},
 {id:"ece11",title:"验证 ECE · 后禁后（n=11）",sub:"校准误差，越小越好",val:v=>v.n11&&v.n11.ece},
 {id:"top",title:"选人命中率",sub:"实线前 5 · 虚线前 8",val:v=>v.pick&&v.pick.top5,val2:v=>v.pick&&v.pick.top8},
];
const fmt=(x,d=4)=>x==null||isNaN(x)?"—":(+x).toFixed(d);
const dur=s=>s==null?"—":s<60?`${s|0} 秒`:s<3600?`${(s/60)|0} 分 ${(s%60)|0} 秒`:`${(s/3600)|0} 时 ${((s%3600)/60)|0} 分`;
async function j(u){const r=await fetch(u);if(!r.ok)throw new Error(r.status);return r.json()}
async function tick(){
 try{
  const res=await j("/api/runs");document.getElementById("root").textContent=res.root;
  state.runs=res.runs;
  res.runs.forEach((r,i)=>{if(!state.color[r.name])state.color[r.name]=COLORS[Object.keys(state.color).length%COLORS.length]});
  if(state.picked===null)state.picked=new Set(res.runs.slice(0,6).map(r=>r.name));
  for(const r of res.runs){
   if(!state.picked.has(r.name))continue;
   const m=await j(`/api/runs/${encodeURIComponent(r.name)}/metrics?since=${state.next[r.name]||0}`);
   (state.data[r.name]=state.data[r.name]||[]).push(...m.lines);state.next[r.name]=m.next;
  }
  render();document.getElementById("clock").textContent="刷新于 "+new Date().toLocaleTimeString();
 }catch(e){document.getElementById("clock").textContent="连不上："+e.message}
}
function render(){
 const box=document.getElementById("runs");box.innerHTML="";
 for(const r of state.runs){
  const st=r.status||{},c=r.config||{},on=state.picked.has(r.name);
  const el=document.createElement("div");el.className="run"+(on?"":" off");
  const pct=st.total_steps?Math.min(100,100*st.step/st.total_steps):0;
  const arch=c.model==="transformer"||c.model==="hybrid"?`d=${c.d} L=${c.layers} λ=${c.lam}`:c.model==="fm"?`k=${c.k}`:"";
  el.innerHTML=`<div class="sw" style="background:${state.color[r.name]}"></div><div><div class="name">${r.name}<span class="badge ${st.status||""}">${{running:"运行中",done:"完成",stopped:"中断"}[st.status]||"—"}</span></div>
   <div class="meta">${c.model||""} ${arch} · ${c.params?(c.params/1000).toFixed(0)+"k 参数":""} · ${c.device||""}</div>
   <div class="meta">第 ${st.epoch??"—"} / ${st.epochs??"—"} 轮 · 最佳第 ${st.best_epoch??"—"} 轮 · ${c.patience?`早停计数 ${st.bad_epochs??0}/${c.patience}`:"跑满"}${c.schedule==="constant"?" · 恒定学习率":""}${c.weight_decay&&c.weight_decay!==0.01?` · wd ${c.weight_decay}`:""}${st.status==="running"?" · 剩余 "+dur(st.eta):""}</div>
   ${st.status==="running"?`<div class="bar"><i style="width:${pct}%"></i></div>`:""}</div>`;
  el.onclick=()=>{on?state.picked.delete(r.name):state.picked.add(r.name);tick()};box.appendChild(el);
 }
 const charts=document.getElementById("charts");
 for(const ch of CHARTS){
  let el=document.getElementById("c-"+ch.id);
  if(!el){el=document.createElement("div");el.className="panel chart";el.id="c-"+ch.id;el.innerHTML=`<h3>${ch.title}<span>${ch.sub}</span></h3><div></div>`;charts.appendChild(el)}
  const series=[];
  for(const name of state.picked){
   const lines=state.data[name]||[],color=state.color[name];
   if(ch.train){const pts=lines.filter(l=>l.kind==="step"&&ch.train(l)!=null).map(l=>[l.frac,ch.train(l)]);if(pts.length)series.push({pts,color,width:1,opacity:.55})}
   const vals=lines.filter(l=>l.kind==="val");
   const p1=vals.map(v=>[v.epoch,ch.val(v)]).filter(p=>p[1]!=null);if(p1.length)series.push({pts:p1,color,width:2,dots:true});
   if(ch.val2){const p2=vals.map(v=>[v.epoch,ch.val2(v)]).filter(p=>p[1]!=null);if(p2.length)series.push({pts:p2,color,width:1.5,dash:"4 3",dots:true})}
  }
  el.querySelector("div").innerHTML=svgChart(series);
 }
 const rows=state.runs.filter(r=>state.picked.has(r.name)).map(r=>{const v=(r.result&&r.result.best_val)||[...(state.data[r.name]||[])].reverse().find(l=>l.kind==="val");return [r.name,v]}).filter(x=>x[1]);
 document.getElementById("table").innerHTML=rows.length?`<table><tr><th>run</th><th>n11 log loss</th><th>AUC</th><th>ECE</th><th>前 5</th><th>前 8</th></tr>${rows.map(([n,v])=>`<tr><td style="color:${state.color[n]}">${n}</td><td>${fmt(v.n11&&v.n11.log_loss)}</td><td>${fmt(v.n11&&v.n11.auc)}</td><td>${fmt(v.n11&&v.n11.ece)}</td><td>${fmt(v.pick&&v.pick.top5,3)}</td><td>${fmt(v.pick&&v.pick.top8,3)}</td></tr>`).join("")}</table>`:`<div class="legend">还没有验证结果</div>`;
}
function svgChart(series){
 const W=440,H=220,L=52,R=10,T=8,B=26;
 const all=series.flatMap(s=>s.pts);if(!all.length)return `<div class="legend" style="padding:40px 0;text-align:center">还没有数据</div>`;
 let x0=Math.min(...all.map(p=>p[0])),x1=Math.max(...all.map(p=>p[0])),y0=Math.min(...all.map(p=>p[1])),y1=Math.max(...all.map(p=>p[1]));
 if(x1-x0<1e-9){x0-=.5;x1+=.5}if(y1-y0<1e-9){y0-=.01;y1+=.01}const pad=(y1-y0)*.08;y0-=pad;y1+=pad;x0=Math.min(x0,0);
 const X=x=>L+(x-x0)/(x1-x0)*(W-L-R),Y=y=>T+(1-(y-y0)/(y1-y0))*(H-T-B);
 let g="";
 for(let i=0;i<=4;i++){const v=y0+(y1-y0)*i/4,y=Y(v);g+=`<line x1="${L}" x2="${W-R}" y1="${y}" y2="${y}" stroke="#2a3550"/><text x="${L-6}" y="${y+3}" text-anchor="end">${v.toFixed(Math.abs(y1-y0)<.05?4:3)}</text>`}
 const xt=Math.max(1,Math.ceil((x1-x0)/8));for(let v=Math.ceil(x0);v<=x1;v+=xt)g+=`<text x="${X(v)}" y="${H-8}" text-anchor="middle">${v}</text>`;
 g+=`<text x="${W-R}" y="${H-8}" text-anchor="end">轮</text>`;
 for(const s of series){
  const d=s.pts.map((p,i)=>(i?"L":"M")+X(p[0]).toFixed(1)+" "+Y(p[1]).toFixed(1)).join("");
  g+=`<path d="${d}" fill="none" stroke="${s.color}" stroke-width="${s.width}" ${s.dash?`stroke-dasharray="${s.dash}"`:""} opacity="${s.opacity||1}"/>`;
  if(s.dots)for(const p of s.pts)g+=`<circle cx="${X(p[0])}" cy="${Y(p[1])}" r="2.6" fill="${s.color}"/>`;
 }
 return `<svg viewBox="0 0 ${W} ${H}" width="100%">${g}</svg>`;
}
tick();setInterval(tick,5000);
</script></body></html>
"""
