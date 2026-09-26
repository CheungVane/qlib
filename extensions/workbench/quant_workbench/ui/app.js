const initialQuery = new URLSearchParams(location.search);
const hasCompareQuery = initialQuery.has('compare');
const state = {runs: [], selected: initialQuery.get('run'), compareIds: (initialQuery.get('compare') || '').split(',').filter(Boolean), researchId: initialQuery.get('research'), researchOffset:0, researchQuery:'', search: '', view: location.hash.slice(1) || 'overview'};
const titles = {overview:['总览','研究运行、数据状态与系统观察'],backtest:['回测','权益、回撤、费用与来源证据'],training:['训练','指标曲线、阶段状态与来源证据'],compare:['比较','并列查看运行，先核对数据与指标口径'],agent:['研究中心','研究结果、因子内容、过程追踪与下一步'],live:['实时','行情连接与数据新鲜度'],data:['数据','数据集来源、覆盖与质量'],system:['系统','任务状态、请求与错误观察']};
const esc = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const fmt = (n, digits=2) => typeof n === 'number' ? new Intl.NumberFormat('zh-CN',{maximumFractionDigits:digits}).format(n) : '未知';
const sample = run => (run?.synthetic && run?.provenance?.kind!=='fixture' ? '<span class="sample">模拟行情</span>' : '') + (run?.provenance?originBadge(run.provenance):'');

const originLabels={native:'引擎原始记录',derived:'工作台计算',custom:'定制检查',opinion:'Agent生成意见',rule:'工作台规则提示',fixture:'手写演示样本',measured:'工作台实测',unknown:'来源未核实',unsupported:'未接入',limited:'能力受限',missing:'未记录'};
function originBadge(p){if(!p)return '';return `<span class="origin origin-${esc(p.kind)}" title="${esc([p.source,...(p.limitations||[])].join('；'))}">${esc(p.label||originLabels[p.kind]||p.kind)}</span>`;}
function badge(kind){return originBadge({kind});}
function provenancePanel(detail){
 const audit=detail.provenance;if(!audit)return card('来源核查',badge('unknown')+' 当前结果未登记来源映射');
 return card('数据来源与能力标记',`${originBadge(audit.run)} ${audit.data_nature==='synthetic'?'<span class="sample">模拟行情</span>':''}<p class="panel-note">原始记录只表示数值来自引擎产物，不表示行情真实，也不表示使用未经修改的上游执行器。下表区分字段来源与计算范围。</p><details><summary>逐项查看字段来源、公式与限制</summary><div class="table-scroll"><table class="table"><thead><tr><th>字段</th><th>来源类型</th><th>依据与限制</th></tr></thead><tbody>${audit.fields.map(x=>`<tr><td>${esc(x.field)}</td><td>${originBadge(x)}</td><td>${esc(x.source)}<br><span class="warning">${esc(x.limitations.join('；'))}</span></td></tr>`).join('')}</tbody></table></div></details>`);
}
async function capabilityPanel(){
 const data=await api('/v1/provenance/capabilities');
 return card('能力边界与来源审计',`<p class="panel-note">这里描述当前工作台接入程度，不代表上游框架的全部能力。标记不以有数字或绿灯代替验收。</p><div class="table-scroll"><table class="table"><thead><tr><th>功能 / 信息</th><th>标记</th><th>依据与限制</th></tr></thead><tbody>${data.items.map(x=>`<tr><td>${esc(x.name)}</td><td>${originBadge(x)}</td><td>${esc(x.source)}<br>${esc(x.limitations.join('；'))}</td></tr>`).join('')}</tbody></table></div>`);
}
async function api(path) {
  const response = await fetch(path, {headers:{'Accept':'application/json'}});
  if (!response.ok) throw new Error((await response.json().catch(()=>({}))).message || `请求失败 ${response.status}`);
  return response.json();
}
function empty(message){return `<div class="empty">${esc(message)}</div>`;}
function card(title,body,meta=''){return `<section class="card"><div class="card-head"><h2>${esc(title)}</h2><small>${esc(meta)}</small></div>${body}</section>`;}
function statusLabel(status){const text={succeeded:'成功',failed:'失败',running:'运行中',queued:'排队中',cancelled:'已取消',interrupted:'中断',unknown:'未知'}[status]||status;return `<span class="status ${status==='failed'?'failed':status==='unknown'?'unknown':''}">${esc(text)}</span>`;}
function setNotice(message=''){document.getElementById('notice').textContent=message;}
function setView(view){
  state.view=titles[view]?view:'overview';location.hash=state.view;
  document.querySelectorAll('.nav').forEach(button=>button.classList.toggle('active',button.dataset.view===state.view));
  document.getElementById('page-title').textContent=titles[state.view][0];
  document.getElementById('page-subtitle').textContent=titles[state.view][1];
  render();
}
function selectRun(id){state.selected=id;const url=new URL(location.href);url.searchParams.set('run',id);history.replaceState(null,'',url);renderRuns();render();}
function renderRuns(){
  const box=document.getElementById('run-list');
  const visible=state.runs.filter(item=>`${item.run.title} ${item.run.engine.id} ${item.external_id}`.toLocaleLowerCase().includes(state.search));
  box.innerHTML=visible.length?visible.map(item=>`<button class="run-item ${item.run_id===state.selected?'selected':''}" data-run="${esc(item.run_id)}"><b>${esc(item.run.title==='mlflow_recorder'?'Qlib 回测 · '+item.run.created_at.slice(0,16).replace('T',' '):item.run.title)}</b><small>${sample(item.run)}${esc(item.run.engine.id)} · ${esc(item.run.status)}</small></button>`).join(''):empty(state.runs.length?'没有匹配的运行':'还没有导入运行结果');
  box.querySelectorAll('[data-run]').forEach(button=>button.onclick=()=>selectRun(button.dataset.run));
}
function renderWidget(widget,payload){
  let body;
  if(payload.availability==='not_recorded'||payload.availability==='unsupported') body=empty(payload.reason||'尚未接入');
  else if(payload.availability==='empty') body=empty('暂无记录');
  else if(widget.query.id==='runs.latest'){
    const rows=payload.data.items.map(item=>`<tr><td><button class="link-button" data-open-run="${esc(item.run_id)}">${esc(item.run.title)}</button> ${sample(item.run)}</td><td>${esc(item.run.engine.id)}</td><td>${statusLabel(item.run.status)}</td><td>${esc(item.run.created_at.slice(0,10))}</td></tr>`).join('');
    body=`<table class="table"><thead><tr><th>运行</th><th>引擎</th><th>状态</th><th>日期</th></tr></thead><tbody>${rows}</tbody></table>`;
  }else if(widget.query.id==='api.error_rate.5m'){body=`<div class="kpi">${payload.data.error_rate===null?'无样本':fmt(payload.data.error_rate*100)+'%'}<small> 5xx / 已完成请求</small></div><p class="panel-note">${payload.data.server_errors} / ${payload.data.completed_requests} 请求 · 覆盖 ${fmt(payload.data.coverage_seconds,0)} 秒（窗口300秒）</p>`;}else body=empty('暂无数据');
  return `<section class="card" style="grid-column:span ${widget.layout.w}"><div class="card-head"><h2>${esc(widget.title)}</h2><small>${esc(payload.availability)}</small></div>${body}</section>`;
}
async function renderOverview(){
  const manifest=await api('/v1/dashboards/overview');
  const research=await api('/v1/research?limit=5');
  const payloads=await Promise.all(manifest.widgets.map(w=>api(`/v1/widgets/${encodeURIComponent(w.query.id)}`)));
  document.getElementById('content').innerHTML=`<div class="stack">${await capabilityPanel()}${card('最近研究与待检查事项', researchTable(research.items))}<div class="grid">${manifest.widgets.map((w,i)=>renderWidget(w,payloads[i])).join('')}</div></div>`;
  document.querySelectorAll('[data-open-run]').forEach(button=>button.onclick=()=>{selectRun(button.dataset.openRun);setView('backtest');});
  bindResearch();
}
function chart(points,unit='CNY'){
  const filtered=points.filter(p=>typeof p.value==='number');
  if(filtered.length<2)return empty('有效点数不足，无法绘图');
  const values=filtered.map(p=>p.value), lo=Math.min(...values),hi=Math.max(...values),range=hi-lo||1;
  const xy=filtered.map((p,i)=>[48+i/(filtered.length-1)*732,235-(p.value-lo)/range*185]);
  const line=xy.map(([x,y])=>`${x.toFixed(2)},${y.toFixed(2)}`).join(' ');
  const fill=`48,235 ${line} 780,235`;
  return `<svg class="chart" viewBox="0 0 820 270" role="img" aria-label="${esc(unit)} 序列，共${filtered.length}个数据点"><line x1="48" y1="235" x2="780" y2="235" class="chart-grid"/><line x1="48" y1="50" x2="780" y2="50" class="chart-grid"/><polygon points="${fill}" class="chart-fill"/><polyline points="${line}" class="chart-line"/><text x="48" y="42" class="chart-label">${esc(fmt(hi))} ${esc(unit)}</text><text x="48" y="255" class="chart-label">${esc(filtered[0].x)}</text><text x="705" y="255" class="chart-label">${esc(filtered.at(-1).x)}</text></svg>`;
}
async function selectedRevision(){
  const id=state.selected;
  if(!id)return null;
  const summary=state.runs.find(x=>x.run_id===id)||await api(`/v1/runs/${encodeURIComponent(id)}`);
  const detail=await api(`/v1/runs/${encodeURIComponent(id)}/revisions/${encodeURIComponent(summary.revision_id)}`);
  return {summary,detail};
}
async function series(id,metric,revisionId=state.runs.find(x=>x.run_id===id)?.revision_id){
  try{return await api(`/v1/runs/${encodeURIComponent(id)}/series?metric_id=${encodeURIComponent(metric)}${revisionId?'&revision_id='+encodeURIComponent(revisionId):''}`);}catch{return null;}
}
async function renderBacktest(){
  const selected=await selectedRevision();if(!selected){document.getElementById('content').innerHTML=empty('请先在左侧选择一个运行');return;}
  const {summary,detail}=selected, id=summary.run_id;
  const review=await api(`/v1/runs/${id}/review?revision_id=${summary.revision_id}`);
  const [equity,drawdown,cost,turnover]=await Promise.all(['platform.equity','platform.drawdown','native.qlib.total_cost','native.qlib.turnover'].map(x=>series(id,x)));
  const points=equity?.series.points||[];
  const last=points.at(-1)?.value, first=points[0]?.value;
  const dd=drawdown?.series.points?.map(x=>x.value).filter(x=>typeof x==='number')||[];
  const totalCost=cost?.series.points?.at(-1)?.value;
  const kpis=`<div class="metric-row"><div class="metric-box"><small>期末权益 ${originBadge(equity?.series?.provenance)}</small><strong>${fmt(last)} <small>CNY</small></strong></div><div class="metric-box"><small>首末观测权益变化 ${badge('derived')}</small><strong>${typeof review.facts.observed_equity_change==='number'?fmt(review.facts.observed_equity_change*100)+'%':'未知'}</strong></div><div class="metric-box"><small>最大观测权益回撤 ${originBadge(drawdown?.series?.provenance)}</small><strong>${dd.length?fmt(Math.min(...dd)*100)+'%':'未知'}</strong></div><div class="metric-box"><small>引擎</small><strong>${esc(summary.run.engine.id)}</strong></div></div>`;
  const heading=`<div class="heading-row"><div><h2>${esc(summary.run.title)}</h2><p class="panel-note">${statusLabel(summary.run.status)} ${sample(summary.run)} · 结果版本 ${esc(summary.revision_id.slice(0,12))} · 数据版本 ${esc(summary.run.dataset.version||'未知')}</p></div></div>`;
  const misc=`<p class="panel-note">${originBadge(cost?.series?.provenance)} 累计费用（源报告末点）：${fmt(totalCost)} CNY<br>换手序列：${turnover?'已记录':'未记录'} · 撮合与费用口径请查原运行配置。</p>`;
  document.getElementById('content').innerHTML=`<div class="stack">${card('运行概况',heading+kpis)}${provenancePanel(detail)}${reviewPanel(review,detail.evidence)}${card('权益曲线',equity?chart(points):empty('该引擎未记录标准权益序列'),equity?.series?.provenance?.source||'来源未核实')}${card('成本与换手',misc)}${card('来源证据',`<details><summary>展开原始证据</summary><pre class="panel-note">${esc(JSON.stringify(detail.evidence,null,2))}</pre></details>`,'未知事实保留为空')}</div>`;
}
async function renderTraining(){
  const selected=await selectedRevision();if(!selected){document.getElementById('content').innerHTML=empty('请先选择一个运行');return;}
  const {summary,detail}=selected;
  const review=await api(`/v1/runs/${summary.run_id}/review?revision_id=${summary.revision_id}`);
  const metrics=detail.series.filter(x=>x.axis==='step'||x.metric_id.toLowerCase().includes('ic')||x.metric_id.includes('l2'));
  let rows=[];
  for(const metric of metrics.slice(0,30)){
    const data=await series(summary.run_id,metric.metric_id);
    rows.push(`<tr><td>${esc(metric.metric_id)} ${originBadge(metric.provenance)}${metric.axis==='step'&&metric.point_count<2?badge('limited'):''}</td><td>${esc(metric.axis)}</td><td>${esc(fmt(data?.series.points?.at(-1)?.value,5))}</td><td>${esc(metric.unit)}</td></tr>`);
  }
  const stageText=summary.run.stages?.map(x=>`${esc(x.kind)}：${esc(x.status)}`).join(' · ')||'阶段信息未知';
  document.getElementById('content').innerHTML=`<div class="stack">${card('训练运行',`<div class="heading-row"><h2>${esc(summary.run.title)}</h2>${sample(summary.run)}</div><p class="panel-note">${stageText}<br>引擎运行时版本：${esc(summary.run.engine.version||'未知')} · 数据版本：${esc(summary.run.dataset.version||'未知')}</p>`)}${provenancePanel(detail)}${reviewPanel(review,detail.evidence)}${card('训练与信号指标',rows.length?`<table class="table"><thead><tr><th>指标</th><th>轴</th><th>末点</th><th>单位</th></tr></thead><tbody>${rows.join('')}</tbody></table>`:empty('该运行没有可显示的训练指标'))}</div>`;
}
const compareReasons = {handwritten_fixture_present:'包含手写演示样本，不支持研究排名',date_window_differs:'回测日期窗口不同',first_equity_differs:'首个观测权益不同',execution_scenario_unknown_or_differs:'执行/费用情景未知或不同',unit_differs:'单位不同',axis_differs:'序列轴不同',definition_id_differs:'指标定义不同',calendar_id_differs:'交易日历不同',currency_differs:'币种不同',synthetic_and_real_mixed:'模拟与真实数据混用',dataset_version_unknown_or_differs:'数据版本未知或不同'};
async function renderCompare(){
  const choices=state.runs.map(item=>`<label class="compare-choice"><input type="checkbox" data-compare-run="${esc(item.run_id)}" ${state.compareIds.includes(item.run_id)?'checked':''}><span><strong>${esc(item.run.title)}</strong><small>${esc(item.run.engine.id)} · ${esc(item.run.dataset.id)} · ${esc(item.run.dataset.version||'版本未知')} ${sample(item.run)}</small></span></label>`).join('');
  const picker=card('选择运行',`<p class="panel-note">选择 2 至 10 个运行。比较依据为平台标准指标，原生指标保留各自定义。</p><div class="compare-choices">${choices||empty('还没有导入运行')}</div>`);
  if(state.compareIds.length<2){document.getElementById('content').innerHTML=`<div class="stack">${picker}${card('比较结果',empty('请选择至少两个运行'))}</div>`;bindCompare();return;}
  const query=new URLSearchParams({metric_id:'platform.equity'});
  state.compareIds.forEach(id=>query.append('run_id',id));
  const assessment=await api(`/v1/compare?${query}`);
  const reasons=assessment.reasons.map(reason=>compareReasons[reason]||reason);
  const tone=assessment.ranking_allowed?'assessment-ok':'assessment-caution';
  const assessmentBody=`<div class="assessment ${tone}"><strong>${assessment.ranking_allowed?'可按统一口径比较':'仅供并列查看，暂不能排名'}</strong><p>${esc(reasons.length?reasons.join(' · '):'指标定义、单位、日历和数据版本一致')}</p></div><p class="panel-note">每个运行单独绘图，保留原始时间轴与数值。不同时间窗口或起始资金不自动归一化。</p>`;
  const panels=await Promise.all(state.compareIds.map(async id=>{
    const item=state.runs.find(x=>x.run_id===id);
    if(!item)return card('运行不存在',empty(id));
    const revisionId=assessment.revisions?.[id]||item.revision_id;
    const result=await series(id,'platform.equity',revisionId);
    const review=await api(`/v1/runs/${id}/review?revision_id=${revisionId}`);
    const detail=await api(`/v1/runs/${id}/revisions/${revisionId}`);
    const scenario=detail.evidence?.cn_scenario;
    const points=result?.series.points||[], first=points[0]?.value,last=points.at(-1)?.value;
    const heading=`<div class="heading-row"><p class="panel-note">${esc(item.run.engine.id)} · ${esc(item.run.dataset.id)} · ${sample(item.run)}</p><button class="link-button" data-open-run="${esc(id)}">查看详情</button></div>`;
    const facts=`<div class="metric-row"><div class="metric-box"><small>期末权益</small><strong>${fmt(last)} <small>${esc(result?.series.unit||'')}</small></strong></div><div class="metric-box"><small>首末观测权益变化 ${badge('derived')}</small><strong>${typeof first==='number'&&first!==0&&typeof last==='number'?fmt((last/first-1)*100)+'%':'未知'}</strong></div><div class="metric-box"><small>数据版本</small><strong>${esc(item.run.dataset.version||'未知')}</strong></div></div>`;
    const context=`<dl class="context-grid"><dt>报告区间</dt><dd>${esc(points[0]?.x||'未记录')} → ${esc(points.at(-1)?.x||'未记录')}</dd><dt>最大观测回撤 ${badge('derived')}</dt><dd>${typeof review.facts.max_observed_drawdown==='number'?fmt(review.facts.max_observed_drawdown*100)+'%':'未知'}</dd><dt>累计成本</dt><dd>${fmt(review.facts.total_cost)} CNY</dd><dt>质量</dt><dd>${badge(review.quality?'custom':'missing')} ${esc(review.quality?.status||'未记录')}</dd><dt>执行情景</dt><dd>${esc(scenario?.fingerprint?.slice(0,12)||'未知')}</dd><dt>佣金 / 最低费</dt><dd>${esc(scenario?.commission_both||'未知')} / ${esc(scenario?.minimum_commission||'未知')}</dd><dt>结果版本</dt><dd>${esc(item.revision_id.slice(0,12))}</dd></dl>`;
    return card(item.run.title,heading+facts+context+(result?chart(points,result.series.unit):empty('该运行没有平台权益序列')),esc(item.run.created_at.slice(0,10)));
  }));
  document.getElementById('content').innerHTML=`<div class="stack">${picker}${card('口径检查',assessmentBody)}<div class="compare-grid">${panels.join('')}</div></div>`;
  bindCompare();
  document.querySelectorAll('[data-open-run]').forEach(button=>button.onclick=()=>{selectRun(button.dataset.openRun);setView('backtest');});
  bindResearch();
}
function bindCompare(){
  document.querySelectorAll('[data-compare-run]').forEach(input=>input.onchange=()=>{
    const id=input.dataset.compareRun;
    if(input.checked&&state.compareIds.length>=10){input.checked=false;setNotice('最多比较 10 个运行');return;}
    state.compareIds=input.checked?[...state.compareIds,id]:state.compareIds.filter(x=>x!==id);
    const url=new URL(location.href);
    url.searchParams.set('compare',state.compareIds.join(','));
    history.replaceState(null,'',url);render();
  });
}
const agentReason = {chat_not_configured:'聊天模型或密钥未配置',embedding_not_configured:'Embedding 模型或对应密钥未配置',embedding_service_unavailable:'本地 Embedding 服务或模型暂不可用',native_runtime_unverified:'RD-Agent 官方仅支持 Linux；当前系统的原生因子流程尚未验证',docker_not_available:'Linux Docker 引擎当前不可用',factor_image_unverified:'因子执行所需的 CPU/arm64 镜像尚未验证',factor_scenario_not_aligned:'因子模板的数据区间与万二费用情景尚未对齐',executor_not_integrated:'工作台执行器尚未接入',checkout_missing:'RD-Agent checkout 不存在',checkout_not_configured:'未指定 RD-Agent checkout'};
const researchMetricNames = {'IC':'IC（相关系数）','Rank IC':'Rank IC','ICIR':'ICIR','Rank ICIR':'Rank ICIR','1day.excess_return_with_cost.annualized_return':'成本后年化超额收益（原生口径）','1day.excess_return_with_cost.max_drawdown':'成本后超额最大回撤','1day.excess_return_with_cost.information_ratio':'成本后信息比率','l2.train':'训练 L2','l2.valid':'验证 L2'};
function reviewPanel(review,evidence={}){
  if(!review)return '';
  const q=review.quality, scenario=evidence.cn_scenario;
  const quality=q?`定制质量检查（非上游原生）：${q.status==='passed_checks'?'通过':'未通过'} · 有效 IC ${q.valid_ic_days} 天 · 交易 ${q.trade_days} 天`:'质量检查未记录';
  const fees=scenario?`佣金 ${esc(scenario.commission_both)} · 最低佣金 ${esc(scenario.minimum_commission)} 元 · 规则核查 ${esc(scenario.rules_as_of)} · ${esc(scenario.mode)}`:'执行情景未记录';
  return card('规则摘要与待验证事项',`${badge('rule')}<p class="panel-note">以下为工作台固定规则提示；不是引擎原始结论，也没有额外调用模型分析。</p><div class="assessment assessment-caution"><strong>${esc(review.conclusion)}</strong><p>${badge(q?'custom':'missing')} ${esc(quality)}</p></div><p class="panel-note">${badge(scenario?'custom':'missing')} ${fees}</p>${(review.findings||[]).map(x=>`<p class="warning">${esc(x)}</p>`).join('')}<div class="compare-grid"><div><h3>数据依据与缺口</h3><ul>${review.gaps.map(x=>`<li>${esc(x)}</li>`).join('')||'<li>没有额外缺口记录</li>'}</ul></div><div><h3>规则建议（需自行验证）</h3><ol>${review.next_steps.map(x=>`<li>${esc(x)}</li>`).join('')}</ol></div></div><p class="panel-note">${esc(review.basis)}</p>`);
}
function researchTable(items){
 return items.length?`<div class="table-scroll"><table class="table research-table"><thead><tr><th>研究 / 点击查看结果与过程</th><th>产物状态 ${badge('limited')}</th><th>已恢复因子 ${badge('derived')}</th><th>期末权益 ${badge('native')}</th><th>IC ${badge('native')}</th><th>成本后年化超额 ${badge('native')}</th><th>操作</th></tr></thead><tbody>${items.map(r=>`<tr><td><button class="link-button" data-research="${r.id}">${esc(r.title)}</button> ${r.synthetic?'<span class="sample">模拟行情</span>':''}<small class="block muted">${esc(r.session)}</small></td><td>${r.status==='result_available'?'已有结果':'过程不完整'}</td><td>${r.factor_count===0?'未恢复 / 不适用':r.factor_count}</td><td>${fmt(r.facts?.ending_equity)} CNY</td><td>${fmt(r.metrics?.IC,4)}</td><td>${typeof r.metrics?.['1day.excess_return_with_cost.annualized_return']==='number'?fmt(r.metrics['1day.excess_return_with_cost.annualized_return']*100)+'%':'未记录'}</td><td>${r.platform_run_id?`<button class="link-button" data-research-compare="${r.platform_run_id}">加入比较</button>`:'可查看过程'}</td></tr>`).join('')}</tbody></table></div>`:empty('暂无研究快照。请运行研究记录同步命令，已有产物不会自动被推断为成功。');
}
function openResearch(id){state.researchId=id;const u=new URL(location.href);u.searchParams.set('research',id);history.replaceState(null,'',u);setView('agent');}
function bindResearch(){
 document.querySelectorAll('[data-research]').forEach(b=>b.onclick=()=>openResearch(b.dataset.research));
 document.querySelectorAll('[data-research-compare]').forEach(b=>b.onclick=()=>{
  const id=b.dataset.researchCompare;
  if(!state.compareIds.includes(id))state.compareIds=[...state.compareIds,id].slice(-10);
  const u=new URL(location.href);u.searchParams.set('compare',state.compareIds.join(','));history.replaceState(null,'',u);setView('compare');
 });
}
function readableFields(value){
 const labels={decision:'Agent 是否采纳',reason:'原因',observations:'观察结果',hypothesis_evaluation:'假设评估',new_hypothesis:'后续研究方向',acceptable:'是否可接受',exception:'异常',hypothesis:'研究假设',concise_observation:'观察',concise_justification:'依据',start_time:'阶段开始',end_time:'阶段结束',feedback:'执行反馈',log:'执行日志',report:'报告',rows:'行数',result:'结果',factor_count:'因子数',metric_count:'指标数'};
 return Object.entries(value).map(([k,v])=>`<div class="evidence-field"><h3>${esc(labels[k]||k)}</h3>${k==='decision'?`<p>${v==='False'?'未采纳候选':v==='True'?'采纳候选':esc(v)}</p>`:`<pre>${esc(typeof v==='object'?JSON.stringify(v,null,2):v)}</pre>`}</div>`).join('');
}
function stageLabel(stage){return stage.replaceAll('direct_exp_gen','研究假设').replaceAll('hypothesis generation','假设生成').replaceAll('coding','因子编码').replaceAll('running','回测执行').replaceAll('feedback','评审反馈').replaceAll('record','记录归档').replaceAll('time_info','阶段耗时').replaceAll('Quantitative Backtesting Chart','回测报告').replaceAll('Qlib_execute_log','执行日志').replaceAll('runner result','研究产物');}
async function renderResearchDetail(){
 const r=await api(`/v1/research/${encodeURIComponent(state.researchId)}`);
 if(r.platform_run_id){r.review=await api(`/v1/runs/${r.platform_run_id}/review?revision_id=${r.revision_id}`);r.resultDetail=await api(`/v1/runs/${r.platform_run_id}/revisions/${r.revision_id}`);r.evidence=r.resultDetail.evidence;}
 const facts=`<div class="heading-row"><div><h2>${esc(r.title)}</h2><p class="panel-note">${r.synthetic?'<span class="sample">模拟数据</span>':''} ${esc(r.session)}<br>源事件更新 ${esc(r.updated_at)} · 快照采集 ${esc(r.observed_at)}</p></div><button class="link-button" id="research-back">返回研究列表</button></div><p>${r.status==='result_available'?'已找到回测报告。进程退出状态未记录。':'未找到完整回测结果；可查看已经记录的过程。'}</p>${r.platform_run_id?`<button class="action" id="research-result">打开统一回测详情</button> <button class="action secondary" data-research-compare="${r.platform_run_id}">加入比较</button>`:''}`;
 const metricTop=`<div class="metric-row"><div class="metric-box"><small>IC ${badge('native')}</small><strong>${fmt(r.metrics?.IC,4)}</strong></div><div class="metric-box"><small>成本后年化超额（源口径） ${badge('native')}</small><strong>${typeof r.metrics?.['1day.excess_return_with_cost.annualized_return']==='number'?fmt(r.metrics['1day.excess_return_with_cost.annualized_return']*100)+'%':'未记录'}</strong></div><div class="metric-box"><small>因子数</small><strong>${r.factor_count??'未记录'}</strong></div></div>`;
 const metrics=Object.entries(r.metrics||{}).map(([k,v])=>`<tr><td>${esc(researchMetricNames[k]||k)}</td><td>${fmt(v,6)}</td></tr>`).join('');
 const factors=(r.factors||[]).map(f=>`<details class="factor"><summary>${esc(f.factor_name||'因子')} — ${esc(f.description||'暂无说明')}</summary><p>公式</p><pre>${esc(f.factor_formulation)}</pre><p>变量</p><pre>${esc(f.variables)}</pre><details><summary>查看生成代码</summary><pre>${esc(f.code||'代码未记录')}</pre></details></details>`).join('');
 const steps=(r.events||[]).map(e=>`<details class="timeline-step"><summary><span>${esc(stageLabel(e.stage))}</span><small>${esc(e.at)}</small></summary>${typeof e.content==='string'?`<pre>${esc(e.content)}</pre>`:readableFields(e.content)}</details>`).join('');
 document.getElementById('content').innerHTML=`<div class="stack">${card('研究结果',facts)}${r.resultDetail?provenancePanel(r.resultDetail):card('来源与限制',badge('limited')+' 仅历史日志摘录；没有完整结果，不等于研究失败。')}${r.review?reviewPanel(r.review,r.evidence):''}${r.warnings?.length?card('产物缺口',r.warnings.map(x=>`<p>${esc(x)}</p>`).join('')):''}${card('结果指标',metrics?`${metricTop}<details><summary>原生指标（保留源口径，空值不填零）</summary><table class="table"><tbody>${metrics}</tbody></table></details>`:empty('没有标量指标；若已生成报告，可在统一回测详情查看权益与费用'))}${card('因子与实现',badge('opinion')+'<p class="panel-note">Agent生成的定义和代码；可执行不等于因子有效，文字声称无未来信息未被独立认证。</p>'+(factors||empty('未记录因子定义；基线回测可能只使用基础特征')))}${card('Agent 评审意见',r.feedback?`${badge('opinion')}<p class="panel-note">模型原文，可能包含错误解释；与已记录数值分开看待。</p>${readableFields(r.feedback)}<p class="panel-note">这是 Agent 的研究反馈，不是平台的实盘建议。</p>`:empty('评审反馈未记录'))}${card('过程时间线',badge('limited')+'<p class="panel-note">离线历史摘录，非实时进度；最多300条，长日志/代码可能截断，未展示完整提示词。标题与结果条目数由工作台编排。</p>'+(steps||empty('没有可恢复的研究阶段')),'点击阶段展开日志 / 耗时 / 反馈')}</div>`;
 document.getElementById('research-back').onclick=()=>{state.researchId=null;const u=new URL(location.href);u.searchParams.delete('research');history.replaceState(null,'',u);render();};
 const result=document.getElementById('research-result');if(result)result.onclick=()=>{selectRun(r.platform_run_id);setView('backtest');};bindResearch();
}
async function renderAgent(){
 if(state.researchId){await renderResearchDetail();return;}
 const [list,runtime]=await Promise.all([api(`/v1/research?limit=20&offset=${state.researchOffset}&query=${encodeURIComponent(state.researchQuery)}`),api('/v1/agents/rdagent')]);
 const toolbar=`<form id="research-search" class="toolbar"><input aria-label="搜索研究" id="research-query" placeholder="搜索因子名、日期、状态" value="${esc(state.researchQuery)}"><button class="action">搜索</button><button type="button" id="research-refresh" class="action secondary">刷新记录</button><small>共 ${list.total} 条</small></form><p class="panel-note">每条研究可查看结果、假设、生成代码和阶段记录。历史缺失信息会保留为未记录；完整指标可在统一比较页并列查看。</p>`;
 const pager=`<div class="toolbar"><button class="action secondary" id="research-prev" ${state.researchOffset===0?'disabled':''}>上一页</button><button class="action secondary" id="research-next" ${list.next_offset===null?'disabled':''}>下一页</button></div>`;
 const ready=`<details><summary>环境与执行能力</summary><p>聊天模型：${esc(runtime.chat?.model||'未连接')}；Embedding：${esc(runtime.embedding?.model||'未连接')}；Linux Docker：${runtime.runtime?.linux_container_available?'可用':'不可用'}。</p><p>当前支持查看已有研究与比较结果；界面启动/停止研究尚未接入。</p><p class="panel-note">同步已有历史产物：在 RD-Agent 目录执行 .venv/bin/python ../qlib/scripts/export_rdagent_research.py --trust-local-artifacts --synthetic；刷新只重新读取已导出的快照，不执行研究。</p></details>`;
 document.getElementById('content').innerHTML=`<div class="stack">${card('研究记录',toolbar+researchTable(list.items)+pager)}${card('运行环境',ready)}</div>`;
 document.getElementById('research-search').onsubmit=e=>{e.preventDefault();state.researchQuery=document.getElementById('research-query').value;state.researchOffset=0;render();};
 document.getElementById('research-prev').onclick=()=>{state.researchOffset=Math.max(0,state.researchOffset-20);render();};
 document.getElementById('research-next').onclick=()=>{state.researchOffset=list.next_offset;render();};
 document.getElementById('research-refresh').onclick=async()=>{await refreshRuns();render();};bindResearch();
}
async function refreshRuns(){
 let items=[],cursor=null;
 do{const page=await api('/v1/runs?limit=100'+(cursor?'&cursor='+encodeURIComponent(cursor):''));items.push(...page.items);cursor=page.next_cursor;}while(cursor&&items.length<1000);
 state.runs=items;renderRuns();
}

async function renderSystem(){
 const [stats,health]=await Promise.all([api('/v1/observability'),api('/v1/health')]);
 document.getElementById('content').innerHTML=`<div class="stack">${card('API 运行观测',`${badge('measured')}${badge('limited')}<p class="panel-note">仅本工作台HTTP服务的实测，非Qlib或RD-Agent错误率。</p><div class="metric-row"><div class="metric-box"><small>5xx 错误率</small><strong>${stats.error_rate===null?'无样本':fmt(stats.error_rate*100)+'%'}</strong></div><div class="metric-box"><small>已完成请求</small><strong>${stats.completed_requests}</strong></div><div class="metric-box"><small>4xx / 5xx</small><strong>${stats.client_errors} / ${stats.server_errors}</strong></div><div class="metric-box"><small>P95 响应耗时</small><strong>${fmt(stats.p95_ms)} ms</strong></div></div><p class="panel-note">覆盖 ${fmt(stats.coverage_seconds,0)} / 300 秒；${stats.truncated?'达到容量上限，统计覆盖不完整':'未截断'}。${esc(stats.scope)}<br>采集开始 ${esc(stats.collection_started_at)}</p><button id="system-refresh" class="action secondary">刷新观测</button>`)}${await capabilityPanel()}${card('存储与任务',`${badge('unsupported')}<p>本地结果库：${esc(health.status)}。</p><p class="panel-note">任务 Attempt 监控尚未接入；历史过程不完整不等同于失败，不能用于推算任务失败率。</p>`)}</div>`;
 document.getElementById('system-refresh').onclick=()=>render();
}
async function renderDataEvidence(){
 const selected=await selectedRevision();
 if(!selected){document.getElementById('content').innerHTML=empty('选择研究以查看其数据与执行证据');return;}
 const {summary,detail}=selected, e=detail.evidence, scenario=e.cn_scenario;
 document.getElementById('content').innerHTML=`<div class="stack">${card('当前研究的数据证据',`${badge('limited')}<h3>${esc(summary.run.title)}</h3><p>${sample(summary.run)}</p><dl class="context-grid"><dt>数据集</dt><dd>${esc(summary.run.dataset.id)}</dd><dt>内容版本</dt><dd>${esc(summary.run.dataset.version||'未记录')}</dd><dt>日历</dt><dd>${esc(scenario?.calendar_id||'未记录')}</dd><dt>执行情景指纹</dt><dd>${esc(scenario?.fingerprint||'未记录')}</dd><dt>研究模式</dt><dd>${esc(scenario?.mode||'未记录')}</dd></dl><p class="panel-note">情景指纹描述配置，不能代替行情内容版本。此页展示已有结果证据，供应商数据目录和真实PIT校验尚未接入。</p>`)}${reviewPanel(await api(`/v1/runs/${summary.run_id}/review`),e)}</div>`;
}
function renderUnavailable(view){
  const info={live:['实时数据尚未接入','目前没有行情流会话或延迟记录。上线前需要数据供应商、交易日历、重连与缺口策略。'],data:['数据目录尚未接入','当前运行可查看结果来源，数据快照与质量报告将在数据层实施后出现。'],system:['系统遥测尚未接入','API和任务错误率没有采集样本，当前不显示0%。健康接口仅反映本地结果库可用性。']}[view];
  document.getElementById('content').innerHTML=`<div class="grid">${card(info[0],badge('unsupported')+empty(info[1]))}</div>`;
}
async function render(){
  setNotice();document.getElementById('content').innerHTML='<div class="loading">加载中…</div>';
  try{
    if(state.view==='overview')await renderOverview();
    else if(state.view==='backtest')await renderBacktest();
    else if(state.view==='training')await renderTraining();
    else if(state.view==='compare')await renderCompare();
    else if(state.view==='agent')await renderAgent();
    else if(state.view==='system')await renderSystem();
    else if(state.view==='data')await renderDataEvidence();
    else renderUnavailable(state.view);
  }catch(error){setNotice(error.message);document.getElementById('content').innerHTML=empty('页面加载失败，请重试。');}
}
async function init(){
  document.querySelectorAll('.nav').forEach(button=>button.onclick=()=>setView(button.dataset.view));
  document.getElementById('run-search').oninput=event=>{state.search=event.target.value.toLocaleLowerCase().trim();renderRuns();};
  window.addEventListener('hashchange',()=>{const view=location.hash.slice(1)||'overview';if(view!==state.view)setView(view);});
  try{
    const [runs,health]=await Promise.all([api('/v1/runs?limit=30'),api('/v1/health')]);
    state.runs=runs.items;await refreshRuns();
    if(!state.selected||!state.runs.some(x=>x.run_id===state.selected))state.selected=state.runs[0]?.run_id||null;
    state.compareIds=state.compareIds.filter(id=>state.runs.some(x=>x.run_id===id));
    if(!hasCompareQuery)state.compareIds=state.runs.slice(0,2).map(x=>x.run_id);
    document.getElementById('health-label').textContent=health.status==='ok'?'正常':'异常';
    renderRuns();setView(state.view);
  }catch(error){setNotice(error.message);document.getElementById('content').innerHTML=empty('无法连接本地结果服务');}
}
init();
