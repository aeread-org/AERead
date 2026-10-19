from pathlib import Path
import hashlib
import json
import re
import pymupdf
from bs4 import BeautifulSoup

base = Path('/Users/chenyusu/AERead/output/pdf')
current = base / 'aeread_working_draft_20261016_v4'
previous = base / 'aeread_working_draft_20261016_v3'
pdf = current / (current.name + '.pdf')
sha = lambda p: hashlib.sha256(p.read_bytes()).hexdigest()
old_manifest = json.loads((previous / 'SOURCE_MANIFEST.json').read_text())
assert sha(previous / old_manifest['pdf']['name']) == old_manifest['pdf']['sha256']
for relative, record in old_manifest['files'].items():
    assert sha(previous / relative) == record['sha256'], relative

doc = pymupdf.open(pdf)
texts = [page.get_text() for page in doc]
bounds = []
for number, page in enumerate(doc, 1):
    for block in page.get_text('dict')['blocks']:
        for line in block.get('lines', []):
            for span in line['spans']:
                x0, y0, x1, y1 = span['bbox']
                if min(x0, y0) < -0.5 or x1 > page.rect.width + 0.5 or y1 > page.rect.height + 0.5:
                    bounds.append({'page': number, 'bbox': span['bbox'], 'text': span['text']})
assert not bounds, bounds
assert not any('\ufffd' in text for text in texts)
headings = [
    '1. Introduction', '2. Related work', '3. Task design and construction',
    '4. Shared runtime and evaluation harness', '5. Case studies',
    '6. Quality control', '7. Discussion and conclusion', 'References',
    'Appendix A. Case specifications', 'Appendix E. Case details',
    'Appendix F. Quality control in detail', 'Appendix G. Artifacts',
    'Appendix H. Runtime contract and experimental coverage',
]
sections = {}
for heading in headings:
    pages = [i for i, text in enumerate(texts, 1) if re.search(r'^' + re.escape(heading) + r'$', text, re.M)]
    assert pages, heading
    sections[heading] = pages[0]

def tables(folder):
    soup = BeautifulSoup((folder / (folder.name + '.html')).read_text(), 'html.parser')
    result = {}
    for caption in soup.select('p[id^="table-"]'):
        table = caption.find_next('table')
        result[caption['id']] = (' '.join(caption.stripped_strings), ' '.join(table.stripped_strings))
    return result

old_tables, new_tables = tables(previous), tables(current)
assert old_tables.keys() == new_tables.keys()
unchanged = [key for key in old_tables if old_tables[key] == new_tables[key]]
changed = [key for key in old_tables if old_tables[key] != new_tables[key]]
data_changed = [key for key in old_tables if old_tables[key][1] != new_tables[key][1]]
for key in ['table-5.2', 'table-5.3', 'table-E.3', 'table-E.4', 'table-E.5', 'table-E.6']:
    assert old_tables[key][1] == new_tables[key][1], key
assert len(doc) == 40
assert len(doc) - sections[headings[-1]] + 1 == 4
assert (current / 'source/sec_discussion.tex').read_bytes() == (previous / 'source/sec_discussion.tex').read_bytes()

checks = {
    'pages': len(doc), 'section_pages': sections,
    'appendix_H_pages': 4, 'bounds_issues': bounds, 'replacement_character_count': 0,
    'unchanged_tables_from_v3': unchanged, 'changed_tables_from_v3': changed,
    'changed_table_bodies_from_v3': data_changed,
    'pdf_sha256': sha(pdf),
    'visual_review': {
        'all_pages': '40 pages rendered and inspected in contact sheets; final page 7 formatting inspected separately',
        'detailed_pages': [2, 7, 23, 28, 29, 32, 35, 39, 40],
        'detail_render_max_dimension_px': 1400, 'issues_remaining': [],
    },
    'previous_v3_manifest_files_and_pdf_preserved': True,
    'section7_unchanged_from_v3': True,
    'verification_scope': 'PDF structure and layout; scientific checks recorded in analysis_evidence/campaign_refresh/review',
}
(current / 'PDF_CHECKS.json').write_text(json.dumps(checks, indent=2) + '\n')
print(json.dumps(checks, indent=2))
