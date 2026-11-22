#!/usr/bin/env python3
"""Generate a self-contained HTML report from an agent-runner experiment.

Usage: python scripts/experiment_report.py RUN_DIRECTORY [--output report.html]
"""

import argparse
import difflib
import html
import json
import tomllib
from pathlib import Path


def run_settings(run_dir):
    metadata = run_dir / 'metadata.json'
    if metadata.is_file():
        settings = json.loads(metadata.read_text()).get('settings')
        if settings is not None:
            return settings
    return tomllib.loads((run_dir / 'run.toml').read_text())


def read_experiment(run_dir):
    manifest = run_settings(run_dir)
    config = {key: value for key, value in manifest.items() if not isinstance(value, dict)}
    for table in ('agent', 'evaluation'):
        config.update(manifest.get(table, {}))
    rows = []
    for path in [*run_dir.glob('*.evaluation.json'), *run_dir.glob('*/*.evaluation.json')]:
        variant, iteration = path.name.removesuffix('.evaluation.json').rsplit('.', 1)
        if path.parent.name in manifest.get('variants', []) and path.parent != run_dir:
            variant = path.parent.name
        report = json.loads(path.read_text())
        report.pop('code_diff', None)
        profile_path = path.with_name(path.name.replace('.evaluation.json', '.profile.json'))
        if profile_path.exists():
            report['after'] = json.loads(profile_path.read_text())
        prefix = path.name.removesuffix('.evaluation.json')
        summary_path = path.with_name(f'{prefix}.summary.json')
        if summary_path.is_file():
            summary = json.loads(summary_path.read_text()).get('short_summary')
            if isinstance(summary, str) and summary.strip():
                report['short_summary'] = summary
        before_path = path.with_name(f'{prefix}.before.py')
        candidate_path = path.with_name(f'{prefix}.candidate.py')
        if before_path.exists() and candidate_path.exists():
            before = before_path.read_text().splitlines()
            candidate = candidate_path.read_text().splitlines()
            code_diff = []
            for tag, start, end, new_start, new_end in difflib.SequenceMatcher(
                None, before, candidate, autojunk=False,
            ).get_opcodes():
                for offset in range(max(end - start, new_end - new_start)):
                    old_index, new_index = start + offset, new_start + offset
                    code_diff.append({
                        'kind': tag,
                        'before': [old_index + 1, before[old_index]] if old_index < end else None,
                        'candidate': [new_index + 1, candidate[new_index]] if new_index < new_end else None,
                    })
            report['code_diff'] = code_diff
        rows.append(dict(variant=variant, iteration=int(iteration), **report))
    rows.sort(key=lambda row: (row['variant'], row['iteration']))
    retained_profiles = {}
    for row in rows:
        previous = retained_profiles.get(row['variant'], {})
        row['before'] = {**previous, **row['before']}
        if row['accepted'] and row['after'] is not None:
            retained_profiles[row['variant']] = row['after']
        else:
            retained_profiles[row['variant']] = row['before']
    if not rows:
        raise ValueError(f'No evaluation files found in {run_dir}')
    return config, rows


def render(run_dir, config, rows):
    # Escape '<' so source data cannot terminate the embedded script element.
    payload = json.dumps({'config': config, 'rows': rows}).replace('<', '\\u003c')
    return TEMPLATE.replace('__TITLE__', html.escape(run_dir.name)).replace('__DATA__', payload)


TEMPLATE = r'''<!doctype html>
<html lang="en"><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Experiment report (__TITLE__)</title>
<style>
:root{font:16px system-ui,sans-serif;color:#17243a;background:#f3f6fa}
body{max-width:1180px;margin:40px auto;padding:0 24px}h1{font-size:30px;margin-bottom:8px}
p{line-height:1.6}.muted{color:#52647b}section{background:white;border:1px solid #dbe3ed;
border-radius:12px;padding:24px;margin:24px 0}label{display:inline-flex;gap:8px;align-items:center;
margin:8px 24px 8px 0}select{padding:8px;max-width:100%}svg{width:100%;height:auto}
.chart{overflow-x:auto}.chart svg{min-width:650px}table{border-collapse:collapse;width:100%;font-size:14px}
th,td{text-align:right;padding:11px;border-bottom:1px solid #e5eaf1}th:first-child,td:first-child{text-align:left}
.table-wrap{overflow:auto}.legend{display:flex;gap:24px;flex-wrap:wrap}.swatch{display:inline-block;
width:12px;height:12px;border-radius:50%;margin-right:7px}.task{max-width:78ch;line-height:1.75}.task p{margin:0 0 1.2em;white-space:pre-wrap}.task code{font-size:.92em;background:#eef2f7;padding:2px 5px;border-radius:4px;overflow-wrap:anywhere}
.metric-picker{position:relative;display:inline-block;margin-right:24px}summary{cursor:pointer;padding:8px;border:1px solid #dbe3ed;border-radius:6px}.metric-picker #metrics{position:absolute;z-index:2;background:white;border:1px solid #dbe3ed;border-radius:6px;padding:12px;max-height:360px;overflow:auto;width:min(520px,75vw)}#metrics label{display:flex;margin:6px 0;overflow-wrap:anywhere}.metric-panel{margin-top:24px;border-top:1px solid #dbe3ed;padding-top:16px}
#metadata{line-height:1.9;padding-left:24px}
.metric-deltas{max-height:320px;margin:12px 0 20px}.metric-deltas thead{position:sticky;top:0;background:white}.metric-deltas td:first-child{font-family:ui-monospace,monospace}.delta-positive{color:#9a3412}.delta-negative{color:#1d4ed8}
.code-scroll{max-height:680px;overflow:auto;border:1px solid #dbe3ed;border-radius:6px}.code-grid{display:grid;grid-template-columns:minmax(0,1fr) minmax(0,1fr);min-width:720px;font:12px/1.6 ui-monospace,SFMono-Regular,Consolas,monospace}.code-cell{display:flex;min-width:0;border-right:1px solid #dbe3ed;white-space:pre;overflow:auto;min-height:1.6em}.line-number{color:#64748b;user-select:none;min-width:4em;text-align:right;padding-right:12px;position:sticky;left:0;background:inherit}.code-cell code{padding-right:12px}.removed{background:#fff0f0}.added{background:#e9f8ee}.empty{background:#f1f5f9}.code-heading{font:600 14px system-ui;padding:12px;background:#f1f5f9;position:sticky;top:0;z-index:1}button{padding:8px 14px;cursor:pointer;border:1px solid #cbd5e1;border-radius:6px;background:white}button:disabled{opacity:.45;cursor:default}
</style>
<h1>Refactoring experiment</h1><div class="muted">__TITLE__</div>
<p id="description"></p>
<section><details class="metric-picker"><summary id="metric-count">Metrics</summary><div id="metrics"></div></details>
<label><input type="checkbox" id="log" checked>Logarithmic scale</label>
<label><input type="checkbox" id="labels">Show every value</label>
<label><input type="checkbox" id="retained" checked>Show retained values</label>
<p class="muted">Click a point to view code changes.</p>
<div id="legend" class="legend"></div><div id="charts"></div></section>
<section id="code-changes"><h2>Code changes</h2><label>Variant <select id="code-variant"></select></label><button id="code-prev" type="button">Previous</button> <label>Iteration <select id="code-iteration"></select></label><button id="code-next" type="button">Next</button><p id="code-status" class="muted"></p><p id="agent-summary" hidden><strong>Agent summary</strong><br> <span id="summary-text"></span></p><details open><summary>Metric changes</summary><div class="table-wrap metric-deltas"><table><thead><tr><th>Metric</th><th>Before</th><th>Candidate</th><th>Change</th><th>Change %</th></tr></thead><tbody id="code-metrics"></tbody></table></div></details><div id="code-view" class="code-scroll"></div></section>
<section><h2>Experiment</h2><ul id="metadata"></ul><h3>Agent prompt</h3><div id="task" class="task"></div></section>
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
el('description').textContent=`${variants.length} variants, ${rows.length} recorded iterations${config.target?' for '+config.target:''}`;
const metadata=[
 ['Experiment',config.name||'unspecified'],
 ['Mode',config.mode||'unspecified'],
 ['Variants',(config.variants||[]).join(', ')],
 ['Model',config.model||'unspecified'],
 ['Target',config.target||'unspecified'],
 ['Tests',config.test_script||'unspecified'],
 ['Reject if not improved',config.reject_if_not_improved??false],
];
metadata.forEach(([label,value])=>{
 const item=document.createElement('li'),name=document.createElement('strong');
 name.textContent=label+': ';item.append(name,document.createTextNode(String(value)));el('metadata').append(item);
});
const promptParagraphs=(config.task||'').trim().split(/\n\s*\n/);
const sentenceSegmenter=new Intl.Segmenter('en',{granularity:'sentence'});
promptParagraphs.filter(Boolean).forEach(block=>{
 const sentences=[...sentenceSegmenter.segment(block)].map(part=>part.segment);
 for(let i=0;i<sentences.length;i+=3){
  const paragraph=document.createElement('p');
  const text=sentences.slice(i,i+3).join('').trim();
  paragraph.innerHTML=esc(text).replace(/\b(calculator\.py|test_calculator\.py|graph\.paths\.expressions\.count)\b/g,'<code>$1</code>');
  el('task').append(paragraph);
 }
});
const availableMetrics=metrics.filter(m=>rows.some(r=>finite(r.before?.[m])||finite(r.after?.[m])));
const defaultMetrics=new Set(availableMetrics.filter(m=>config.metrics?.includes(m)));
if(!defaultMetrics.size)defaultMetrics.add(availableMetrics[0]);
availableMetrics.forEach(m=>{
 const label=document.createElement('label'),input=document.createElement('input');
 input.type='checkbox';input.value=m;input.checked=defaultMetrics.has(m);input.addEventListener('change',draw);
 label.append(input,document.createTextNode(m));el('metrics').append(label);
});
el('legend').innerHTML=variants.map((v,i)=>`<span><i class="swatch" style="background:${colors[i%colors.length]}"></i>${esc(v)}</span>`).join('');
variants.forEach(variant=>{const option=document.createElement('option');option.value=variant;option.textContent=variant;el('code-variant').append(option)});
function listCodeIterations(){
 el('code-iteration').replaceChildren();
 rows.filter(row=>row.variant===el('code-variant').value).forEach(row=>{
  const option=document.createElement('option');option.value=row.iteration;option.textContent=`${row.iteration} (${row.status})`;el('code-iteration').append(option);
 });
 drawCode();
}
function highlightIteration(){
 const iteration=Number(el('code-iteration').value),variant=el('code-variant').value;
 document.querySelectorAll('[data-chart-point]').forEach(point=>{
  const selected=Number(point.dataset.iteration)===iteration;
  point.setAttribute('r',selected&&point.dataset.variant===variant?'8':selected?'7':'5');
  point.setAttribute('stroke-width',selected?'4':'2');
  if(point.getAttribute('role')==='button')point.setAttribute('aria-pressed',String(selected&&point.dataset.variant===variant));
 });
 document.querySelectorAll('[data-iteration-marker]').forEach(marker=>{
  marker.style.display=Number(marker.dataset.iterationMarker)===iteration?'':'none';
 });
}
function openCode(variant,iteration){
 el('code-variant').value=variant;listCodeIterations();
 el('code-iteration').value=iteration;drawCode();
 el('code-changes').scrollIntoView({behavior:'smooth',block:'start'});
 el('code-iteration').focus({preventScroll:true});
}
function drawCode(){
 highlightIteration();
 const select=el('code-iteration');
 const row=rows.find(row=>row.variant===el('code-variant').value&&row.iteration===Number(select.value));
 el('code-prev').disabled=select.selectedIndex<=0;
 el('code-next').disabled=select.selectedIndex>=select.options.length-1;
 el('code-status').textContent=row?`${row.variant}, iteration ${row.iteration} (${row.status})`:'';
 el('summary-text').textContent=row?.short_summary||'';
 el('agent-summary').hidden=!row?.short_summary;
 const signed=value=>`${value>0?'+':''}${fmt(value)}`;
 el('code-metrics').innerHTML=row?metrics.filter(metric=>{
  const before=row.before?.[metric],after=row.after?.[metric];
  return finite(before)&&finite(after)&&before!==after;
 }).map(metric=>{
  const before=row.before?.[metric],after=row.after?.[metric];
  const delta=finite(before)&&finite(after)?after-before:null;
  const percent=delta!==null&&before!==0?delta/Math.abs(before)*100:null;
  const style=delta>0?'delta-positive':delta<0?'delta-negative':'';
  return `<tr><td>${esc(metric)}</td><td>${fmt(before)}</td><td>${fmt(after)}</td><td class="${style}">${delta===null?'—':signed(delta)}</td><td class="${style}">${percent===null?'—':signed(percent)+'%'}</td></tr>`;
 }).join('')||'<tr><td colspan="5">No measured metric changes.</td></tr>':'';
 if(!row?.code_diff){el('code-view').textContent='Code snapshots unavailable.';return;}
 const cell=(line,kind)=>`<div class="code-cell ${line?kind:'empty'}"><span class="line-number">${line?esc(line[0]):''}</span><code>${line?esc(line[1]):''}</code></div>`;
 el('code-view').innerHTML='<div class="code-grid"><div class="code-heading">Before</div><div class="code-heading">Candidate</div>'+row.code_diff.map(line=>cell(line.before,line.kind==='equal'?'':'removed')+cell(line.candidate,line.kind==='equal'?'':'added')).join('')+'</div>';
 el('code-view').scrollTop=0;
}
el('code-variant').addEventListener('change',listCodeIterations);
el('code-iteration').addEventListener('change',drawCode);
['prev','next'].forEach(direction=>el(`code-${direction}`).addEventListener('click',()=>{
 el('code-iteration').selectedIndex+=direction==='next'?1:-1;drawCode();
}));
listCodeIterations();
function draw(){
 const selected=[...el('metrics').querySelectorAll('input:checked')].map(input=>input.value);
 el('metric-count').textContent=`Metrics (${selected.length} selected)`;
 el('charts').replaceChildren();
 if(!selected.length)el('charts').textContent='Select metrics to display.';
 selected.forEach(metric=>{
  const panel=document.createElement('div');panel.className='metric-panel';
  panel.innerHTML=`<h2>${esc(metric)}</h2><div data-part="chart" class="chart"></div><p data-part="summary"></p><details><summary>Every iteration</summary><div class="table-wrap"><table><thead><tr><th>Variant</th><th>Iteration</th><th>Before</th><th>Candidate</th><th>Retained</th><th>Change</th><th>Status</th><th>Test exit code</th></tr></thead><tbody data-part="rows"></tbody></table></div></details>`;
  el('charts').append(panel);drawMetric(metric,panel);
 });
 highlightIteration();
}
function drawMetric(metric,panel){
 const el=id=>panel.querySelector(`[data-part="${id}"]`)||document.getElementById(id);
 const logarithmic=el('log').checked, retained=el('retained').checked;
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
 const ticks=[...new Set(Array.from({length:6},(_,i)=>{
  const value=inverse(maximum*i/5);
  return Math.min(Math.round(value),Math.floor(inverse(maximum)));
 }))];
 for(const value of ticks){
  const yy=y(value);
  svg+=`<line x1="${left}" x2="${w-right}" y1="${yy}" y2="${yy}" stroke="#e2e8f0"/>
   <text x="${left-12}" y="${yy+5}" text-anchor="end" fill="#52647b" font-size="12">${fmt(value)}</text>`;
 }
 for(let i=0;i<=last;i++){
  if(last>30&&i%Math.ceil(last/20)!==0&&i!==last)continue;
  svg+=`<text x="${x(i)}" y="${h-bottom+25}" text-anchor="middle" fill="#52647b" font-size="12">${i}</text>`;
 }
 svg+=`<text x="${w/2}" y="${h-10}" text-anchor="middle" fill="#52647b">Iteration</text>`;
 for(let iteration=1;iteration<=last;iteration++){
  svg+=`<line data-iteration-marker="${iteration}" x1="${x(iteration)}" x2="${x(iteration)}" y1="${top}" y2="${h-bottom}" stroke="#64748b" stroke-dasharray="5 5" style="display:none"/>`;
 }
 series.forEach(s=>{
  let connected=false,path='';
  s.points.forEach(p=>{
   if(!finite(p.value)){connected=false;return;}
   path+=`${connected?'L':'M'}${x(p.iteration)},${y(p.value)} `;connected=true;
  });
  svg+=`<path d="${path}" fill="none" stroke="${s.color}" stroke-width="2.5"/>`;
  s.points.filter(p=>finite(p.value)).forEach(p=>{
   const title=`${s.name}, iteration ${p.iteration}, ${retained?'retained':'candidate'} ${fmt(p.value)}, ${p.status}`;
   svg+=`<circle data-chart-point data-variant="${esc(s.name)}" data-iteration="${esc(p.iteration)}" ${p.iteration>0?'role="button" aria-pressed="false" style="cursor:pointer"':''} cx="${x(p.iteration)}" cy="${y(p.value)}" r="5" stroke="${s.color}" stroke-width="2"
    fill="${p.status==='accepted'||p.status==='baseline'?s.color:'white'}" tabindex="0" aria-label="${esc(title)}"><title>${esc(title)}</title></circle>`;
   if(el('labels').checked)svg+=`<text x="${x(p.iteration)}" y="${y(p.value)-12}" text-anchor="middle" font-size="11" fill="${s.color}">${fmt(p.value)}</text>`;
  });
 });
 el('chart').innerHTML=svg+'</svg>';
 el('chart').querySelectorAll('[data-chart-point][role="button"]').forEach(point=>{
  const activate=()=>openCode(point.dataset.variant,Number(point.dataset.iteration));
  point.addEventListener('click',activate);
  point.addEventListener('keydown',event=>{
   if(event.key==='Enter'||event.key===' '){event.preventDefault();activate();}
  });
 });
 el('rows').innerHTML=rows.map(r=>{
  const a=r.before?.[metric],b=r.after?.[metric];
  const change=finite(a)&&finite(b)?`${b-a>0?'+':''}${fmt(b-a)}${a!==0?' ('+((b-a)/Math.abs(a)*100).toFixed(1)+'%)':''}`:'—';
  return `<tr><td>${esc(r.variant)}</td><td>${esc(r.iteration)}</td><td>${esc(fmt(a))}</td><td>${esc(fmt(b))}</td><td>${esc(fmt(r.accepted?b:a))}</td><td>${change}</td><td>${esc(r.status)}</td><td>${esc(fmt(r.test_return_code))}</td></tr>`;
 }).join('');
 el('summary').textContent=series.map(s=>{
  const measured=s.points.filter(p=>p.iteration>0&&finite(p.value));
  if(!measured.length)return `${s.name}: no measured candidates`;
  const latest=measured.at(-1),best=measured.reduce((a,b)=>a.value<=b.value?a:b);
  return `${s.name}: latest ${retained?'retained':'candidate'} ${fmt(latest.value)} (iteration ${latest.iteration}); lowest ${fmt(best.value)} (iteration ${best.iteration}, ${best.status})`;
 }).join('. ')+'.';
}
['log','labels','retained'].forEach(id=>el(id).addEventListener('change',draw));draw();
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
