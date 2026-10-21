"""Plot the checked Table E.10 accounting as Figure 5.2, with native units.

Run from the draft directory: uv run --with matplotlib python figures/plot_shortfalls.py
Point estimates only; descriptive intervals remain in Table E.9.
"""
from pathlib import Path
import hashlib
import json

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.patches import Patch

ROOT = Path(__file__).resolve().parent
SOURCE = ROOT.parent/'analysis_evidence/shortfall_panels/panels.json'
DATA = json.loads(SOURCE.read_text())
plt.rcParams.update({
    'font.family':'DejaVu Sans', 'font.size':9,
    'svg.fonttype':'path', 'svg.hashsalt':'aeread-shortfalls-v11',
    'axes.edgecolor':'#9BA6AE', 'axes.linewidth':.6,
    'text.color':'#172A3A', 'axes.labelcolor':'#405366',
    'xtick.color':'#405366', 'ytick.color':'#172A3A',
    'hatch.linewidth':.5,
})

# Shared hues retain the broad meaning across cases; each panel names its
# own rules. Missed deals get a distinct tone and hatch from harmful deals.
INFO = '#367DAD'
CONTRARY = '#CC6946'
TERMS = '#38968A'
COMMIT = '#995E96'
COST = '#D5A23A'
PROCEDURE = '#7B899B'
PANELS = [
    dict(case='housing', title='(a) Housing', subtitle='Declared v15 · reachable scripted reference',
         names=['Gemini 3.8 Flash','GPT-6 Luna','Sol 6.1 (Codex, addendum B)','Opus 5.5 (Claude Code, addendum B)','GLM 5.3 Flash (addendum A)'],
         labels=['Gemini 3.8 Flash','GPT-6 Luna','Sol 6.1 (B)','Opus 5.5 (B)','GLM 5.3 Flash (A)'],
         sample='260 main worlds each; two landlord arms averaged', unit='Shortfall ($ / world)', legend_columns=3, legend_spacing=.6,
         limit=150, ticks=[0,50,100,150],
         parts=[('information_not_acquired','Info not acquired',INFO,''),
                ('contrary_to_information_held','Contrary to info',CONTRARY,''),
                ('worse_terms','Worse terms',TERMS,''),
                ('commitment_error','Commitment error',COMMIT,''),
                ('procedure_and_format','Procedure / format',PROCEDURE,''),
                ('interaction_cost','Inspection cost',COST,'')]),
    dict(case='procurement', title='(b) Procurement', subtitle='Declared worlds · best policy with available info',
         names=['Sol 6.1 (Codex)','Opus 5.5 (Claude Code)','Gemini 3.8 Flash','GPT-6 Luna'],
         labels=['Sol 6.1\n(Codex)','Opus 5.5\n(Claude Code)','Gemini 3.8\nFlash','GPT-6 Luna'],
         sample='20 worlds, two plays each', unit='Shortfall ($ / world)',
         limit=66, ticks=[0,20,40,60],
         parts=[('information_not_acquired','Info not acquired',INFO,''),
                ('contrary_to_information_held','Contrary to info',CONTRARY,''),
                ('worse_terms','Worse terms',TERMS,''),
                ('interaction_cost','Award checks',COST,'')]),
    dict(case='datacenter', title='(c) Data center', subtitle='Declared v2 · firm counterparts',
         names=['Opus 5.5','Sol 6.1'], labels=['Opus 5.5\n(Claude Code)','Sol 6.1\n(Codex)'],
         sample='80 worlds; two focal roles averaged', unit='Joint loss ($k / world)',
         limit=160, ticks=[0,50,100,150],
         parts=[('inferior_clauses','Inferior clauses',TERMS,''),
                ('harmful_agreement','Harmful agreement',COMMIT,''),
                ('missed_deal','Missed deal','#CAA4CB','///'),
                ('redline_fees','Redline fees',COST,'')]),
    dict(case='refund', title='(d) Refund', subtitle='Development V2.1 · full resolution',
         names=['GPT-5.6 Luna','Gemini 2.5 Flash Lite'],
         labels=['GPT-5.6 Luna','Gemini 2.5\nFlash Lite'],
         sample='6 fixed cases; 120 cells each', unit='Resolution shortfall (percentage points)',
         limit=115, ticks=[0,25,50,75,100],
         parts=[('information_not_acquired','Required facts skipped',INFO,''),
                ('procedure_and_format','Procedure / format',PROCEDURE,'')]),
]


def main():
    fig = plt.figure(figsize=(7.8,5.05),facecolor='white')
    checks=[]
    for i,panel in enumerate(PANELS):
        column=i%2; row=i//2
        x0=.015+column*.51
        ytop=.985-row*.51
        fig.text(x0,ytop,panel['title'],size=11,weight='bold',va='top')
        fig.text(x0,ytop-.041,panel['subtitle'],size=8.3,va='top',color='#405366')
        fig.text(x0,ytop-.077,panel['sample'],size=7.9,va='top',color='#596977')
        n=len(panel['names'])
        ax=fig.add_axes([x0+.122, ytop-.335, .342, .226])
        ax.set_xlim(0,panel['limit']);ax.set_ylim(-.5,n-.5)
        ax.set_yticks(list(reversed(range(n))),panel['labels'],fontsize=8.2)
        ax.tick_params(axis='y',length=0,pad=7)
        ax.set_xticks(panel['ticks']);ax.tick_params(axis='x',length=3,labelsize=8)
        ax.set_xlabel(panel['unit'],fontsize=8.3,labelpad=5)
        for edge in ('top','right','left'):ax.spines[edge].set_visible(False)
        ax.set_axisbelow(True)
        ax.grid(axis='x',color='#DEE4E8',linewidth=.6)
        for j,name in enumerate(panel['names']):
            values=DATA[panel['case']][name]['summary'];left=0.;drawn=0.
            components=[]
            for key,label,color,hatch in panel['parts']:
                value=values[key]['mean']
                # A negative component is not drawn; the caption and Table E.10 report it.
                assert value>-1.0,(panel['case'],name,key,value)
                if value>0:
                    ax.barh(n-1-j,value,left=drawn,height=.5,color=color,
                            edgecolor='white',linewidth=.45,hatch=hatch,zorder=3)
                    drawn+=value
                components.append(dict(key=key,value=value))
                left+=value
            total=values['total']['mean']
            assert abs(left-total)<1e-5,(panel['case'],name,left,total)
            ax.text(total+panel['limit']*.021,n-1-j,f'{total:.1f}',
                    va='center',ha='left',fontsize=9,weight='bold')
            checks.append(dict(case=panel['case'],subject=name,total=total,
                               components=components,axis_limit=panel['limit']))
        handles=[Patch(facecolor=c,edgecolor='white',hatch=h,label=l)
                 for _,l,c,h in panel['parts']]
        # Legends align to the panel's left edge, independently of model labels.
        fig.legend(handles=handles,loc='upper left',
                   bbox_to_anchor=(x0,ytop-.412),ncol=panel.get('legend_columns',2),frameon=False,
                   fontsize=7.9,handlelength=1.35,handleheight=.9,
                   handletextpad=.55,columnspacing=panel.get('legend_spacing',1.25),labelspacing=.55,
                   borderaxespad=0)
    svg=ROOT/'shortfall_by_case.svg'
    png=ROOT/'shortfall_by_case.png'
    fig.savefig(svg,metadata={'Date':None,'Creator':'AERead source-bound shortfall plot'})
    fig.savefig(png,dpi=240,metadata={'Software':'AERead source-bound shortfall plot'})
    # Keep the editable Markdown source's relative figure link usable as well.
    source_assets=ROOT.parent/'source/figures'
    source_assets.mkdir(exist_ok=True)
    (source_assets/svg.name).write_bytes(svg.read_bytes())
    plt.close(fig)
    report=dict(source=str(SOURCE.relative_to(ROOT.parent)),
                source_sha256=hashlib.sha256(SOURCE.read_bytes()).hexdigest(),
                figure='Figure 5.2', table='Table E.10',
                # The classes Table E.10's Procurement panel shows, in order; build.py checks each displayed mean.
                procurement_table_keys=[k for k,*_ in next(p for p in PANELS if p['case']=='procurement')['parts']]+['total'],
                component_sums_checked=len(checks), bars=checks,
                negative_component_policy='a negative component above -1 is not drawn and is reported in the caption and Table E.10 (Housing inspection cost: GLM 5.3 Flash -0.2, Sol 6.1 and Opus 5.5 -0.4); positive components stack from zero',
                uncertainty='Point estimates; descriptive intervals in Table E.9',
                svg_sha256=hashlib.sha256(svg.read_bytes()).hexdigest(),
                png_sha256=hashlib.sha256(png.read_bytes()).hexdigest())
    (ROOT/'FIGURE_CHECKS.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps({'bars':len(checks),'output':[str(svg),str(png)]}))


if __name__=='__main__':main()
