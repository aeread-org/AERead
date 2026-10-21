#!/usr/bin/env python3
"""Build the merged review PDF from the included, editable source copies.

Run: uv run --with markdown --with beautifulsoup4 --with pypdf python build.py
Requires pandoc and Google Chrome (macOS). No network assets are loaded.
"""
from pathlib import Path
import ast
import hashlib
import html
import json
import re
import subprocess

import markdown
from bs4 import BeautifulSoup
from pypdf import PdfReader, PdfWriter

ROOT = Path(__file__).resolve().parent
SOURCE = ROOT / "source"
OUT = ROOT / "aeread_working_draft_20261018_v15.pdf"
CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"


def pandoc(text, source_format, cite=False):
    command = ["pandoc", "-f", source_format, "-t", "html5", "--mathml"]
    if cite:
        command += ["--citeproc", "--bibliography=" + str(SOURCE / "runtime.bib")]
    result = subprocess.run(command, input=text, text=True, capture_output=True, check=True)
    if result.stderr.strip():
        raise RuntimeError(result.stderr)
    return result.stdout


def markdown_body(name):
    text = (SOURCE / name).read_text().split("\n---\n", 1)[1]
    text = text.partition("### Sources for the numbers in this section")[0]
    return text.partition("### References")[0].strip()


# Reuse the original document's math typography, without executing its renderer.
original = (SOURCE / "original_sections_builder.py").read_text()
nodes = ast.parse(original).body
namespace = {"re": re}
for node in nodes:
    if isinstance(node, ast.Assign) and any(
        isinstance(t, ast.Name) and t.id in {"_B", "_W", "_MATH"} for t in node.targets
    ):
        exec(compile(ast.Module(body=[node], type_ignores=[]), "typesetting", "exec"), namespace)
    elif isinstance(node, ast.FunctionDef) and node.name == "typeset":
        exec(compile(ast.Module(body=[node], type_ignores=[]), "typesetting", "exec"), namespace)


def user_html(text):
    result = markdown.markdown(text, extensions=["tables", "fenced_code"])
    result = namespace["typeset"](result)
    result = result.replace("10⁻⁸", "10<sup>−8</sup>")
    return result


def simplify_tables(text):
    def convert(match):
        block = match[0]
        n = block.split("\n", 1)[0].count("P{")
        caption = block[block.index(r"\caption"):block.index(r"\toprule")]
        header = block.split(r"\toprule", 1)[1].split(r"\midrule", 1)[0]
        body = block.split(r"\endlastfoot", 1)[1].rsplit(r"\end{longtable}", 1)[0]
        body = re.sub(r"\\addlinespace\[[^]]+\]", "", body)
        body = re.sub(
            r"\\multicolumn\{\d+\}\{@\{\}l\}\{\\textit\{([^}]+)\}\}",
            lambda m: r"\textit{" + m[1] + "}" + " &" * (n - 1), body,
        )
        body = body.replace(r"\\[2pt]", r"\\")
        return (
            "\\begin{table}\n" + caption.rstrip("\\\n") + "\n"
            + "\\begin{tabular}{" + "l" * n + "}\n" + header + body
            + "\\end{tabular}\n\\end{table}"
        )
    return re.sub(r"\\begin\{longtable\}.*?\\end\{longtable\}", convert, text, flags=re.S)


def prepare_tex(text):
    text = simplify_tables(text)
    text = re.sub(r"\\code\{([^}]+)\}", lambda m: r"\texttt{" + m[1].replace("_", r"\_") + "}", text)
    text = re.sub(r"\\(?:begingroup|endgroup|small|allowbreak)\b", "", text)
    text = re.sub(r"\\setlength\{[^}]*\}\{[^}]*\}", "", text)
    text = re.sub(r"\\renewcommand\{[^}]*\}\{[^}]*\}", "", text)
    text = text.replace(r"\newline", " ")
    text = text.replace(r"\qcref{}", r"Section~\ref{sec:qc}")
    text = text.replace(r"\casesref{}", r"Section~\ref{sec:cases}")
    return text


def runtime_figure():
    boxes = [
        (8, 8, ["World, block, profiles, seeds", "Resolved plan"]),
        (222, 8, ["Freeze observations", "Act, then transition"]),
        (436, 8, ["Provider / tool events", "Action envelopes"]),
        (436, 94, ["Reconstruct state and score", "Seal evidence"]),
        (222, 94, ["Receipt with typed scores", "Reference values"]),
        (8, 94, ["Replay state and score", "No model call"]),
    ]
    parts = ['<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 638 156" role="img" aria-label="Execution and receipt path">',
             '<defs><marker id="arrow" markerWidth="6" markerHeight="6" refX="5" refY="3" orient="auto"><path d="M0,0 L6,3 L0,6 Z" fill="#254e70"/></marker></defs>']
    for x, y, lines in boxes:
        parts.append(f'<rect x="{x}" y="{y}" width="194" height="52" rx="3" fill="#f8fafb" stroke="#254e70"/>')
        for i, line in enumerate(lines):
            parts.append(f'<text x="{x+97}" y="{y+21+i*17}" text-anchor="middle" font-family="Arial" font-size="12">{html.escape(line)}</text>')
    for d in ["M202,34 H220", "M416,34 H434", "M533,60 V92", "M436,120 H418", "M222,120 H204"]:
        parts.append(f'<path d="{d}" fill="none" stroke="#254e70" marker-end="url(#arrow)"/>')
    parts.append('</svg>')
    return '<figure id="fig:runtime">'+''.join(parts)+'''<figcaption>Figure H.1. The receipt path. Replay checks recorded transitions and receipt scores. It does not rerun the provider, harness or parser, or automatically cover analyses outside a receipt. The kernel supplies no sandbox or arbitrary-crash recovery.</figcaption></figure>'''


def architecture_figure():
    checks = json.loads((ROOT/'figures/ARCHITECTURE_CHECKS.json').read_text())
    for name, digest in checks['sources'].items():
        assert hashlib.sha256((ROOT/name).read_bytes()).hexdigest() == digest, name
    asset = ROOT/'figures/architecture_overview.svg'
    assert hashlib.sha256(asset.read_bytes()).hexdigest() == checks['svg_sha256']
    assert (SOURCE/'figures'/asset.name).read_bytes() == asset.read_bytes()
    return '<figure id="fig:architecture" class="architecture-figure"><img src="figures/architecture_overview.svg" alt="AERead architecture: case design, runtime interaction, evidence and measurement, with campaign QC across the workflow."><figcaption><strong>Figure 4.1. AERead architecture.</strong> Families define the economic world and reference; the runtime coordinates seat policies and retains execution evidence. Agents receive only their seat observations, while scoring uses explicitly declared reference access. Replay checks receipt consistency; separate headline derivations require their own verification. Applied coverage and QC verdicts vary by campaign (Appendices F and H).</figcaption></figure>'


PROPERTIES = ['Value against a reference with stated information', 'Counterpart is part of the case',
              'Typed shortfall', 'World generator with admission',
              'Quality control over populations of worlds', 'Scores recomputed from sealed evidence',
              'Several economic activities on one runtime']


def case_figure():
    checks = json.loads((ROOT/'figures/LEVELS_FIGURE_CHECKS.json').read_text())
    assert hashlib.sha256((ROOT/'figures/plot_evaluation_levels.py').read_bytes()).hexdigest() == checks['script_sha256']
    asset = ROOT/'figures/evaluation_levels.svg'
    assert hashlib.sha256(asset.read_bytes()).hexdigest() == checks['svg_sha256']
    assert (SOURCE/'figures'/asset.name).read_bytes() == asset.read_bytes()
    return ('<figure id="fig:case" class="case-figure"><img src="figures/evaluation_levels.svg" alt="The three levels of an AERead '
            'evaluation: the runtime hosting case families; one case and its population of admitted worlds; one world, '
            'with an agent seat, a counterpart seat and the score against the reference split by shortfall class.">'
            '<figcaption><strong>Figure 1.1. The three levels of an AERead evaluation,</strong> with the Data-center agreement '
            'as the example. The runtime hosts several case families (left). A case draws a population of worlds and admits '
            'those where the decision matters; quality control runs over that population (centre). In one world, the agent '
            'holds a seat, a counterpart holds another, and the score is compared with the case reference and split into '
            'shortfall classes (right). Dashed lines mean "contains", not a sequence. Each panel lists the properties of '
            'Section 1 that belong to its level. The dot pattern and the score bar are schematic.</figcaption></figure>')


def comparison_table():
    spec = json.loads((SOURCE/'comparison_table.json').read_text())
    symbols = {'full': '<span class="mark mark-full"></span>', 'partial': '<span class="mark mark-partial"></span>', 'no': '<span class="mark-no">–</span>'}
    rows = []
    for row in spec['rows']:
        assert len(row['marks']) == len(PROPERTIES), row['name']
        cells = []
        for mark, evidence in zip(row['marks'], row['evidence'], strict=True):
            assert mark in symbols, (row['name'], mark)
            assert evidence.strip(), (row['name'], 'evidence required for every cell')
            cells.append(f'<td title="{html.escape(evidence)}">{symbols[mark]}</td>')
        name = html.escape(row['name'])
        if row.get('this_paper'): name = f'<strong>{name}</strong>'
        rows.append(f'<tr><td>{name}</td>' + ''.join(cells) + '</tr>')
    head = '<tr><th>Benchmark</th>' + ''.join(f'<th>{i}. {html.escape(n)}</th>' for i, n in enumerate(PROPERTIES, 1)) + '</tr>'
    caption = ('<p class="caption" id="table-2.1"><strong>Table 2.1. The seven properties in related benchmarks,</strong> '
               'read from each paper\'s description of its own method: <span class="mark mark-full"></span> present, <span class="mark mark-partial"></span> partly present, – absent. '
               + html.escape(spec['note']) + '</p>')
    return '<div class="comparison-table">' + caption + '<table class="table-2-1"><thead>' + head + '</thead><tbody>' + ''.join(rows) + '</tbody></table></div>'


def number_sections(soup, first, appendix=False):
    section, subsection = first - 1, 0
    for heading in soup.find_all(['h1', 'h2']):
        if heading.name == 'h1':
            section += 1; subsection = 0
            heading.name = 'h2'
            heading.insert(0, 'Appendix H. ' if appendix else f'{section}. ')
        else:
            subsection += 1; heading.name = 'h3'
            heading.insert(0, f'H.{subsection} ' if appendix else f'{section}.{subsection} ')


def prepare_runtime_tables(soup):
    for number, table in enumerate(soup.find_all('table'), 1):
        table['class'] = ['runtime-table', f'runtime-table-{number}']
        table.find('caption').insert(0, f'Table H.{number}. ')
        first = table.find('tr').extract()
        for cell in first.find_all('td'):
            cell.name = 'th'
        thead = soup.new_tag('thead'); thead.append(first); table.insert(1, thead)


def document(title, subtitle, body, styles, authors=()):
    author_text = ' · '.join(authors)
    author_meta = f'<meta name="author" content="{html.escape(author_text, quote=True)}">' if authors else ''
    byline = f'<div class="authors">{html.escape(author_text)}</div>' if authors else ''
    byline += '<div class="contact"><a href="mailto:contact@aeread.org">contact@aeread.org</a></div>'
    return ('<!doctype html><html lang="en"><head><meta charset="utf-8">'
            f'{author_meta}<title>{html.escape(title)}</title><style>{styles}</style></head><body>'
            f'<div class="title">{html.escape(title)}</div>'
            f'{byline}<div class="subtitle">{html.escape(subtitle)}</div>{body}</body></html>')


def main():
    styles = (ROOT / 'paper.css').read_text()
    app = (SOURCE / 'app_runtime.tex').read_text()
    for name in ('tab_cli_controls', 'tab_case_paths'):
        app = app.replace(r'\input{' + name + '}', (SOURCE / f'{name}.tex').read_text())
    app = re.sub(r'\\begin\{figure\}.*?\\end\{figure\}', 'RUNTIMEFIGUREPLACEHOLDER', app, flags=re.S)
    main_tex = '\n'.join((SOURCE / name).read_text() for name in
                         ('abstract.tex', 'sec_opening.tex', 'sec_runtime.tex', 'sec_discussion.tex'))
    markers = r'\section{CITATIONMARKERS} CITEAV \citep{li2026activities} CITEABC \citep{zhu2025abc} CITETB \citep{zhang2026termsbench}'
    converted = BeautifulSoup(pandoc(prepare_tex(main_tex + '\n' + app + '\n' + markers), 'latex', True), 'html.parser')
    bibliography = converted.find(id='refs').extract()
    marker = converted.find(id='citationmarkers'); paragraph = marker.find_next('p')
    av, abc, tb = map(str, paragraph.select('span.citation'))
    marker.extract(); paragraph.extract()
    blocks = {name: [] for name in ('abstract', 'opening', 'runtime', 'discussion', 'appendix')}
    starts = {'abstract':'abstract', 'sec:introduction':'opening', 'sec:runtime':'runtime',
              'sec:discussion':'discussion', 'app:runtime':'appendix'}
    target = 'abstract'
    for node in list(converted.contents):
        if getattr(node, 'attrs', None) and node.get('id') in starts:
            target = starts[node['id']]
        blocks[target].append(str(node))
    parts = {name: BeautifulSoup(''.join(nodes), 'html.parser') for name, nodes in blocks.items()}
    heading = parts['abstract'].find('h1'); heading.name = 'h2'; heading['class'] = ['abstract-heading']
    parts['opening'] = BeautifulSoup(str(parts['opening']).replace('<p>CASEFIGUREPLACEHOLDER</p>', case_figure()).replace('<p>COMPARISONTABLEPLACEHOLDER</p>', comparison_table()), 'html.parser')
    number_sections(parts['opening'], 1)
    parts['runtime'] = BeautifulSoup(str(parts['runtime']).replace('<p>ARCHITECTUREFIGUREPLACEHOLDER</p>', architecture_figure()), 'html.parser')
    number_sections(parts['runtime'], 4)
    number_sections(parts['discussion'], 7)
    parts['appendix'] = BeautifulSoup(str(parts['appendix']).replace('<p>RUNTIMEFIGUREPLACEHOLDER</p>', runtime_figure()), 'html.parser')
    number_sections(parts['appendix'], 1, appendix=True)
    prepare_runtime_tables(parts['appendix'])
    labels = {'sec:introduction':'1', 'sec:related-work':'2', 'sec:task-design':'3',
              'sec:task-formulation':'3.1', 'sec:case-construction':'3.3', 'sec:runtime':'4',
              'sec:measurement':'4', 'sec:cases':'5', 'sec:qc':'6', 'sec:discussion':'7',
              'app:runtime':'H', 'app:runtime-overview':'H.1', 'app:runtime-replay':'H.2',
              'app:runtime-cases':'H.3', 'app:runtime-limits':'H.4', 'fig:runtime':'H.1', 'fig:architecture':'4.1',
              'tab:cli-controls':'H.1', 'tab:case-paths':'H.2'}
    body = '<div class="abstract">' + str(parts['abstract']) + '</div>'
    body += str(parts['opening']) + str(parts['runtime'])
    body += user_html(markdown_body('paper_case_studies.md')) + user_html(markdown_body('paper_qc_design.md'))
    body += str(parts['discussion']) + '<h2 id="references" class="references-heading">References</h2>' + str(bibliography)
    body += '<div class="appendices">' + user_html(markdown_body('paper_appendix_case_specs.md') + '\n\n' + markdown_body('paper_appendix_details.md')) + str(parts['appendix']) + '</div>'
    soup = BeautifulSoup(body.replace('[AV]', av).replace('[ABC]', abc).replace('[TB]', tb), 'html.parser')
    for link in soup.find_all('a', attrs={'data-reference':True}):
        key = link['data-reference']; link.clear(); link.append(labels[key]); link['href'] = '#' + key
    for heading in soup.find_all(['h2','h3','h4']):
        title = heading.get_text(' ',strip=True)
        if title.startswith('5. Case studies'): heading['id'] = 'sec:cases'
        elif title.startswith('6. Quality control'): heading['id'] = 'sec:qc'
        elif title.startswith('Appendix '):
            letter = re.match(r'Appendix ([A-H])',title)[1]
            if letter != 'H': heading['id'] = 'appendix-' + letter
        elif re.match(r'^[A-G]\.\d+\b',title): heading['id'] = 'appendix-' + title.split()[0]
    for paragraph in soup.find_all('p'):
        title = paragraph.get_text(' ',strip=True); match = re.match(r'^Table ([A-G1-9]\.[0-9]+)\.',title)
        if match:
            paragraph['class'] = ['caption']; paragraph['id'] = 'table-' + match[1]
            table = paragraph.find_next_sibling('table')
            if table: table['class'] = ['table-' + match[1].replace('.','-')]
    # Procurement's results figure: each plotted value is recomputed from pinned read-outs by the script.
    v3_image = soup.find('img', src='figures/procurement_v3_gap_closed.svg')
    assert v3_image is not None
    v3_marker = v3_image.find_parent('p')
    v3_caption = v3_marker.find_next_sibling('p')
    assert v3_caption.get_text().startswith('Figure 5.1.')
    v3_figure = soup.new_tag('figure', attrs={'id':'fig-procurement-v3','class':'procurement-figure'})
    v3_figure.append(v3_image.extract())
    v3_figcaption = soup.new_tag('figcaption')
    for child in list(v3_caption.contents): v3_figcaption.append(child.extract())
    v3_figure.append(v3_figcaption)
    v3_caption.decompose()
    v3_marker.replace_with(v3_figure)
    v3_checks = json.loads((ROOT/'figures/PROCUREMENT_V3_FIGURE_CHECKS.json').read_text())
    assert hashlib.sha256((ROOT/'figures/plot_procurement_v3.py').read_bytes()).hexdigest() == v3_checks['script_sha256']
    assert hashlib.sha256((ROOT/'figures/procurement_v3_gap_closed.svg').read_bytes()).hexdigest() == v3_checks['svg_sha256']
    assert (SOURCE/'figures/procurement_v3_gap_closed.svg').read_bytes() == (ROOT/'figures/procurement_v3_gap_closed.svg').read_bytes()
    for name, meta in v3_checks['sources']['files'].items():
        assert hashlib.sha256((ROOT/'analysis_evidence/procurement_v3'/name).read_bytes()).hexdigest() == meta['sha256']
    assert [round(r['mean'], 2) for r in v3_checks['rows'][:2]] == [0.35, 0.0]
    # A source-bound figure leads the main results; exact values stay in E.10.
    source_image = soup.find('img', src='figures/shortfall_by_case.svg')
    assert source_image is not None
    marker = source_image.find_parent('p')
    caption = marker.find_next_sibling('p')
    assert caption.get_text().startswith('Figure 5.2.')
    figure = soup.new_tag('figure', attrs={'id':'fig-shortfall','class':'shortfall-figure'})
    image = source_image.extract()
    figure.append(image)
    figure_caption = soup.new_tag('figcaption')
    for child in list(caption.contents): figure_caption.append(child.extract())
    figure.append(figure_caption)
    caption.decompose()
    marker.replace_with(figure)
    figure_checks = json.loads((ROOT/'figures/FIGURE_CHECKS.json').read_text())
    assert hashlib.sha256((ROOT/figure_checks['source']).read_bytes()).hexdigest() == figure_checks['source_sha256']
    assert hashlib.sha256((ROOT/'figures/shortfall_by_case.svg').read_bytes()).hexdigest() == figure_checks['svg_sha256']
    assert (SOURCE/'figures/shortfall_by_case.svg').read_bytes() == (ROOT/'figures/shortfall_by_case.svg').read_bytes()
    assert len(figure_checks['bars']) == 13
    # One numbered appendix table, four panels in the same order as the figure.
    caption = soup.find(id='table-E.10')
    panel_names = ['(a) Housing', '(b) Procurement', '(c) Data center', '(d) Refund']
    wrapper = soup.new_tag('div', attrs={'class':'shortfall-table'})
    caption.insert_before(wrapper)
    first = caption.find_next_sibling('p')
    wrapper.append(caption.extract())
    grid = soup.new_tag('div', attrs={'class':'shortfall-panels'})
    wrapper.append(grid)
    for name in panel_names:
        assert first.get_text(' ',strip=True) == name, first
        basis = first.find_next_sibling('p')
        table = basis.find_next_sibling('table')
        note = table.find_next_sibling('p')
        following = note.find_next_sibling('p')
        panel = soup.new_tag('div', attrs={'class':'shortfall-panel'})
        grid.append(panel)
        first['class'] = ['panel-title']
        basis['class'] = ['panel-basis']
        table['class'] = ['shortfall-panel-table']
        note['class'] = ['panel-note']
        for node in (first,basis,table,note):
            panel.append(node.extract())
        first = following
    first['class'] = ['shortfall-note']
    wrapper.append(first.extract())
    assert len(grid.select('.shortfall-panel')) == 4
    assert len(grid.find_all('table')) == 4
    decomposition = json.loads((ROOT/'analysis_evidence/shortfall_panels/panels.json').read_text())
    for bar in figure_checks['bars']:
        values = decomposition[bar['case']][bar['subject']]['summary']
        assert abs(bar['total']-values['total']['mean']) < 1e-9
        for component in bar['components']:
            assert abs(component['value']-values[component['key']]['mean']) < 1e-9
    PROCUREMENT_KEYS = json.loads((ROOT/'figures/FIGURE_CHECKS.json').read_text())['procurement_table_keys']
    displayed_panels = [
        ('housing', ['Gemini 3.8 Flash','GPT-6 Luna','Sol 6.1 (Codex, addendum B)','Opus 5.5 (Claude Code, addendum B)','GLM 5.3 Flash (addendum A)'],
         ['information_not_acquired','contrary_to_information_held','worse_terms',
          'commitment_error','procedure_and_format','interaction_cost','total']),
        ('procurement', ['Sol 6.1 (Codex)','Opus 5.5 (Claude Code)','Gemini 3.8 Flash','GPT-6 Luna'],
         PROCUREMENT_KEYS),
        ('datacenter', ['Opus 5.5','Sol 6.1'],
         ['inferior_clauses','harmful_agreement','missed_deal','redline_fees','total']),
        ('refund', ['GPT-5.6 Luna','Gemini 2.5 Flash Lite'],
         ['information_not_acquired','procedure_and_format','total']),
    ]
    displayed_means = 0
    for panel, (case, names, keys) in zip(grid.select('.shortfall-panel'), displayed_panels, strict=True):
        for row, key in zip(panel.select('tbody tr'), keys, strict=True):
            for cell, name in zip(row.find_all('td')[1:], names, strict=True):
                expected = decomposition[case][name]['summary'][key]['mean']
                assert cell.get_text(strip=True).replace('−', '-') == f'{expected:.1f}', (case,name,key)
                displayed_means += 1
    runtime_notes = 0
    for heading in soup.find_all('h4'):
        if ' '.join(heading.get_text(' ',strip=True).split()).startswith('Procurement: the decision-loss reference'):
            paragraph = heading.find_next_sibling('p')
            wrapper = soup.new_tag('div', attrs={'class':'runtime-case-note'})
            heading.insert_before(wrapper)
            wrapper.append(heading.extract())
            wrapper.append(paragraph.extract())
            runtime_notes += 1
    assert runtime_notes == 1, 'Expected one Procurement runtime note'
    for link in soup.find_all('a', href=True):
        if not link['href'].startswith(('https:', 'http:', '#')): link.unwrap()
    ids = [tag['id'] for tag in soup.find_all(id=True)]
    assert len(ids) == len(set(ids)), 'Duplicate internal IDs'
    missing = sorted({a['href'][1:] for a in soup.find_all('a',href=True) if a['href'].startswith('#') and a['href'][1:] not in ids})
    assert not missing, missing
    assert len(parts['appendix'].find_all('h3')) == 4
    assert not re.search(r'\bH\.(?:[5-9]|1[0-2])\b', soup.get_text())
    assert len(soup.find_all(id='fig:case')) == 1 and len(soup.select('table.table-2-1')) == 1
    assert 'PLACEHOLDER' not in soup.get_text()
    checks = {'case_figures':len(soup.find_all(id='fig:case')), 'comparison_rows':len(soup.select('table.table-2-1 tbody tr')),
              'architecture_figures':len(soup.find_all(id='fig:architecture')),
              'shortfall_panels':len(grid.select('.shortfall-panel')),
              'shortfall_figure_bars_verified':len(figure_checks['bars']),
              'shortfall_displayed_means_verified':displayed_means,
              'runtime_tables':len(parts['appendix'].find_all('table')),
              'runtime_subsections':4, 'references':len(bibliography.select('.csl-entry')),
              'missing_internal_links':missing, 'duplicate_ids':[],
              'runtime_words':len(parts['appendix'].get_text(' ',strip=True).split()),
              'abstract_words':len(parts['abstract'].get_text(' ',strip=True).split()),
              'discussion_words':len(parts['discussion'].get_text(' ',strip=True).split())}
    assert checks['runtime_tables'] == 2
    title = 'AERead: Evaluating Economic Decisions in Interactive Environments'
    version = json.loads((SOURCE / 'version.json').read_text())
    subtitle = (f"Research working paper · version {version['version']} · {version['date']} · "
                'Preliminary results; feedback and contributions welcome')
    authors = json.loads((SOURCE / 'authors.json').read_text())
    full = document(title, subtitle, str(soup), styles, authors=authors)
    page = OUT.with_suffix('.html'); page.write_text(full)
    result = subprocess.run([CHROME,'--headless=new','--disable-gpu','--no-pdf-header-footer',f'--print-to-pdf={OUT}',page.resolve().as_uri()],capture_output=True,text=True)
    if not OUT.exists() or OUT.stat().st_mtime < page.stat().st_mtime:
        raise RuntimeError(result.stderr[-4000:])
    writer = PdfWriter(clone_from=PdfReader(OUT))
    writer.add_metadata({'/Author': '; '.join(authors), '/Title': title, '/Subject': f"Version {version['version']}, {version['date']}"})
    stamped = OUT.with_suffix('.metadata.pdf')
    writer.write(stamped)
    stamped.replace(OUT)
    # Retain the original technical material outside the shortened paper appendix.
    supplement_root = ROOT / 'technical_supplement'
    legacy = (supplement_root / 'app_runtime.tex').read_text()
    for name in ('tab_families','tab_case_paths'):
        legacy = legacy.replace(r'\input{' + name + '}', (supplement_root / f'{name}.tex').read_text())
    legacy = re.sub(r'\\begin\{figure\}.*?\\end\{figure\}', 'RUNTIMEFIGUREPLACEHOLDER', legacy, flags=re.S)
    technical = BeautifulSoup(pandoc(prepare_tex(legacy),'latex',True),'html.parser')
    technical = BeautifulSoup(str(technical).replace('<p>RUNTIMEFIGUREPLACEHOLDER</p>',runtime_figure()),'html.parser')
    number_sections(technical,1,appendix=True); prepare_runtime_tables(technical)
    legacy_labels = dict(labels, **{'tab:families':'H.1','tab:family-fidelity':'H.2','tab:case-paths':'H.3'})
    for i, heading in enumerate(technical.find_all('h3'),1):
        if heading.get('id'): legacy_labels[heading['id']] = f'H.{i}'
    technical_ids = {tag['id'] for tag in technical.find_all(id=True)}
    for link in technical.find_all('a',attrs={'data-reference':True}):
        key=link['data-reference']; link.clear(); link.append(legacy_labels[key])
        link['href']=('#' if key in technical_ids else '../'+page.name+'#')+key
    note='<p class="note">Full technical reference retained from the previous draft, including its original H.1-H.12 numbering. The paper now has a separate condensed H.1-H.4. This reference preserves the original dated review scope; it is not an updated campaign audit.</p>'
    supplement_styles = styles + '''
    .runtime-table-1 { break-inside:auto; }
    .runtime-table-1 th:nth-child(1) { width:22%; }
    .runtime-table-1 th:nth-child(2) { width:26%; }
    .runtime-table-1 th:nth-child(3) { width:45%; }
    .runtime-table-1 th:nth-child(4) { width:7%; }
    .runtime-table-2 th:nth-child(1) { width:22%; }
    .runtime-table-2 th:nth-child(2) { width:31%; }
    .runtime-table-2 th:nth-child(3) { width:47%; }
    .runtime-table-3 th:nth-child(1) { width:20%; }
    .runtime-table-3 th:nth-child(2) { width:32%; }
    .runtime-table-3 th:nth-child(3) { width:48%; }
    '''
    (supplement_root/'runtime_technical_reference.html').write_text(document('AERead runtime: retained technical reference','Source review dated 14 October 2026',note+str(technical),supplement_styles))
    # Editable reading copy of the complete main text and its references.
    reading=BeautifulSoup(str(soup),'html.parser'); reading.find('div',class_='appendices').extract()
    for tag in reading.find_all(attrs={'role':True}): del tag['role']
    for tag in reading.select('span.citation,div'): tag.unwrap()
    md=subprocess.run(['pandoc','-f','html','-t','gfm','--wrap=none'],input=str(reading),capture_output=True,text=True,check=True).stdout
    (ROOT/'complete_main_text.md').write_text(md.replace('$`\\tau^2`$','τ²'))
    (ROOT/'HTML_CHECKS.json').write_text(json.dumps(checks,indent=2)+'\n')
    print(OUT); print(json.dumps(checks))


if __name__ == '__main__':
    main()


