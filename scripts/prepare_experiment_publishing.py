#!/usr/bin/env python3
"""Build an offline HTML report for a completed evaluated experiment (Python 3.11+)."""
import argparse
import experiment_report as interactive
import json
import re
from html import escape
from pathlib import Path
from urllib.parse import quote

ROOT = Path(__file__).resolve().parents[1]


def locate(directory):
    manifest = interactive.run_settings(directory)
    rows = {}
    for variant in manifest.get('variants', []):
        trials = []
        for i in range(1, manifest['agent']['iterations'] + 1):
            filename = f'{variant}.{i}.evaluation.json'
            path = directory / variant / filename
            if not path.exists() and len(manifest['variants']) == 1:
                path = directory / variant / f'agent-01.{i}.evaluation.json'
            if not path.exists():
                path = directory / filename
            if not path.is_file():
                return None
            trials.append(path)
        rows[variant] = trials
    return (manifest, rows) if rows and all(rows.values()) else None


def table(headers, rows):
    head = ''.join(f'<th>{escape(h)}</th>' for h in headers)
    body = ''.join('<tr>' + ''.join(f'<td>{c}</td>' for c in row) + '</tr>' for row in rows)
    return f'<div class="table-wrap"><table><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table></div>'


LABELS = {
    'graph.paths.expressions.count': 'Expression paths',
    'call.occurrences.total.count': 'Call occurrences',
    'call.dependencies.external.distinct_count': 'Distinct external call dependencies',
}


def retained(row):
    return (row['after'] if row['accepted'] else row['before']) or {}


def file_link(path, label, artifacts):
    if path not in artifacts:
        return escape(label)
    return f'<a href="{quote(path.as_posix())}">{escape(label)}</a>'


def benchmarks(path):
    """Return printed pytest-benchmark means and standard deviations in ms."""
    scales = {'ns': 1e-6, 'us': .001, 'µs': .001, 'μs': .001, 'ms': 1, 's': 1000}
    result = {}
    scale = None
    if path.exists():
        for line in path.read_text(errors='replace').splitlines():
            header = re.search(r'Name \(time in ([^)]+)\)', line)
            if header:
                scale = scales.get(header[1])
            fields = line.split()
            if scale and len(fields) >= 5 and fields[0].startswith('test_'):
                try:
                    result[fields[0]] = tuple(float(x.replace(',', '')) * scale for x in fields[3:5])
                except ValueError:
                    continue
    return result


def findings(metrics, trials, files, artifacts, source_fixture):
    parts = []
    variants = list(trials)
    paired = len(variants) == 2
    for metric in metrics:
        label = escape(LABELS.get(metric, metric))
        parts.append(f'<h3>{label}</h3>')
        series = {}
        for variant, records in trials.items():
            values = [records[0]['before'].get(metric)] + [retained(r).get(metric) for r in records]
            if any(v is None for v in values):
                parts.append(f'<p>Incomplete trajectory for {escape(variant)}.</p>')
                continue
            series[variant] = values
        summary = []
        for variant, values in series.items():
            minimum = min(values)
            turn = values.index(minimum)
            first = files[variant][max(0, turn-1)]
            stem = first.name.removesuffix('.evaluation.json')
            path = Path(variant) / (stem + ('.diff' if turn else '.before.py'))
            if not turn and source_fixture in artifacts:
                path = source_fixture
            source = file_link(path, f'turn {turn}' if turn else 'baseline', artifacts)
            summary.append([escape(variant), str(values[0]), str(minimum), source, str(values[-1])])
        parts.append(table(['Variant', 'Baseline', 'Minimum', 'First observed at', 'Final'], summary))
        if paired and len(series) == 2:
            a, b = variants
            x, y = series[a], series[b]
            gaps = [left-right for left, right in zip(x, y)]
            moves = sorted(range(1,len(gaps)), key=lambda i: abs(gaps[i]-gaps[i-1]), reverse=True)
            evidence_rows = []
            for i in dict.fromkeys([*moves[:3], len(gaps)-1]):
                if gaps[i] == gaps[i-1]:
                    continue
                cells = []
                for v in variants:
                    values = series[v]
                    stem = files[v][i-1].name.removesuffix('.evaluation.json')
                    cells.append(file_link(Path(v) / (stem + '.diff'),
                                           f'{values[i-1]:,} → {values[i]:,}', artifacts))
                evidence_rows.append([str(i), *cells, f'{gaps[i-1]:+,} → {gaps[i]:+,}'])
            if evidence_rows:
                parts.append('<p>Three largest shifts in the signed gap, followed by the final turn if it also changed the gap.</p>')
                parts.append(table(['Turn', *variants, f'{a} minus {b}'], evidence_rows))
    parts.append('<h3>Runtime of the final retained revisions</h3>')
    samples = {}
    for v, records in trials.items():
        for i in reversed(range(len(records))):
            if records[i]['accepted']:
                p = files[v][i]
                log = p.with_name(p.name.removesuffix('.evaluation.json')+'.tests.txt')
                if log.exists():
                    memory = re.search(r'^test_memory\s+([\d,]+)\s+[\d,]+\s*$', log.read_text(), re.M)
                    if memory:
                        parts.append(f'<p>{escape(v)} peak memory {memory[1]} bytes '
                                     f'({file_link(Path(v) / log.name, "test log", artifacts)}).</p>')
                samples[v] = benchmarks(log)
                for test, (mean, sd) in samples[v].items():
                    source = file_link(Path(v) / log.name, f'turn {i+1} test log', artifacts)
                    parts.append(f'<p>{escape(test)} averaged {mean:.4g} ms for {escape(v)} '
                                 f'(standard deviation {sd:.3g} ms, {source}).</p>')
                break
    common = set.intersection(*(set(samples.get(v, {})) for v in variants))
    if not common:
        parts.append('<p>No matching endpoint benchmark with a recorded mean and standard deviation.</p>')
    elif paired:
        a, b = variants
        for test in sorted(common):
            fast, slow = sorted(variants, key=lambda v: samples[v][test][0])
            low, high = samples[fast][test][0], samples[slow][test][0]
            if low == high:
                parts.append(f'<p>The measured means for {escape(test)} were equal.</p>')
            elif high:
                parts.append(f'<p><b>{escape(fast)} averaged {(high-low)/high:.1%} less time than '
                             f'{escape(slow)} on {escape(test)}.</b></p>')
    return parts


def render(directory, manifest, files, artifacts, source_fixture):
    config, rows = interactive.read_experiment(directory)
    trials = {variant: [] for variant in files}
    for row in rows:
        trials[row['variant']].append(row)
    analysis = ''.join(findings(config['metrics'], trials, files, artifacts, source_fixture))
    metadata_path = directory / 'metadata.json'
    metadata = json.loads(metadata_path.read_text()) if metadata_path.exists() else {}
    version = escape(str(metadata.get('depencity_version') or 'unrecorded'))
    panel = ('<details id="findings"><summary>Metric and benchmark comparisons</summary>'
             + analysis + '</details>')
    for row in rows:
        row['target'] = Path(row.get('target', '')).name
    for key in ('repo', 'log_root'):
        config.pop(key, None)
    page = interactive.render(directory, config, rows)
    metric = LABELS.get(config['metrics'][0], config['metrics'][0])
    objective = f'Track whether the agent steadily reduces {escape(metric.lower())}.'
    rule = config.get('reject_if_not_improved')
    gated = [variant for variant in files if rule in ('all', variant)]
    gate = 'Required for ' + ', '.join(gated) if gated else 'Optional'
    facts = [('Task', config['target']), ('Variants', ', '.join(files)), ('Runs per variant', 1),
             ('Turns per run', config['iterations']), ('Metric improvement', gate)]
    conditions = ''.join(f'<div><dt>{label}</dt><dd>{escape(str(value))}</dd></div>'
                         for label, value in facts)
    header = ('<header class="report-header"><h1>Depencity experiment</h1>'
              f'<p><strong>Objective</strong><br> {objective}</p>'
              f'<dl>{conditions}</dl><p class="muted">Depencity version: {version}</p></header>')
    style = """
.report-header{border-top:4px solid #254d74;padding:24px 0 8px}
.report-header h1{font:600 clamp(1.85rem,4vw,3.1rem)/1.12 system-ui;letter-spacing:-.035em;
  max-width:31ch;margin:0 0 24px;text-wrap:balance}
.report-header dl{display:grid;grid-template-columns:repeat(auto-fit,minmax(145px,1fr));
  margin:0;padding:16px 0;gap:14px 20px;border-block:1px solid #cbd5e1}
.report-header dt{font-size:.85rem;color:#495c74}
.report-header dd{margin:3px 0 0;font-weight:650;overflow-wrap:anywhere}
.report-options{margin-top:12px}.report-options>details{margin-bottom:8px}
.report-options>details>summary{background:white;padding:12px 16px}
"""
    page = re.sub(r'<title>.*?</title>', '<title>Depencity experiment</title>', page, count=1)
    start = page.index('<h1>Refactoring experiment</h1>')
    end = page.index('<section>', start)
    page = page[:start] + header + '<div class="report-options">' + panel + '</div>' + page[end:]
    page = page.replace('</style>', style + '</style>', 1)
    page = page.replace("el('description').textContent=", '// Header is rendered at publication time.\n// ', 1)
    return page


def collect_artifacts(files, test_name, source_fixture):
    artifacts = {}
    initial_sources = {}
    for variant, evaluations in files.items():
        first = evaluations[0]
        before = first.with_name(first.name.removesuffix('.evaluation.json') + '.before.py')
        if before.is_file():
            initial_sources[Path(variant) / before.name] = before.read_bytes()
        fixture = first.parent / 'workspace' / Path(test_name).name
        if fixture.is_file():
            name = Path('fixtures') / fixture.name
            if name in artifacts and artifacts[name] != fixture.read_bytes():
                name = Path('fixtures') / variant / fixture.name
            artifacts[name] = fixture.read_bytes()
        summaries = {}
        for turn, evaluation in enumerate(evaluations, 1):
            stem = evaluation.name.removesuffix('.evaluation.json')
            for suffix in ('.diff', '.candidate.py', '.profile.json', '.tests.txt', '.summary.json'):
                source = evaluation.with_name(stem + suffix)
                if not source.is_file():
                    continue
                data = source.read_bytes()
                if suffix == '.summary.json':
                    summaries[str(turn)] = json.loads(data)
                else:
                    artifacts[Path(variant) / source.name] = data
        artifacts[Path(variant) / 'summaries.json'] = (json.dumps(summaries, indent=2, ensure_ascii=False) + '\n').encode()
    if len(initial_sources) == len(files) and len(set(initial_sources.values())) == 1:
        artifacts[source_fixture] = next(iter(initial_sources.values()))
    else:
        artifacts.update(initial_sources)
    return artifacts


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('run_directory', nargs='?', type=Path)
    parser.add_argument('-o', '--output', type=Path)
    args = parser.parse_args()
    candidates = [args.run_directory] if args.run_directory else sorted(
        {p.parent for name in ('metadata.json', 'run.toml') for p in (ROOT/'out/experiments').rglob(name)}, key=lambda p: p.name, reverse=True)
    for directory in candidates:
        result = locate(directory)
        if result:
            output = args.output or ROOT/'published'/'experiments'/directory.parent.name/directory.name/'index.html'
            output.parent.mkdir(parents=True, exist_ok=True)
            evaluation = result[0]['evaluation']
            source_fixture = Path('fixtures') / Path(evaluation['target']).name
            artifacts = collect_artifacts(result[1], evaluation['test_script'], source_fixture)
            page = render(directory, *result, artifacts, source_fixture)
            if re.search(r'/(?:Users|home)/[^/\s]+/', page):
                parser.error('Report contains a local home-directory path; inspect source artifacts.')
            metadata = directory / 'metadata.json'
            record = json.loads(metadata.read_text()) if metadata.exists() else {}
            if 'settings' in record:
                artifacts[Path('metadata.json')] = metadata.read_bytes()
            else:
                # Legacy runners stored the effective settings in a machine-local TOML.
                record['settings'] = {k: v for k, v in result[0].items() if k not in ('repo', 'log_root')}
                artifacts[Path('metadata.json')] = (json.dumps(record, indent=2) + '\n').encode()
            for relative, data in artifacts.items():
                if re.search(rb'/(?:Users|home)/[^/\s]+/', data):
                    parser.error(f'{relative} contains a local home-directory path.')
            for relative, data in artifacts.items():
                destination = output.parent / relative
                destination.parent.mkdir(parents=True, exist_ok=True)
                destination.write_bytes(data)
            output.write_text(page, encoding='utf-8')
            print(output.resolve())
            return
    parser.error('No run with evaluations for every configured turn and variant')


if __name__ == '__main__':
    main()
