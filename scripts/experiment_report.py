#!/usr/bin/env python3
"""Generate a self-contained HTML report from an agent-runner experiment.

Usage: python scripts/experiment_report.py RUN_DIRECTORY [--output report.html]
"""

import argparse
import html
import json
import tomllib
from pathlib import Path


def read_experiment(run_dir):
    manifest = tomllib.loads((run_dir / 'run.toml').read_text())
    config = {key: value for key, value in manifest.items() if not isinstance(value, dict)}
    for table in ('agent', 'evaluation'):
        config.update(manifest.get(table, {}))
    rows = []
    for path in [*run_dir.glob('*.evaluation.json'), *run_dir.glob('*/*.evaluation.json')]:
        variant, iteration = path.name.removesuffix('.evaluation.json').rsplit('.', 1)
        report = json.loads(path.read_text())
        rows.append(dict(variant=variant, iteration=int(iteration), **report))
    rows.sort(key=lambda row: (row['variant'], row['iteration']))
    if not rows:
        raise ValueError(f'No evaluation files found in {run_dir}')
    return config, rows


def render(run_dir, config, rows):
    # Escape '<' so source data cannot terminate the embedded script element.
    payload = json.dumps({'config': config, 'rows': rows}).replace('<', '\\u003c')
    return TEMPLATE.replace('__TITLE__', html.escape(run_dir.name)).replace('__DATA__', payload)


TEMPLATE = '''<!doctype html>
<html lang="en"><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Experiment report · __TITLE__</title>
<style>
:root{font:16px system-ui,sans-serif;color:#17243a;background:#f3f6fa}
body{max-width:1180px;margin:40px auto;padding:0 24px}h1{font-size:30px;margin-bottom:8px}
p{line-height:1.6}.muted{color:#52647b}section{background:white;border:1px solid #dbe3ed;
border-radius:12px;padding:24px;margin:24px 0}label{display:inline-flex;gap:8px;align-items:center;
margin:8px 24px 8px 0}select{padding:8px;max-width:100%}svg{width:100%;height:auto}
.chart{overflow-x:auto}.chart svg{min-width:650px}table{border-collapse:collapse;width:100%;font-size:14px}
th,td{text-align:right;padding:11px;border-bottom:1px solid #e5eaf1}th:first-child,td:first-child{text-align:left}
.table-wrap{overflow:auto}.legend{display:flex;gap:24px;flex-wrap:wrap}.swatch{display:inline-block;
width:12px;height:12px;border-radius:50%;margin-right:7px}.task{white-space:pre-wrap}
</style>
<h1>Refactoring experiment</h1><div class="muted">__TITLE__</div>
<p id="description"></p>
<section><label>Metric <select id="metric"></select></label>
<label><input type="checkbox" id="log" checked>Logarithmic scale</label>
<label><input type="checkbox" id="labels">Show every value</label>
<label><input type="checkbox" id="retained" checked>Show retained values</label>
<p class="muted">Iteration 0 is each variant’s starting value. Later points show candidate measurements,
or retained values after acceptance and rollback. Uncheck “Show retained values” to see rejected candidate scores.
Missing measurements break the line. Hover or focus a point for details.
The logarithmic view uses log(1 + value), so zero remains visible.</p>
<div id="legend" class="legend"></div><div id="chart" class="chart"></div>
<p id="summary"></p></section>
<section><h2>Every iteration</h2><div class="table-wrap"><table><thead><tr>
<th>Variant</th><th>Iteration</th><th>Before</th><th>Candidate</th><th>Retained</th><th>Change</th>
<th>Status</th><th>Test exit code</th></tr></thead><tbody id="rows"></tbody></table></div>
<p class="muted">Accepted means the run passed validation; it does not necessarily mean the metric improved.
These are static dependency metrics, not runtime measurements.</p></section>
<section><h2>Experiment</h2><p id="metadata"></p><div id="task" class="task"></div></section>
<script id="data" type="application/json">__DATA__</script>
<script>
const {config,rows}=JSON.parse(document.getElementById('data').textContent);
const variants=[...new Set(rows.map(r=>r.variant))];
const metrics=[...new Set([...(config.metrics||[]),...rows.flatMap(r=>Object.keys(r.before||{})),
  ...rows.flatMap(r=>Object.keys(r.after||{}))])];
const colors=['#2563eb','#d45b13','#12816a','#9449b8'];
const el=id=>document.getElementById(id);
const fmt=v=>v==null?'—':v.toLocaleString('en-US',{maximumFractionDigits:3});
const esc=s=>String(s).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const finite=v=>typeof v==='number'&&Number.isFinite(v);
el('description').textContent=`${variants.length} variants · ${rows.length} recorded iterations · ${config.target||''}`;
el('metadata').textContent=`Experiment: ${config.name||'unspecified'} · Mode: ${config.mode||'unspecified'} · Variants: ${(config.variants||[]).join(', ')} · Model: ${config.model||'unspecified'} · Target: ${config.target||'unspecified'} · Tests: ${config.test_script||'unspecified'} · Reject if not improved: ${config.reject_if_not_improved??false}`;
el('task').textContent=config.task||'';
metrics.forEach(m=>{const o=document.createElement('option');o.value=m;o.textContent=m;el('metric').append(o)});
el('legend').innerHTML=variants.map((v,i)=>`<span><i class="swatch" style="background:${colors[i%colors.length]}"></i>${esc(v)}</span>`).join('');
function draw(){
 const metric=el('metric').value, logarithmic=el('log').checked, retained=el('retained').checked;
 const series=variants.map((v,i)=>{
  const rs=rows.filter(r=>r.variant===v);
  return {name:v,color:colors[i%colors.length],points:[
   {iteration:0,value:rs[0].before?.[metric],status:'baseline'},
   ...rs.map(r=>({...r,value:(retained&&!r.accepted?r.before:r.after)?.[metric]}))]};
 });
 const values=series.flatMap(s=>s.points.map(p=>p.value)).filter(finite);
 if(!values.length){el('chart').textContent='No numeric measurements for this metric.';return;}
 const transform=v=>logarithmic?Math.log1p(Math.max(0,v)):v;
 const inverse=v=>logarithmic?Math.expm1(v):v;
 const w=1100,h=460,left=100,right=35,top=35,bottom=65;
 const maximum=Math.max(...values.map(transform),1)*1.08;
 const last=Math.max(...rows.map(r=>r.iteration),1);
 const x=i=>left+i/last*(w-left-right),y=v=>h-bottom-transform(v)/maximum*(h-top-bottom);
 let svg=`<svg viewBox="0 0 ${w} ${h}" role="img" aria-label="${esc(metric)} by iteration"><title>${esc(metric)} by iteration</title>`;
 for(let i=0;i<=5;i++){
  const t=maximum*i/5,yy=h-bottom-t/maximum*(h-top-bottom);
  svg+=`<line x1="${left}" x2="${w-right}" y1="${yy}" y2="${yy}" stroke="#e2e8f0"/>
   <text x="${left-12}" y="${yy+5}" text-anchor="end" fill="#52647b" font-size="12">${fmt(inverse(t))}</text>`;
 }
 for(let i=0;i<=last;i++){
  if(last>30&&i%Math.ceil(last/20)!==0&&i!==last)continue;
  svg+=`<text x="${x(i)}" y="${h-bottom+25}" text-anchor="middle" fill="#52647b" font-size="12">${i}</text>`;
 }
 svg+=`<text x="${w/2}" y="${h-10}" text-anchor="middle" fill="#52647b">Iteration</text>`;
 series.forEach(s=>{
  let connected=false,path='';
  s.points.forEach(p=>{
   if(!finite(p.value)){connected=false;return;}
   path+=`${connected?'L':'M'}${x(p.iteration)},${y(p.value)} `;connected=true;
  });
  svg+=`<path d="${path}" fill="none" stroke="${s.color}" stroke-width="2.5"/>`;
  s.points.filter(p=>finite(p.value)).forEach(p=>{
   const title=`${s.name} · iteration ${p.iteration} · ${retained?'retained':'candidate'} ${fmt(p.value)} · ${p.status}`;
   svg+=`<circle cx="${x(p.iteration)}" cy="${y(p.value)}" r="5" stroke="${s.color}" stroke-width="2"
    fill="${p.status==='accepted'||p.status==='baseline'?s.color:'white'}" tabindex="0" aria-label="${esc(title)}"><title>${esc(title)}</title></circle>`;
   if(el('labels').checked)svg+=`<text x="${x(p.iteration)}" y="${y(p.value)-12}" text-anchor="middle" font-size="11" fill="${s.color}">${fmt(p.value)}</text>`;
  });
 });
 el('chart').innerHTML=svg+'</svg>';
 el('rows').innerHTML=rows.map(r=>{
  const a=r.before?.[metric],b=r.after?.[metric];
  const change=finite(a)&&finite(b)?`${b-a>0?'+':''}${fmt(b-a)}${a!==0?' ('+((b-a)/Math.abs(a)*100).toFixed(1)+'%)':''}`:'—';
  return `<tr><td>${esc(r.variant)}</td><td>${r.iteration}</td><td>${fmt(a)}</td><td>${fmt(b)}</td><td>${fmt(r.accepted?b:a)}</td><td>${change}</td><td>${esc(r.status)}</td><td>${fmt(r.test_return_code)}</td></tr>`;
 }).join('');
 el('summary').textContent=series.map(s=>{
  const measured=s.points.filter(p=>p.iteration>0&&finite(p.value));
  if(!measured.length)return `${s.name}: no measured candidates`;
  const latest=measured.at(-1),best=measured.reduce((a,b)=>a.value<=b.value?a:b);
  return `${s.name}: latest ${retained?'retained':'candidate'} ${fmt(latest.value)} (iteration ${latest.iteration}); lowest ${fmt(best.value)} (iteration ${best.iteration}, ${best.status})`;
 }).join('. ')+'.';
}
['metric','log','labels','retained'].forEach(id=>el(id).addEventListener('change',draw));draw();
</script></html>
'''


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('run_directory', type=Path)
    parser.add_argument('--output', '-o', type=Path, help='Default: RUN_DIRECTORY/report.html')
    args = parser.parse_args()
    config, rows = read_experiment(args.run_directory)
    output = args.output or args.run_directory / 'report.html'
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(render(args.run_directory, config, rows))
    print(output.resolve())


if __name__ == '__main__':
    main()
