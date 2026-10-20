"""Plot Figure 5.1: on the 20 declared worlds, the share of the pay-to-best gap each subject closes, world by world.

Run from the draft directory: uv run --with matplotlib python figures/plot_procurement_v3.py
Inputs are the sealed read-outs and packs in analysis_evidence/procurement_v3/ (SOURCES.json names the commits and
digests). Every plotted value is a per-world mean, the basis the text and Table 5.3 use; the script recomputes each
summary and asserts it against the published one before drawing.
"""
from pathlib import Path
import hashlib
import json
import statistics

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

ROOT = Path(__file__).resolve().parent
EVIDENCE = ROOT.parent/'analysis_evidence/procurement_v3'
SOURCES = json.loads((EVIDENCE/'SOURCES.json').read_text())
for name, meta in SOURCES['files'].items():
    assert hashlib.sha256((EVIDENCE/name).read_bytes()).hexdigest() == meta['sha256'], name

plt.rcParams.update({
    'font.family':'DejaVu Sans', 'font.size':9,
    'svg.fonttype':'path', 'svg.hashsalt':'aeread-procurement-v3-v1',
    'axes.edgecolor':'#9BA6AE', 'axes.linewidth':.6,
    'text.color':'#172A3A', 'axes.labelcolor':'#405366',
    'xtick.color':'#405366', 'ytick.color':'#172A3A',
})
SOL, OPUS, GEMINI, LUNA = '#367DAD', '#CC6946', '#8E5BA6', '#A8841A'
RULE, INK, MUTED = '#7B899B', '#172A3A', '#5B6B7A'


def load(name):
    return json.loads((EVIDENCE/name).read_text())


def world_means(readout, kind='myopic_pays'):
    by = {}
    for p in readout['plays_detail']:
        if p['kind'] == kind:
            by.setdefault(p['slug'], []).append(p['gap_closed'])
    return {slug: statistics.fmean(v) for slug, v in sorted(by.items())}


#: Student t 0.975 quantile at 19 degrees of freedom (20 worlds), as scipy.stats.t.ppf(0.975, 19) gives.
T19 = 2.0930240544


def interval(values):
    mean = statistics.fmean(values)
    half = T19 * statistics.stdev(values) / len(values) ** 0.5
    return mean, [mean - half, mean + half]


def rows():
    """The 20 declared worlds only: four subjects (each world the mean of its two plays) and two exact rules."""
    analysis = load('confirmatory_analysis.json')
    confirm = {w['slug']: w for w in load('confirm_pack.json')['worlds']}
    out = []
    for label, name, color in (('Sol 6.1 (Codex)', 'readout_sol61.json', SOL),
                               ('Opus 5.5 (Claude Code)', 'readout_opus55.json', OPUS),
                               ('Gemini 3.8 Flash', 'readout_gemini38_flash.json', GEMINI),
                               ('GPT-6 Luna', 'readout_gpt6_luna.json', LUNA)):
        readout = load(name)
        readout = readout[0] if isinstance(readout, list) else readout
        values = list(world_means(readout).values())
        assert len(values) == 20 and readout['failed'] == []
        mean, ci = interval(values)
        varies = max(values) - min(values) > 1e-3
        out.append(dict(label=label, values=values, color=color, mean=mean, ci=ci if varies else None,
                        interval='95% t interval' if varies else None))
    sol = out[0]
    assert abs(sol['mean'] - analysis['arm_a']['gap_closed_mean']) < 5e-4
    assert all(abs(x - y) < 5e-4 for x, y in zip(sol['ci'], analysis['arm_a']['t_ci95']))
    for w in confirm.values():  # the one-step rule pays the premium in every declared world
        assert abs(w['rule_loss_usd']['one_step_value'] - w['rule_loss_usd']['pay_premium']) < 0.01
    share = lambda rule: [1 - w['rule_loss_usd'][rule] / w['rule_loss_usd']['pay_premium'] for w in confirm.values()]  # noqa: E731
    shortcut, two_step = share('cheapest_sample_first'), share('two_step_value')
    assert abs(statistics.fmean(shortcut) - 0.334) < 1e-3
    out += [dict(label='Shortcut: cheapest\nsample first (exact)', values=shortcut, color=RULE,
                 mean=statistics.fmean(shortcut), ci=None, interval=None),
            dict(label='A rule that may test\ntwo newcomers (exact)', values=two_step, color=RULE,
                 mean=statistics.fmean(two_step), ci=None, interval=None)]
    return out


def main():
    data = rows()
    fig, ax = plt.subplots(figsize=(7.6, 3.55), facecolor='white')
    fig.subplots_adjust(left=.265, right=.975, top=.86, bottom=.15)
    n = len(data)
    for i, row in enumerate(data):
        y = n - 1 - i
        vals = [0.0 if abs(v) < 1e-3 else 100 * v for v in row['values']]  # rounding noise only; real negatives stay
        offsets = [((k % 5) - 2) * .055 for k in range(len(vals))]
        ax.scatter(vals, [y + o for o in offsets], s=22, color=row['color'], alpha=.55, linewidths=0, zorder=3)
        m = 100 * row['mean']
        if row['ci'] is not None:
            lo, hi = (100 * c for c in row['ci'])
            ax.plot([lo, hi], [y, y], color=INK, lw=1.6, zorder=4, solid_capstyle='round')
            ax.plot([m], [y], marker='D', ms=6.5, color=INK, zorder=5)
            ax.text(m, y + .3, f'{m:.0f}% [{lo:.0f}, {hi:.0f}]'.replace('-', '\u2212'), va='center', ha='center', fontsize=8.5, color=INK)
        else:
            ax.plot([m], [y], marker='D', ms=6.5, color=INK, zorder=5)
            if max(abs(v) for v in row['values']) < 1e-3:
                ax.text(3, y + .3, '0% in every world', va='center', ha='left', fontsize=8.5, color=MUTED)
            else:
                ax.text(m, y + .3, f'{m:.0f}% on average', va='center', ha='center', fontsize=8.5, color=MUTED)
    ax.set_yticks(range(n))
    ax.set_yticklabels([r['label'] for r in reversed(data)], fontsize=8.5)
    low = min(100 * min(v for r in data for v in r['values']), 0)
    ax.set_xlim(min(-6, low - 6), 112)
    ax.set_ylim(-.7, n - .4)
    ticks = [t for t in (-50, -25, 0, 25, 50, 75, 100) if t >= min(-6, low - 6)]
    ax.set_xticks(ticks)
    ax.set_xticklabels([f'{t}%'.replace('-', '\u2212') for t in ticks])
    ax.set_xlabel('Share of the gap between paying the premium and the best policy closed, per world', fontsize=8.5)
    for x, text, align in ((0, 'paying the premium\n= the one-step rule', 'left'),
                           (100, 'the best policy, given\nwhat the buyer knows', 'right')):
        ax.axvline(x, color='#9BA6AE', lw=.8, ls=(0, (3, 2)), zorder=1)
        ax.text(x + (-1 if align == 'right' else 1), n - .25, text, ha=align, va='bottom', fontsize=8, color=MUTED)
    for side in ('top', 'right'):
        ax.spines[side].set_visible(False)
    ax.grid(axis='x', color='#E3E7EA', lw=.5, zorder=0)
    ax.tick_params(axis='y', length=0)
    svg, png = ROOT/'procurement_v3_gap_closed.svg', ROOT/'procurement_v3_gap_closed.png'
    fig.savefig(svg, format='svg', metadata={'Date': None})
    fig.savefig(png, format='png', dpi=200, metadata={'Software': None})
    plt.close(fig)
    (ROOT.parent/'source/figures'/svg.name).write_bytes(svg.read_bytes())
    checks = {
        'figure': 'Figure 5.1', 'table': 'Table 5.3', 'sources': SOURCES,
        'script_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        'svg_sha256': hashlib.sha256(svg.read_bytes()).hexdigest(),
        'png_sha256': hashlib.sha256(png.read_bytes()).hexdigest(),
        'rows': [{'label': r['label'].replace('\n', ' '), 'worlds': len(r['values']), 'mean': round(r['mean'], 4),
                  'ci': r['ci'], 'interval': r['interval'], 'values': [round(v, 4) for v in r['values']]} for r in data],
    }
    (ROOT/'PROCUREMENT_V3_FIGURE_CHECKS.json').write_text(json.dumps(checks, indent=1) + '\n')
    print(json.dumps([{k: v for k, v in r.items() if k != 'values'} for r in checks['rows']], indent=1))


if __name__ == '__main__':
    main()
