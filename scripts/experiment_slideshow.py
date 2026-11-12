"""Generate code-only slideshows: uv run scripts/experiment_slideshow.py RUN_DIRECTORY."""

import argparse
import ast
import re
import difflib
import html
import json
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('run_directory', type=Path)
    parser.add_argument('--output', type=Path, help='Default: RUN_DIRECTORY/slideshow')
    parser.add_argument('--context', type=int, default=8, help='Unchanged lines around each change (default: 8)')
    args = parser.parse_args()
    if args.context < 0:
        parser.error('--context must be nonnegative')
    output = args.output or args.run_directory / 'slideshow'
    output.mkdir(parents=True, exist_ok=True)
    variants = {}
    for path in args.run_directory.glob('*/*.evaluation.json'):
        variant, iteration = path.name.removesuffix('.evaluation.json').rsplit('.', 1)
        variants.setdefault(variant, []).append((int(iteration), path))
    if not variants:
        raise ValueError('No evaluation artifacts found')
    for variant, entries in sorted(variants.items()):
        slides = []
        for iteration, path in sorted(entries):
            prefix = path.name.removesuffix('.evaluation.json')
            before = path.with_name(prefix + '.before.py').read_text().splitlines()
            after = path.with_name(prefix + '.candidate.py').read_text().splitlines()
            status = json.loads(path.read_text())['status']
            before_locations = locate_scopes(before)
            after_locations = locate_scopes(after)
            filename = Path(json.loads(path.read_text())['target']).name
            groups = difflib.SequenceMatcher(None, before, after, autojunk=False).get_grouped_opcodes(args.context)
            pages = []
            for group in groups:
                lines = []
                for tag, start, end, new_start, new_end in group:
                    if tag == 'equal':
                        lines.extend(['context', i + 1, new_start + i - start + 1, before[i], [], before_locations[i]] for i in range(start, end))
                    else:
                        removed = [['remove', i + 1, '', before[i], [], before_locations[i]] for i in range(start, end)]
                        added = [['add', '', i + 1, after[i], [], after_locations[i]] for i in range(new_start, new_end)]
                        for index in range(max(len(removed), len(added))):
                            old = removed[index] if index < len(removed) else None
                            new = added[index] if index < len(added) else None
                            if old is not None and new is not None:
                                old[4], new[4] = highlight_words(old[3], new[3])
                            elif old is not None:
                                old[4] = [[0, len(old[3])]]
                            elif new is not None:
                                new[4] = [[0, len(new[3])]]
                        lines.extend(removed)
                        lines.extend(added)
                # Keep all source characters, including long-line continuations.
                visual = []
                for kind, old, new, text, spans, location in lines:
                    for offset in range(0, max(len(text), 1), 100):
                        chunk = text[offset:offset + 100]
                        highlights = [[max(left, offset) - offset, min(right, offset + 100) - offset]
                                      for left, right in spans if left < offset + 100 and right > offset]
                        visual.append([kind, old if offset == 0 else '', new if offset == 0 else '', chunk, highlights, location])
                # Repeat a few context rows when continuing a large hunk.
                cursor = 0
                while cursor < len(visual):
                    page = visual[cursor:cursor + 30]
                    pages.append(page)
                    if cursor + 30 >= len(visual):
                        break
                    cursor += 27
            if not pages:
                pages = [[]]
            for index, lines in enumerate(pages):
                locations = list(dict.fromkeys(line[5] for line in lines))
                slides.append(dict(iteration=iteration, status=status, page=index + 1, pages=len(pages), lines=lines, location=filename + ' → ' + ', '.join(locations or ['module'])))
        payload = json.dumps(slides).replace('<', '\\u003c')
        title = f'{args.run_directory.name} · {variant}'
        document = TEMPLATE.replace('__TITLE__', html.escape(title)).replace('__VARIANT__', html.escape(variant)).replace('__DATA__', payload)
        destination = output / f'{variant}.html'
        destination.write_text(document)
        print(f'{destination}: {len(slides)} slides')


def locate_scopes(lines):
    """Locate enclosing Python declarations without executing source."""
    locations = ['module'] * len(lines)
    try:
        tree = ast.parse('\n'.join(lines))
    except SyntaxError:
        return locations
    declarations = [node for node in ast.walk(tree) if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))]
    declarations.sort(key=lambda node: (node.lineno, -(node.end_lineno - node.lineno)))
    for node in declarations:
        parent = locations[node.lineno - 1]
        name = node.name if parent == 'module' else parent + '.' + node.name
        for index in range(node.lineno - 1, node.end_lineno):
            locations[index] = name
    return locations


def highlight_words(before, after):
    """Return changed token ranges on both sides of a replacement."""
    old = list(re.finditer(r'\w+|[^\w\s]+|\s+', before))
    new = list(re.finditer(r'\w+|[^\w\s]+|\s+', after))
    removed, added = [], []
    for tag, start, end, new_start, new_end in difflib.SequenceMatcher(
        None, [token.group() for token in old], [token.group() for token in new], autojunk=False,
    ).get_opcodes():
        if tag != 'equal':
            if start < end:
                removed.append([old[start].start(), old[end - 1].end()])
            if new_start < new_end:
                added.append([new[new_start].start(), new[new_end - 1].end()])
    return removed, added


TEMPLATE = r'''<!doctype html><html lang="en"><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>__TITLE__</title>
<style>
*{box-sizing:border-box}body{margin:0;background:#0c111b;color:#edf3fc;font:18px system-ui}main{max-width:1800px;margin:auto;padding:30px 40px}header{display:flex;justify-content:space-between;align-items:center}h1{font-size:30px;margin:0}#caption{color:#a7b8cf;margin:12px 0 22px}#code{background:#101a28;border:1px solid #344253;border-radius:10px;height:770px;padding:14px 0;overflow:auto;font:17px/24px ui-monospace,SFMono-Regular,Consolas,monospace}.line{display:flex;min-width:max-content;height:24px}.number{width:55px;flex-shrink:0;text-align:right;padding-right:10px;color:#8394aa}.sign{width:30px;flex-shrink:0;text-align:center}code{white-space:pre;tab-size:4}.add mark{background:#267454;color:inherit}.remove mark{background:#913b50;color:inherit}mark{border-radius:2px}#location{font:16px ui-monospace,monospace;color:#bdd0ea;margin:8px 0 16px}.add{background:#143c31;color:#d2ffe8}.remove{background:#3e222e;color:#ffc5ca}.empty{padding:40px;color:#a7b8cf}nav{display:flex;gap:14px;align-items:center;margin-top:20px}button,select{background:#1c2a3d;color:inherit;border:1px solid #465a74;border-radius:6px;padding:8px 14px;font:inherit}button{cursor:pointer}button:disabled{opacity:.4}#position{margin-left:auto}body.recording nav{visibility:hidden}@media(max-width:900px){main{padding:20px}#code{font-size:13px;height:70vh}h1{font-size:22px}}
</style><main><header><h1>__VARIANT__ · Code changes</h1><span id="status"></span></header><p id="caption"></p><p id="location"></p><div id="code"></div><nav><button id="prev">Previous</button><button id="play">Play</button><button id="next">Next</button><label>Iteration <select id="iteration"></select></label><span id="position"></span></nav></main>
<script id="data" type="application/json">__DATA__</script><script>
const slides=JSON.parse(document.getElementById('data').textContent);
const el=id=>document.getElementById(id);
const escapeText=text=>String(text).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
function renderWords(text,spans){
 let output='',cursor=0;
 for(const [start,end] of spans){output+=escapeText(text.slice(cursor,start))+'<mark>'+escapeText(text.slice(start,end))+'</mark>';cursor=end;}
 return output+escapeText(text.slice(cursor));
}
let current=0,timer=null;
function showSlide(index){
 current=Math.max(0,Math.min(index,slides.length-1));const slide=slides[current];
 el('caption').textContent=`Iteration ${slide.iteration} · change view ${slide.page} / ${slide.pages} · before → candidate`;
 el('location').textContent=slide.location;
 el('status').textContent=slide.status;el('iteration').value=slide.iteration;
 el('code').innerHTML=slide.lines.length?slide.lines.map(([kind,before,after,text,spans])=>`<div class="line ${kind}"><span class="number">${before}</span><span class="number">${after}</span><span class="sign">${kind==='add'?'+':kind==='remove'?'−':' '}</span><code>${renderWords(text,spans)}</code></div>`).join(''):'<div class="empty">No code changes.</div>';
 el('code').scrollTop=0;el('code').scrollLeft=0;
 el('position').textContent=`${current+1} / ${slides.length}`;el('prev').disabled=current===0;el('next').disabled=current===slides.length-1;
 if(current===slides.length-1)stopPlayback();
}
function stopPlayback(){clearInterval(timer);timer=null;el('play').textContent='Play'}
[...new Set(slides.map(s=>s.iteration))].forEach(iteration=>{const option=document.createElement('option');option.value=iteration;option.textContent=iteration;el('iteration').append(option)});
el('prev').onclick=()=>{stopPlayback();showSlide(current-1)};el('next').onclick=()=>{stopPlayback();showSlide(current+1)};
el('iteration').onchange=()=>{stopPlayback();showSlide(slides.findIndex(s=>s.iteration===Number(el('iteration').value)))};
el('play').onclick=()=>{if(timer){stopPlayback();return}if(current===slides.length-1)showSlide(0);el('play').textContent='Pause';timer=setInterval(()=>showSlide(current+1),3500)};
document.addEventListener('keydown',event=>{if(event.target.matches('select,button'))return;if(event.key==='ArrowRight'){stopPlayback();showSlide(current+1)}if(event.key==='ArrowLeft'){stopPlayback();showSlide(current-1)}});
window.replay={count:slides.length,show:showSlide};showSlide(0);
</script></html>'''


if __name__ == '__main__':
    main()
