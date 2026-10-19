"""Draw Figure 1.1: the three levels of an AERead evaluation, labelled with the properties of Section 1.

Run: uv run --with matplotlib python figures/plot_evaluation_levels.py
Levels, left to right: the runtime hosting case families; one case's population of admitted worlds;
one world. Zoom lines mean "contains", not a sequence. Example values are the Data-center agreement's
(Table 5.1, Section 5.1, Appendix F.2). The admitted/rejected dot pattern and the score bar are schematic.
"""
from pathlib import Path
import hashlib
import json

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch, FancyArrowPatch, Circle, Rectangle

ROOT = Path(__file__).resolve().parent
plt.rcParams.update({'font.family': 'DejaVu Sans', 'svg.fonttype': 'path',
                     'svg.hashsalt': 'aeread-evaluation-levels-v15'})
INK = '#172A3A'
MUTED = '#405366'
TEAL = '#38968A'
BLUE = '#367DAD'
GOLD = '#A77A23'
ZOOM = '#9AA7B2'


def main():
    fig = plt.figure(figsize=(7.8, 3.25), facecolor='white')
    ax = fig.add_axes([0, 0, 1, 1])
    ax.set_xlim(0, 1000)
    ax.set_ylim(416, 0)
    ax.axis('off')

    def box(x, y, w, h, color, fill, radius=6, lw=.8):
        ax.add_patch(FancyBboxPatch((x, y), w, h, boxstyle=f'round,pad=0,rounding_size={radius}',
                                    linewidth=lw, edgecolor=color, facecolor=fill))

    def label(x, y, s, size=7.6, bold=False, color=INK, align='left', rotation=0):
        ax.text(x, y, s, fontsize=size, color=color, weight='bold' if bold else 'normal',
                ha=align, va='center', rotation=rotation)

    def arrow(start, end, color=MUTED):
        ax.add_patch(FancyArrowPatch(start, end, arrowstyle='-|>', mutation_scale=6,
                                     linewidth=.7, color=color, shrinkA=0, shrinkB=0))

    def properties(x, y, color, lines):
        row = 0
        for line in lines:
            parts = line.split('\n')
            ax.add_patch(Rectangle((x, y + 17 * row - 3.5), 7, 7, facecolor=color, edgecolor='none'))
            for part in parts:
                label(x + 13, y + 17 * row, part, 6.9, True, color)
                row += 1
            row += 0.35

    top, bottom = 44, 396
    panels = [(12, 296, TEAL, '#F3F9F7', 'RUNTIME'),
              (352, 292, BLUE, '#F2F7FB', 'ONE CASE: ITS WORLDS'),
              (690, 298, GOLD, '#FBF8EF', 'ONE WORLD')]
    for x, w, color, fill, title in panels:
        box(x, top, w, bottom - top, color, fill)
        label(x + 2, 25, title, 7.6, True, color)

    # Runtime: one kernel hosting several families.
    box(26, 62, 36, 240, TEAL, 'white', 4)
    label(44, 182, 'Kernel: plan, play, seal, replay', 6.2, True, TEAL, 'center', 90)
    families = ['Housing', 'Procurement', 'Data center', 'Refund', 'TERMS-Bench, reimplemented']
    for i, name in enumerate(families):
        y = 62 + 49 * i
        highlight = name == 'Data center'
        box(76, y, 216, 42, BLUE if highlight else '#B9D5CE', '#F2F7FB' if highlight else 'white', 4,
            1.2 if highlight else .8)
        label(90, y + 21, name, 6.9, highlight)
        ax.plot([62, 76], [y + 21, y + 21], color='#B9D5CE', linewidth=.8)
    properties(26, 330, TEAL, ['One runtime, several activities', 'Scores recomputed from\nsealed evidence'])

    # One case: candidate worlds from the generator, admitted ones filled.
    rejected = {(0, 1), (1, 3), (2, 0), (2, 6), (3, 4), (4, 2), (4, 8), (1, 7), (3, 9), (0, 5)}
    chosen = (1, 9)
    for r in range(5):
        for c in range(10):
            cx, cy = 378 + 26 * c, 80 + 26 * r
            if (r, c) in rejected:
                ax.add_patch(Circle((cx, cy), 6.5, facecolor='white', edgecolor=ZOOM, linewidth=.8))
            else:
                ax.add_patch(Circle((cx, cy), 6.5, facecolor=BLUE, edgecolor='none'))
    ccx, ccy = 378 + 26 * chosen[1], 80 + 26 * chosen[0]
    ax.add_patch(Circle((ccx, ccy), 10.5, facecolor='none', edgecolor=GOLD, linewidth=1.4))
    ax.add_patch(Circle((374, 208), 5.5, facecolor=BLUE, edgecolor='none'))
    label(385, 208, 'admitted world', 6.6, color=MUTED)
    ax.add_patch(Circle((374, 226), 5.5, facecolor='white', edgecolor=ZOOM, linewidth=.8))
    label(385, 226, 'rejected by the admission rule', 6.6, color=MUTED)
    for i, line in enumerate(['Data center: 60 worlds admitted of', '2,729 scanned. The reference is',
                              'played on every admitted world.']):
        label(368, 254 + 15 * i, line, 6.6, color=MUTED)
    properties(368, 330, BLUE, ['World generator with admission', 'Quality control over the\npopulation of worlds'])

    # One world: the agent's seat against a counterpart seat, then the score against the reference.
    box(704, 58, 270, 46, GOLD, 'white', 4)
    label(716, 72, 'Agent seat', 7.0, True)
    label(716, 90, 'client or integrator; its own costs only', 6.5, color=MUTED)
    arrow((826, 106), (826, 122))
    arrow((852, 122), (852, 106))
    box(704, 124, 270, 46, GOLD, 'white', 4)
    label(716, 138, 'Counterpart seat', 7.0, True)
    label(716, 156, 'a script, another model or the same model', 6.5, color=MUTED)
    label(704, 186, 'Eight clauses and a price: redline, sign or walk', 6.5, color=MUTED)
    label(704, 208, 'Score against the full-information reference', 6.5, color=MUTED)
    segments = [(0.56, GOLD, 1.0), (0.14, '#8C6A2C', .55), (0.10, '#8C6A2C', .4), (0.08, '#8C6A2C', .28),
                (0.12, '#8C6A2C', .16)]
    x0, width = 704, 268
    for share, color, alpha in segments:
        ax.add_patch(Rectangle((x0, 220), width * share, 16, facecolor=color, alpha=alpha, edgecolor='white', linewidth=.6))
        x0 += width * share
    ax.plot([972, 972], [215, 241], color=INK, linewidth=1)
    label(704, 252, 'kept', 6.4, color=MUTED)
    label(856, 252, 'shortfall by class', 6.4, color=MUTED)
    label(704, 270, 'clauses, harm, missed deal, fees', 6.4, color=MUTED)
    properties(704, 306, GOLD, ['Counterpart is part of the case', 'Reference with stated\ninformation',
                                'Typed shortfall'])

    # Zoom lines: a family contains a population; a world is one member of it.
    tile_y = 62 + 49 * 2
    for ya, yb in ((tile_y, top), (tile_y + 42, bottom)):
        ax.plot([292, 352], [ya, yb], color=ZOOM, linewidth=.7, linestyle=(0, (3, 2)))
    for ya, yb in ((ccy - 10.5, top), (ccy + 10.5, bottom)):
        ax.plot([ccx + 8, 690], [ya, yb], color=ZOOM, linewidth=.7, linestyle=(0, (3, 2)))

    svg = ROOT / 'evaluation_levels.svg'
    png = ROOT / 'evaluation_levels.png'
    fig.savefig(svg, metadata={'Date': None, 'Creator': 'AERead evaluation levels'})
    fig.savefig(png, dpi=240)
    plt.close(fig)
    (ROOT.parent / 'source/figures' / svg.name).write_bytes(svg.read_bytes())
    checks = {
        'figure': 'Figure 1.1',
        'scope': 'Levels of an evaluation with the Data-center agreement as the example; dot pattern and score bar schematic',
        'script_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        'example_sources': ['source/paper_case_studies.md (Table 5.1, Section 5.1)',
                            'source/paper_appendix_details.md (F.2, admission before types)'],
        'svg_sha256': hashlib.sha256(svg.read_bytes()).hexdigest(),
        'png_sha256': hashlib.sha256(png.read_bytes()).hexdigest(),
    }
    (ROOT / 'LEVELS_FIGURE_CHECKS.json').write_text(json.dumps(checks, indent=2) + '\n')
    print('Figure 1.1 SVG and PNG generated')


if __name__ == '__main__':
    main()
