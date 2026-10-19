"""Draw Figure 4.1 from the paper's case, runtime and measurement contracts.

Run: uv run --with matplotlib python figures/plot_architecture.py
The overview describes responsibilities; it does not certify campaign coverage.
"""
from pathlib import Path
import hashlib
import json

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch, FancyArrowPatch

ROOT = Path(__file__).resolve().parent
plt.rcParams.update({'font.family': 'DejaVu Sans', 'svg.fonttype': 'path',
                     'svg.hashsalt': 'aeread-architecture-v11'})
INK = '#172A3A'
MUTED = '#405366'
BLUE = '#367DAD'
TEAL = '#38968A'
GOLD = '#A77A23'


def main():
    fig = plt.figure(figsize=(7.8, 2.55), facecolor='white')
    ax = fig.add_axes([0, 0, 1, 1])
    ax.set_xlim(0, 1000)
    ax.set_ylim(326, 0)
    ax.axis('off')

    def box(x, y, w, h, color, fill, radius=7):
        ax.add_patch(FancyBboxPatch((x, y), w, h,
                     boxstyle=f'round,pad=0,rounding_size={radius}',
                     linewidth=.8, edgecolor=color, facecolor=fill))

    def label(x, y, s, size=8.5, bold=False, color=INK, align='left'):
        return ax.text(x, y, s, fontsize=size, color=color,
                       weight='bold' if bold else 'normal', ha=align, va='center')

    def arrow(start, end, color=MUTED):
        ax.add_patch(FancyArrowPatch(start, end, arrowstyle='-|>',
                     mutation_scale=7, linewidth=.8, color=color,
                     shrinkA=0, shrinkB=0))

    label(12, 15, 'CASE DESIGN', 9, True, BLUE)
    label(280, 15, 'SHARED EXECUTION', 9, True, TEAL)
    label(731, 15, 'EVIDENCE + MEASUREMENT', 9, True, GOLD)

    box(12, 35, 225, 230, BLUE, '#F2F7FB')
    label(28, 61, 'Case family', 9.5, True)
    for y, line in zip([96, 126, 156, 186], [
            'Worlds + private types', 'Seats + information rules',
            'Actions + transitions', 'References + verifiers']):
        label(28, y, line)
    ax.plot([28, 221], [209, 209], color='#BCD0DF', linewidth=.6)
    label(28, 230, 'Admitted world pack', 7.7, color=MUTED)
    label(28, 248, 'Reference access is explicit', 7.7, color=MUTED)

    box(280, 35, 405, 230, TEAL, '#F3F9F7')
    box(295, 49, 375, 59, '#B9D5CE', 'white', 4)
    label(309, 68, 'Resolved run plan', 9, True)
    label(309, 91, 'Worlds, seats, agent settings, seeds, budgets', 7.8, color=MUTED)
    arrow((482, 110), (482, 130), TEAL)

    box(295, 137, 145, 80, TEAL, 'white', 4)
    label(367.5, 159, 'Environment', 8.7, True, align='center')
    label(367.5, 183, 'World state', 8, align='center')
    label(367.5, 201, 'Case transitions', 8, align='center')
    box(526, 137, 144, 80, TEAL, 'white', 4)
    label(598, 159, 'Seat policies', 8.7, True, align='center')
    label(598, 183, 'Focal agent', 8, align='center')
    label(598, 201, 'Counterparts', 8, align='center')
    arrow((444, 165), (522, 165), TEAL)
    label(483, 152, 'Observe', 7.2, color=MUTED, align='center')
    arrow((522, 200), (444, 200), TEAL)
    label(483, 186, 'Act', 7.2, color=MUTED, align='center')
    label(482.5, 237, 'Kernel schedules and records; drivers connect agents',
          7.4, color=MUTED, align='center')
    label(482.5, 254, 'Policies receive only their seat observations',
          7.4, color=MUTED, align='center')

    arrow((240, 177), (276, 177), BLUE)
    arrow((689, 177), (723, 177), TEAL)

    box(728, 35, 260, 230, GOLD, '#FBF8EF')
    label(744, 61, 'Sealed execution', 9, True)
    label(744, 84, 'Events, actions, receipt', 8, color=MUTED)
    arrow((858, 96), (858, 117), GOLD)
    label(744, 133, 'Receipt replay', 9, True)
    label(744, 156, 'Rebuild state + receipt scores', 7.8, color=MUTED)
    ax.plot([744, 972], [176, 176], color='#DDD2B3', linewidth=.6)
    label(744, 198, 'Headline analysis', 8.5, True)
    label(744, 221, 'Case reference + native units', 7.8, color=MUTED)
    label(744, 247, 'Extra derivations verified separately', 7.3, color=MUTED)

    box(12, 283, 976, 37, '#BDC7CF', '#F5F7F9', 4)
    label(27, 301, 'Campaign QC', 8.3, True)
    label(170, 301, 'World validity and headroom  /  controls  /  frozen analysis  /  incident review',
          8, color=MUTED)

    svg = ROOT/'architecture_overview.svg'
    png = ROOT/'architecture_overview.png'
    fig.savefig(svg, metadata={'Date': None, 'Creator': 'AERead architecture overview'})
    fig.savefig(png, dpi=240)
    plt.close(fig)
    (ROOT.parent/'source/figures'/svg.name).write_bytes(svg.read_bytes())
    source_files = ['sec_opening.tex', 'sec_runtime.tex', 'app_runtime.tex',
                    'paper_qc_design.md', 'tab_case_paths.tex']
    checks = {
        'figure': 'Figure 4.1',
        'scope': 'Conceptual architecture; applied coverage varies by campaign',
        'sources': {f'source/{p}': hashlib.sha256(
            (ROOT.parent/'source'/p).read_bytes()).hexdigest() for p in source_files},
        'svg_sha256': hashlib.sha256(svg.read_bytes()).hexdigest(),
        'png_sha256': hashlib.sha256(png.read_bytes()).hexdigest(),
    }
    (ROOT/'ARCHITECTURE_CHECKS.json').write_text(json.dumps(checks, indent=2)+'\n')
    print('Figure 4.1 SVG and PNG generated')


if __name__ == '__main__':
    main()
