"""Re-apply the run-order changes onto a base copy of the examiner page (idempotent anchors)."""
import sys
src, dst = sys.argv[1], sys.argv[2]
s = open(src).read()
# strip the publish wrapper if present
if s.startswith('<!doctype html>'):
    s = s.split('\n', 1)[1]
s = s.rstrip()
if s.endswith('</body></html>'):
    s = s[:-len('</body></html>')].rstrip() + '\n'
if not s.startswith('<meta charset="utf-8">'):
    s = '<meta charset="utf-8">\n' + s
def rep(old, new):
    global s
    assert s.count(old) == 1, (old[:70], s.count(old)); s = s.replace(old, new)
# CSS
rep(".banner{", ".basis{font-size:10.5px;color:var(--muted);white-space:nowrap}table.order td.what{white-space:normal;min-width:220px;max-width:300px;font-size:12px}table.order td.lin{white-space:normal;min-width:120px;font-size:11.5px}table.order td.idc{white-space:normal;min-width:230px;max-width:300px;overflow-wrap:anywhere}table.order td.ran{white-space:nowrap}.runline{display:flex;flex-wrap:wrap;gap:6px 10px;align-items:center;margin:6px 0 2px;font-size:12.5px}.runline button{padding:3px 8px;font-size:12px}.runline .mono{font-size:12px}\n.banner{")
# renderCatalog body
start = s.index("  const list=CAT.campaigns.filter(c=>c.family===route.family);\n  const stems={};")
end = s.index("  const famRows=(CAT.family_incidents[route.family]||[]);")
new_block = '''  const mode=route.catalogOrder||'time';
  const list=CAT.campaigns.filter(c=>c.family===route.family).slice().sort((a,b)=>((a.order||{}).rank||1e9)-((b.order||{}).rank||1e9));
  const cellsOf=c=>{const g=c.grain||{};const planned=(c.facts.find(f=>f.key==='planned_cells')||{}).value,done=(c.facts.find(f=>f.key==='completed_cells')||{}).value;return planned!=null?`${done??'?'} / ${planned}`:(g.cases!=null?`${g.cases} cases`:(g.legacy_rows?`${g.legacy_rows} rows`:'—'));};
  const issuesOf=c=>c.issues.length?`${c.issues.length}${c.issues.some(i=>i.state==='open')?` <span class="chip no">${c.issues.filter(i=>i.state==='open').length} open</span>`:''}`:'<span class="muted">none</span>';
  const costOf=c=>{const g=c.grain||{};return c.manifest.total_cost_usd!=null?money(c.manifest.total_cost_usd):(g.cost_usd?money(g.cost_usd):'—');};
  const trajOf=c=>c.trajectory_file?'<span class="chip yes">step grain</span>':((c.grain||{}).legacy_rows?'<span class="chip na">cell rows</span>':'<span class="chip na">none</span>');
  const BASIS_SHORT={'sealed receipts on this machine':'receipts on disk','first commit naming it':'first commit','date in the identity':'date in id','created_date in its reports':'report date'};
  const ranOf=c=>{const o=c.order||{};if(!o.at)return '<span class="muted">unknown</span>';const t=o.at.replace('T',' ').slice(0,16);const w=o.window;const title=`${o.basis}${w?` · ${w.receipts} receipts written ${w.start.replace('T',' ')} to ${w.end.replace('T',' ')}`:''}${o.git?` · first commit ${o.git.commit} ${o.git.date.slice(0,10)}: ${o.git.subject}`:''}`;return `<span class="mono" title="${esc(title)}">${esc(t)}</span><div class="basis" title="${esc(title)}">${esc(BASIS_SHORT[o.basis]||o.basis)}${w&&w.end&&w.end!==w.start?' · to '+esc(w.end.slice(11,16)):''}</div>`;};
  const rankOf=id=>{const m=byId(id);return m&&m.order?`<button class="runnav" data-id="${esc(id)}">#${m.order.rank}</button>`:esc(id);};
  const lineageOf=c=>{const parts=[];if(c.chain.length>1)parts.push(`${esc(c.version||'')} of ${c.chain.length} in <span class="mono">${esc(c.stem)}</span>`);const o=c.order||{};(o.refs||[]).forEach(r=>parts.push(`builds on ${rankOf(r)}`));(o.referred_by||[]).forEach(r=>parts.push(`used by ${rankOf(r)}`));return parts.join('<br>')||'<span class="muted">standalone</span>';};
  let groups;
  if(mode==='time'){
    const rows=list.map(c=>`<tr class="click" data-id="${esc(c.id)}"><td class="mono">${c.order?c.order.rank:''}</td><td class="ran">${ranOf(c)}</td><td class="idc"><span class="mono">${esc(c.id)}</span> <span class="chip ${c.chain.latest?'acc':''}">${esc(c.version||c.date||'—')}${c.variant?' · '+esc(c.variant):''}</span></td><td class="what">${esc((c.order||{}).summary||'')}${(c.order||{}).claim?`<div class="basis" style="white-space:normal">claim: ${esc(c.order.claim.replace(/_/g,' '))}</div>`:''}</td><td>${esc(c.status.label)}</td><td>${issuesOf(c)}</td><td>${miniBar(c.checklist)}</td><td>${trajOf(c)}</td><td class="lin">${lineageOf(c)}</td></tr>`).join('');
    groups=`<div class="stem">Run order <span class="stemnote">· ${list.length} bundle${list.length!==1?'s':''}, earliest first. “Ran” is when this bundle's sealed receipts were written on this machine; where the run root is not here, it is the first commit that names the identity (day precision).</span></div><div class="scroll"><table class="order"><thead><tr><th>#</th><th>ran</th><th>identity</th><th>what this run is (README)</th><th>status (as stated)</th><th>incident rows</th><th>validity checklist</th><th>trajectories</th><th>lineage</th></tr></thead><tbody>${rows}</tbody></table></div>`;
  } else {
    const stems={}; list.forEach(c=>{(stems[c.stem]=stems[c.stem]||[]).push(c);});
    groups=Object.entries(stems).sort((a,b)=>Math.min(...a[1].map(c=>(c.order||{}).rank||1e9))-Math.min(...b[1].map(c=>(c.order||{}).rank||1e9))).map(([stem,members])=>{
      members.sort((a,b)=>a.chain.position-b.chain.position);
      const rows=members.map(c=>`<tr class="click" data-id="${esc(c.id)}"><td class="mono">${c.order?c.order.rank:''}</td><td><span class="chip ${c.chain.latest?'acc':''}">${esc(c.version||c.date||'—')}${c.variant?' · '+esc(c.variant):''}</span></td><td class="mono">${esc(c.id)}</td><td>${ranOf(c)}</td><td>${esc(c.status.label)}</td><td>${cellsOf(c)}</td><td>${costOf(c)}</td><td>${issuesOf(c)}</td><td>${miniBar(c.checklist)}</td><td>${trajOf(c)}</td></tr>`).join('');
      return `<div class="stem">${esc(stem)} <span class="stemnote">· ${members.length} version${members.length>1?'s':''}${members.length>1?', latest '+esc(members[members.length-1].version||members[members.length-1].date||''):''}</span></div><div class="scroll"><table><thead><tr><th>#</th><th>version</th><th>identity</th><th>ran</th><th>status (as stated)</th><th>cells</th><th>cost</th><th>incident rows</th><th>validity checklist</th><th>trajectories</th></tr></thead><tbody>${rows}</tbody></table></div>`;
    }).join('');
  }
'''
s = s[:start] + new_block + s[end:]
rep("""$('view').innerHTML=`<p class="lede">Every published campaign bundle, grouped by family and version chain. Status is what the bundle and the QC profile state, never inferred beyond their words; the validity bar summarises the checklist on each campaign's page (green yes, amber partial, red no, grey not stated). Click a row.</p><div class="tabs">${tabs}</div>${graphs}${groups}${famIssues}`;
  $('view').querySelectorAll('.tabs button').forEach(b=>b.addEventListener('click',()=>{route.family=b.dataset.f;render();}));""",
"""$('view').innerHTML=`<p class="lede">Every published campaign bundle, in the order it ran (# is its place in the family). Status is what the bundle and the QC profile state, never inferred beyond their words; the validity bar summarises the checklist on each campaign's page (green yes, amber partial, red no, grey not stated). Click a row.</p><div class="tabs">${tabs}</div><div class="bar" style="margin:-6px 0 8px"><span class="muted" style="font-size:12px">show</span><div class="tabs" style="margin:0"><button data-m="time" class="${mode==='time'?'cur':''}">by run order</button><button data-m="stem" class="${mode==='stem'?'cur':''}">by version stem</button></div></div>${graphs}${groups}${famIssues}`;
  $('view').querySelectorAll('[data-m]').forEach(b=>b.addEventListener('click',()=>{route.catalogOrder=b.dataset.m;render();}));
  $('view').querySelectorAll('.runnav').forEach(b=>b.addEventListener('click',e=>{e.stopPropagation();route.view='campaign';route.campaign=b.dataset.id;route.caseId=null;render();}));
  $('view').querySelectorAll('.tabs button[data-f]').forEach(b=>b.addEventListener('click',()=>{route.family=b.dataset.f;render();}));""")
rep("""   <h3 class="mono" style="font-size:16px">${esc(c.id)}</h3><div class="chain">${chain}</div>""",
    """   <h3 class="mono" style="font-size:16px">${esc(c.id)}</h3><div class="chain">${chain}</div>${runline}""")
rep("""  const st=c.status;
  const why=[""", """  const o=c.order||{};const prevRun=o.prev?byId(o.prev):null,nextRun=o.next?byId(o.next):null;
  const runline=`<div class="runline"><span class="chip acc">run #${o.rank||'?'} of ${o.of||'?'} in ${esc(CAT.family_label[c.family]||c.family)}</span><span class="muted">ran <span class="mono">${esc(o.at?o.at.replace('T',' ').slice(0,16):'unknown')}</span> · ${esc(o.basis||'')}</span>${prevRun?`<button class="runnav" data-id="${esc(prevRun.id)}" title="${esc(prevRun.id)}">‹ #${prevRun.order.rank} ${esc(prevRun.stem)}${prevRun.version?' '+esc(prevRun.version):''}</button>`:'<span class="muted">first run in the family</span>'}${nextRun?`<button class="runnav" data-id="${esc(nextRun.id)}" title="${esc(nextRun.id)}">#${nextRun.order.rank} ${esc(nextRun.stem)}${nextRun.version?' '+esc(nextRun.version):''} ›</button>`:'<span class="muted">latest run in the family</span>'}${(o.refs||[]).length?`<span class="muted">builds on ${o.refs.map(r=>`<button class="runnav" data-id="${esc(r)}">#${(byId(r).order||{}).rank} ${esc(r)}</button>`).join(' ')}</span>`:''}${(o.referred_by||[]).length?`<span class="muted">used by ${o.referred_by.map(r=>`<button class="runnav" data-id="${esc(r)}">#${(byId(r).order||{}).rank} ${esc(r)}</button>`).join(' ')}</span>`:''}</div>`;
  const st=c.status;
  const why=[""")
rep("""  $('view').querySelectorAll('.chain button').forEach(b=>b.addEventListener('click',()=>{route.campaign=b.dataset.id;render();}));""",
    """  $('view').querySelectorAll('.chain button, .runnav').forEach(b=>b.addEventListener('click',()=>{route.campaign=b.dataset.id;route.caseId=null;render();}));""")
open(dst, 'w').write(s)
print('merged ->', dst, len(s), 'bytes; has orderHtml:', 'function orderHtml' in s, '; has run order:', 'Run order' in s)
