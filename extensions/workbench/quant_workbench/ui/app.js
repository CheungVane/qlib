const initialQuery = new URLSearchParams(location.search);
const hasCompareQuery = initialQuery.has('compare');
const state = {renderGeneration:0, revision: initialQuery.get("revision"), seriesOffsets:{}, runs: [], selected: initialQuery.get('run'), compareIds: (initialQuery.get('compare') || '').split(',').filter(Boolean), researchId: initialQuery.get('research'), researchOffset:0, researchQuery:'', search: '', executionKey:null, view: location.hash.slice(1) || 'overview'};
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
  const generation=state.renderGeneration;
  const response=await fetch(path,{headers:{'Accept':'application/json'}});
  const body=await response.json().catch(error=>{if(response.ok)throw error;return {};});
  if(generation!==state.renderGeneration){const error=new Error('页面已切换');error.name='StaleRender';throw error;}
  if(!response.ok){
    const error=new Error(`${body.message||'请求失败 '+response.status}${body.request_id?' · request_id: '+body.request_id:''}`);
    error.status=response.status;error.code=body.code;throw error;
  }
  return body;
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
function selectRun(id,revision=null){state.selected=id;state.revision=revision;const url=new URL(location.href);url.searchParams.set('run',id);if(revision)url.searchParams.set('revision',revision);else url.searchParams.delete('revision');history.replaceState(null,'',url);renderRuns();render();}
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
function chart(points,unit='CNY',axis='trading_date'){
  const valid=points.filter(p=>typeof p.value==='number');
  if(!valid.length)return empty('没有有效观测；缺测不填零');
  const values=valid.map(p=>p.value),lo=Math.min(...values),hi=Math.max(...values),range=hi-lo||1;
  const position=p=>axis==='step'?Number(p.x):axis==='scalar'?0:Date.parse(p.x);
  const start=position(points[0]),end=position(points.at(-1));
  const xy=p=>[48+(position(p)-start)/(end-start||1)*732,235-(p.value-lo)/range*185];
  let segments=[],segment=[];
  for(const p of points){if(typeof p.value==='number')segment.push(xy(p));else if(segment.length){segments.push(segment);segment=[];}}
  if(segment.length)segments.push(segment);
  const lines=segments.map(seg=>seg.length===1?`<circle cx="${seg[0][0]}" cy="${seg[0][1]}" r="3" fill="currentColor"/>`:`<polyline points="${seg.map(([x,y])=>`${x.toFixed(2)},${y.toFixed(2)}`).join(' ')}" class="chart-line"/>`).join('');
  const gaps=points.filter(p=>p.value===null);
  return `<svg class="chart" viewBox="0 0 820 270" role="img" aria-label="${esc(unit)} ${esc(axis)}序列，${valid.length}个有效点、${gaps.length}个缺测点"><line x1="48" y1="235" x2="780" y2="235" class="chart-grid"/>${lines}<text x="48" y="42" class="chart-label">${esc(fmt(hi))} ${esc(unit)}</text><text x="48" y="255" class="chart-label">${esc(points[0].x)}</text><text x="665" y="255" class="chart-label">${esc(points.at(-1).x)}</text></svg>${gaps.length?`<p class="warning">缺测 ${gaps.length} 点，已断线：${esc([...new Set(gaps.map(p=>p.reason))].join('；'))}</p>`:''}`;
}
function seriesKey(id,metric,revision){return JSON.stringify([id,metric,revision]);}
function availabilityLabel(value){return {available:'已记录',empty:'暂无观测',not_recorded:'未记录',unsupported:'不支持',error:'读取失败'}[value]||'未记录';}
function seriesPanel(payload){
  if(!payload)return empty('未记录：该结果没有此序列');
  const entry=payload.series;
  const availability={empty:'暂无观测',not_recorded:'未记录',unsupported:'引擎不支持',error:'源序列读取失败'};
  if(entry.availability!=='available')return empty(availability[entry.availability]||entry.availability);
  const offset=payload.offset,total=payload.total_points;
  const button=(label,target,disabled)=>`<button class="action secondary" data-series-page="${target}" data-series-run="${esc(payload.run_id)}" data-series-metric="${esc(entry.metric_id)}" data-series-revision="${esc(payload.revision_id)}" ${disabled?'disabled':''}>${label}</button>`;
  return chart(entry.points,entry.unit,entry.axis)+`<p class="panel-note">当前第 ${offset+1}—${offset+entry.points.length} 点 / 共 ${total} 点；${payload.downsampled?'已降采样':'原始观测，未降采样'}。摘要按完整结果计算。</p><div class="toolbar">${button('上一页',Math.max(0,offset-payload.limit),offset===0)}${button('下一页',payload.next_offset??offset,payload.next_offset===null)}</div>`;
}
function bindSeriesPages(){document.querySelectorAll('[data-series-page]').forEach(b=>b.onclick=()=>{
  state.seriesOffsets[seriesKey(b.dataset.seriesRun,b.dataset.seriesMetric,b.dataset.seriesRevision)]=Number(b.dataset.seriesPage);render();
});}
async function selectedRevision(){
  const id=state.selected;
  if(!id)return null;
  const summary=state.runs.find(x=>x.run_id===id)||await api(`/v1/runs/${encodeURIComponent(id)}`);
  const detail=await api(`/v1/runs/${encodeURIComponent(id)}/revisions/${encodeURIComponent(state.revision||summary.revision_id)}`);
  return {summary:{...summary,revision_id:detail.revision_id,run:{...detail.run,provenance:detail.provenance?.run}},detail};
}
async function series(id,metric,revisionId=state.runs.find(x=>x.run_id===id)?.revision_id){
  const offset=state.seriesOffsets[seriesKey(id,metric,revisionId)]||0;
  try{return await api(`/v1/runs/${encodeURIComponent(id)}/series?metric_id=${encodeURIComponent(metric)}&offset=${offset}${revisionId?'&revision_id='+encodeURIComponent(revisionId):''}`);}
  catch(error){if(error.status===404&&error.code==='not_found')return null;throw error;}
}
async function renderBacktest(){
  const selected=await selectedRevision();if(!selected){document.getElementById('content').innerHTML=empty('请先在左侧选择一个运行');return;}
  const {summary,detail}=selected, id=summary.run_id;
  const review=await api(`/v1/runs/${id}/review?revision_id=${summary.revision_id}`);
  const [equity,drawdown,cost,turnover]=await Promise.all(['platform.equity','platform.drawdown','native.qlib.total_cost','native.qlib.turnover'].map(x=>series(id,x,summary.revision_id)));
  const points=equity?.series.points||[];
  const last=review.facts.ending_equity;
  const dd=review.facts.max_observed_drawdown;
  const totalCost=review.facts.total_cost;
  const kpis=`<div class="metric-row"><div class="metric-box"><small>期末权益 ${originBadge(equity?.series?.provenance)}</small><strong>${fmt(last)} <small>${esc(equity?.series?.unit||'币种未记录')}</small></strong></div><div class="metric-box"><small>首末观测权益变化 ${badge('derived')}</small><strong>${typeof review.facts.observed_equity_change==='number'?fmt(review.facts.observed_equity_change*100)+'%':'未知'}</strong></div><div class="metric-box"><small>最大观测权益回撤 ${badge('derived')}</small><strong>${typeof dd==='number'?fmt(dd*100)+'%':'未知'}</strong></div><div class="metric-box"><small>引擎</small><strong>${esc(summary.run.engine.id)}</strong></div></div>`;
  const heading=`<div class="heading-row"><div><h2>${esc(summary.run.title)}</h2><p class="panel-note">${statusLabel(summary.run.status)} ${sample(summary.run)} · 结果版本 ${esc(summary.revision_id.slice(0,12))} · 数据版本 ${esc(summary.run.dataset.version||'未知')}</p></div></div>`;
  const misc=`<p class="panel-note">${originBadge(cost?.series?.provenance)} 累计费用（源报告末点）：${fmt(totalCost)} ${esc(cost?.series?.unit||'币种未记录')}（${availabilityLabel(cost?.series.availability)}）<br>换手序列：${availabilityLabel(turnover?.series.availability)} · 撮合与费用口径请查原运行配置。</p>`;
  document.getElementById('content').innerHTML=`<div class="stack">${card('运行概况',heading+kpis)}${provenancePanel(detail)}${reviewPanel(review,detail.evidence)}${card('权益曲线',seriesPanel(equity),equity?.series?.provenance?.source||'来源未核实')}${card('成本与换手',misc)}${card('来源证据',`<details><summary>展开原始证据</summary><pre class="panel-note">${esc(JSON.stringify(detail.evidence,null,2))}</pre></details>`,'未知事实保留为空')}</div>`;
}
async function renderTraining(){
  const selected=await selectedRevision();if(!selected){document.getElementById('content').innerHTML=empty('请先选择一个运行');return;}
  const {summary,detail}=selected;
  const review=await api(`/v1/runs/${summary.run_id}/review?revision_id=${summary.revision_id}`);
  const metrics=detail.series.filter(x=>x.axis==='step'||x.metric_id.toLowerCase().includes('ic')||x.metric_id.includes('l2'));
  let rows=[];
  for(const metric of metrics.slice(0,30)){
    const value=metric.summary?.last;
    rows.push(`<tr><td>${esc(metric.metric_id)} ${originBadge(metric.provenance)}${metric.axis==='step'&&metric.point_count<2?badge('limited'):''}</td><td>${esc(metric.axis)}</td><td>${esc(fmt(value,5))}</td><td>${esc(metric.unit)}</td><td>${availabilityLabel(metric.availability)}${metric.summary?.last_reason?' · '+esc(metric.summary.last_reason):''}</td></tr>`);
  }
  const stageText=summary.run.stages?.map(x=>`${esc(x.kind)}：${esc(x.status)}`).join(' · ')||'阶段信息未知';
  document.getElementById('content').innerHTML=`<div class="stack">${card('训练运行',`<div class="heading-row"><h2>${esc(summary.run.title)}</h2>${sample(summary.run)}</div><p class="panel-note">${stageText}<br>引擎运行时版本：${esc(summary.run.engine.version||'未知')} · 数据版本：${esc(summary.run.dataset.version||'未知')}</p>`)}${provenancePanel(detail)}${reviewPanel(review,detail.evidence)}${card('训练与信号指标',rows.length?`<table class="table"><thead><tr><th>指标</th><th>轴</th><th>末点</th><th>单位</th><th>记录状态</th></tr></thead><tbody>${rows.join('')}</tbody></table>`:empty('该运行没有可显示的训练指标'))}</div>`;
}
const compareReasons = {legacy_experiment_attribution_unverified:'旧版导出实验归属未复核',dataset_id_differs:'数据集身份不同',coverage_axis_differs:'有效观测坐标不同',missing_observations:'序列有缺测',step_kind_differs:'训练步定义未知或不同',evaluation_unknown_or_differs:'评估口径未知或不同',initial_equity_unknown_or_differs:'初始资金未知或不同',initial_equity_invalid:'缺少有效初始资金',cashflow_policy_unknown_or_differs:'现金流口径未知或不同',cashflow_not_supported:'尚不支持该现金流口径',price_basis_unknown_or_differs:'价格口径未知或不同',benchmark_id_unknown_or_differs:'基准未知或不同',handwritten_fixture_present:'包含手写演示样本，不支持研究排名',date_window_differs:'回测日期窗口不同',first_equity_differs:'首个观测权益不同',execution_scenario_unknown_or_differs:'执行/费用情景未知或不同',unit_differs:'单位不同',axis_differs:'序列轴不同',definition_id_differs:'指标定义不同',calendar_id_differs:'交易日历不同',currency_differs:'币种不同',synthetic_and_real_mixed:'模拟与真实数据混用',dataset_version_unknown_or_differs:'数据版本未知或不同'};
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
    const selectedRun={...detail.run,provenance:detail.provenance?.run};
    const first=review.facts.first_observed_equity,last=review.facts.ending_equity;
    const bounds=review.facts.equity_coverage;
    const heading=`<div class="heading-row"><p class="panel-note">${esc(selectedRun.engine.id)} · ${esc(selectedRun.dataset.id)} · ${sample(selectedRun)}</p><button class="link-button" data-open-run="${esc(id)}">查看详情</button></div>`;
    const facts=`<div class="metric-row"><div class="metric-box"><small>期末权益</small><strong>${fmt(last)} <small>${esc(result?.series.unit||'')}</small></strong></div><div class="metric-box"><small>首末观测权益变化 ${badge('derived')}</small><strong>${typeof review.facts.observed_equity_change==='number'?fmt(review.facts.observed_equity_change*100)+'%':'未知'}</strong></div><div class="metric-box"><small>数据版本</small><strong>${esc(selectedRun.dataset.version||'未知')}</strong></div></div>`;
    const context=`<dl class="context-grid"><dt>报告区间</dt><dd>${esc(bounds?.start||'未记录')} → ${esc(bounds?.end||'未记录')}</dd><dt>最大观测回撤 ${badge('derived')}</dt><dd>${typeof review.facts.max_observed_drawdown==='number'?fmt(review.facts.max_observed_drawdown*100)+'%':'未知'}</dd><dt>累计成本</dt><dd>${fmt(review.facts.total_cost)} CNY</dd><dt>质量</dt><dd>${badge(review.quality?'custom':'missing')} ${esc(review.quality?.status||'未记录')}</dd><dt>执行情景</dt><dd>${esc(scenario?.fingerprint?.slice(0,12)||'未知')}</dd><dt>佣金 / 最低费</dt><dd>${esc(scenario?.commission_both??'未知')} / ${esc(scenario?.minimum_commission??'未知')}</dd><dt>结果版本</dt><dd>${esc(revisionId.slice(0,12))}</dd></dl>`;
    return card(selectedRun.title,heading+facts+context+seriesPanel(result),esc(selectedRun.created_at.slice(0,10)));
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
const agentReason = {chat_not_configured:'聊天模型或密钥未配置',embedding_not_configured:'Embedding 模型或对应密钥未配置',embedding_service_unavailable:'本地 Embedding 服务或模型暂不可用',native_runtime_unverified:'RD-Agent 官方仅支持 Linux；当前系统的原生因子流程尚未验证',docker_not_available:'Linux Docker 引擎当前不可用',factor_image_unverified:'因子执行所需的 CPU/arm64 镜像尚未验证',factor_scenario_not_aligned:'因子模板的数据区间与万二费用情景尚未对齐',checkout_missing:'RD-Agent checkout 不存在',checkout_not_configured:'未指定 RD-Agent checkout'};
const executionReasonLabels = {rdagent_checkout:'RD-Agent checkout 不存在',rdagent_venv:'RD-Agent 虚拟环境缺失','rdagent.checkout':'RD-Agent checkout 不存在','rdagent.venv':'RD-Agent 虚拟环境缺失','rdagent.chat':'聊天模型或密钥未配置（loop 必需）','rdagent.embedding':'本地 Embedding 服务或模型不可用（loop 必需）','rdagent.docker':'Linux Docker 引擎不可用','rdagent.image':'因子执行镜像未构建','rdagent.resources':'Docker 资源低于下限（需至少 2 CPU、4GiB）','rdagent.data_snapshot':'该情景指纹的容器数据快照尚未物化','rdagent.template':'模板与当前情景指纹不一致','rdagent.profile':'CN 情景配置不可用','platform.attempt_store':'平台 Attempt 存储不可用','cn.profile':'CN 情景配置不可用','cn.data_snapshot':'本机数据快照尚未物化','cn.calendar':'交易日历未覆盖研究区间','cn.fee_scenario':'费用情景缺失','cn.engine_env':'Qlib 虚拟环境缺失','cn.attempt_workspace':'执行工作目录不可写'};
function newIdempotencyKey(){return (crypto.randomUUID?crypto.randomUUID():`${Date.now()}-${Math.random().toString(16).slice(2)}`);}
function reasonLabel(id){return executionReasonLabels[id]||agentReason[id]||id;}
function outcomeSummary(outcome){
 if(!outcome)return '未记录';
 const parts=[];
 const quality=outcome.quality;
 if(quality)parts.push(`质量 ${quality.status||'未知'} · 有效IC ${quality.valid_ic_days??'未知'}天 · 交易 ${quality.trade_days??'未知'}天`);
 if(outcome.evidence)parts.push(`指标 ${outcome.evidence.metric_count??'未知'}项`);
 if(outcome.artifacts?.mlflow_runs?.length)parts.push(`MLflow run ${outcome.artifacts.mlflow_runs.map(x=>x.slice(0,8)).join('、')}`);
 if(outcome.research_sessions_synced?.length)parts.push(`研究会话 ${outcome.research_sessions_synced.length}个`);
 if(outcome.collection_error)parts.push('摘要收集受限');
 if(outcome.result_import==='manual_import_required')parts.push('结果需显式导入');
 return parts.join(' · ')||'已记录';
}
function executionChecks(entry){
 const required=entry.reasons||[];
 return `<ul class="checklist">${entry.checks.map(c=>{const blocking=required.includes(c.id);const informational=!(c.required_for||[]).includes(entry.kind);return `<li class="${c.status==='ok'?'ok':'warn'}">${c.status==='ok'?'✓':'!'} ${esc(reasonLabel(c.id))}${informational?' <small>（该入口非必需）</small>':(blocking?' <small class="warning">（阻塞启动）</small>':'')}<br><small>${esc(c.detail||'')}</small></li>`;}).join('')}</ul>`;
}
function executionPanel(catalog,attempts){
 const available=catalog.items.filter(x=>x.available);
 const options=catalog.items.map(x=>`<option value="${esc(x.kind)}" ${x.available?'':'disabled'}>${esc(x.label)}${x.available?'':'（前置条件未满足）'}</option>`).join('');
 const form=`<form id="execution-form" class="toolbar"><label class="sr-only" for="execution-kind">执行入口</label><select id="execution-kind" aria-label="执行入口" ${available.length?'':'disabled'}>${options}</select><input id="execution-note" aria-label="备注" placeholder="可选备注（随 Attempt 保存）"><button class="action" id="execution-submit" ${available.length?'':'disabled'}>启动研究</button><small>启动请求期间复用同一幂等键（重复点击不会产生第二个进程）；启动成功或去重后自动换用新键，可再次启动新 Attempt。</small></form><p id="execution-feedback" class="panel-note">${available.length?'前置条件已满足，可启动隔离进程执行。':'当前没有可用执行入口；下方逐项列出缺失条件，不会提供假启动。'}</p>`;
 const entries=catalog.items.map(x=>`<details class="execution-entry" ${x.available?'':'open'}><summary>${esc(x.label)} ${x.probe?badge('limited'):''} ${x.available?badge('measured'):badge('unsupported')}</summary><p class="panel-note">执行器 <code>${esc(x.executor_id)}</code> · 数据性质 ${esc(x.data_nature||'未记录')}<br>${esc(x.description||'')}</p>${executionChecks(x)}</details>`).join('');
 return card('启动研究（隔离进程）',form+entries,'前置条件逐项核对；探针类执行标记为集成探针');
}
function attemptTable(attempts){
 if(!attempts.length)return empty('还没有执行记录。启动一次研究后，这里会显示状态、退出码、结果摘要与日志入口。');
 const rows=attempts.map(a=>{
  const actions=[];
  if(a.has_log)actions.push(`<button class="link-button" data-attempt-log="${esc(a.attempt_id)}">日志尾部</button>`);
  if(['queued','running'].includes(a.status))actions.push(`<button class="link-button" data-attempt-cancel="${esc(a.attempt_id)}">${a.cancel_pending?'取消请求中…':'取消'}</button>`);
  const started=(a.started_at||a.created_at||'').replace('T',' ').slice(0,19);
  const ended=a.ended_at?('→ '+a.ended_at.replace('T',' ').slice(0,19)):'进行中';
  const exitCode=(a.exit_code===null||a.exit_code===undefined)?'未知':esc(a.exit_code);
  return `<tr><td><code>${esc(a.attempt_id.slice(0,8))}</code><br><small>${esc(a.label)}${a.probe?' · 集成探针':''}</small></td><td>${statusLabel(a.status)}${a.cancel_pending?'<br><small class="warning">取消请求中</small>':''}</td><td><small>${esc(started)}<br>${esc(ended)}</small></td><td>${exitCode}${a.error_code?`<br><small class="warning">${esc(a.error_code)}</small>`:''}</td><td>${esc(outcomeSummary(a.outcome))}${a.error_message?`<br><small class="warning">${esc(a.error_message)}</small>`:''}<br><small>指纹 ${esc((a.config_fingerprint||'未知').slice(0,10))} · 工作目录 ${esc(a.workspace_label||'未记录')}</small></td><td>${actions.join(' ')||'—'}</td></tr>`;
 }).join('');
 return `<div class="table-scroll"><table class="table"><thead><tr><th>Attempt</th><th>状态</th><th>时间</th><th>退出码</th><th>结果与证据</th><th>操作</th></tr></thead><tbody>${rows}</tbody></table></div><div id="attempt-log"></div>`;
}
function bindExecution(catalog){
 const form=document.getElementById('execution-form');
 if(form)form.onsubmit=async event=>{
  event.preventDefault();
  const kind=document.getElementById('execution-kind').value;
  const note=document.getElementById('execution-note').value.trim();
  const button=document.getElementById('execution-submit');
  button.disabled=true;
  try{
   const response=await fetch('/v1/executions',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({kind,params:note?{note}:{},idempotency_key:state.executionKey})});
   const body=await response.json().catch(()=>({}));
   if(!response.ok){
    const detail=(body.details?.reasons||[]).map(reasonLabel).join('；');
    throw new Error(`${body.message||'启动失败'}${detail?'：'+detail:''}${body.request_id?' · request_id: '+body.request_id:''}`);
   }
   state.executionKey=newIdempotencyKey();
   setNotice(body.created?`已启动 ${body.attempt.label}（${body.attempt.attempt_id.slice(0,8)}）`:`已存在同一幂等键的 Attempt，未重复启动（${body.attempt.status}）`);
   render();
  }catch(error){setNotice(error.message);button.disabled=false;}
 };
 const select=document.getElementById('execution-kind');
 if(select)select.onchange=()=>{state.executionKey=newIdempotencyKey();render();};
 document.querySelectorAll('[data-attempt-cancel]').forEach(button=>button.onclick=async()=>{
  if(!window.confirm('取消需要执行器确认进程结束后才落终态；确认请求取消？'))return;
  button.disabled=true;
  try{
   const response=await fetch(`/v1/executions/${encodeURIComponent(button.dataset.attemptCancel)}/cancel`,{method:'POST'});
   const body=await response.json().catch(()=>({}));
   if(!response.ok)throw new Error(body.message||'取消失败');
   setNotice(body.cancel_confirmed?`已确认进程结束，终态 ${body.attempt.status}`:`未确认取消（${body.reason||'未知'}），当前状态 ${body.attempt.status}`);
  }catch(error){setNotice(error.message);}
  render();
 });
 document.querySelectorAll('[data-attempt-log]').forEach(button=>button.onclick=async()=>{
  const target=document.getElementById('attempt-log');
  target.innerHTML='正在读取日志尾部…';
  try{
   const response=await fetch(`/v1/executions/${encodeURIComponent(button.dataset.attemptLog)}/log?tail=80`);
   const body=await response.json().catch(()=>({}));
   if(!response.ok)throw new Error(body.message||'日志读取失败');
   target.innerHTML=`<details open><summary>日志尾部（脱敏；最多80行，${body.truncated?'已截断':'未截断'}）</summary><pre>${esc((body.lines||[]).join('\n'))}</pre></details>`;
  }catch(error){target.innerHTML=`<p class="warning">${esc(error.message)}</p>`;}
 });
}
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
 if(r.status==='session_index'){document.getElementById('content').innerHTML=card('会话内实验',`<button class="action secondary" id="research-index-back">返回研究列表</button><p>按实验查看结果，旧会话合并结果已停止作为当前证据。</p>${(r.iterations||[]).map(x=>`<p><button class="link-button" data-research="${esc(x.id)}">${esc(x.title)}</button> ${esc(x.status)}</p>`).join('')||empty('尚未恢复实验')}`);bindResearch();document.getElementById('research-index-back').onclick=()=>{state.researchId=null;const u=new URL(location.href);u.searchParams.delete('research');history.replaceState(null,'',u);render();};return;}
 if(r.platform_run_id){r.review=await api(`/v1/runs/${r.platform_run_id}/review?revision_id=${r.revision_id}`);r.resultDetail=await api(`/v1/runs/${r.platform_run_id}/revisions/${r.revision_id}`);r.evidence=r.resultDetail.evidence;}
 const facts=`<div class="heading-row"><div><h2>${esc(r.title)}</h2><p class="panel-note">${r.synthetic?'<span class="sample">模拟数据</span>':''} ${esc(r.session)}<br>源事件更新 ${esc(r.updated_at)} · 快照采集 ${esc(r.observed_at)}</p></div><button class="link-button" id="research-back">返回研究列表</button></div><p>${r.status==='result_available'?'已找到回测报告。进程退出状态未记录。':'未找到完整回测结果；可查看已经记录的过程。'}</p>${r.platform_run_id?`<button class="action" id="research-result">打开统一回测详情</button> <button class="action secondary" data-research-compare="${r.platform_run_id}">加入比较</button>`:''}`;
 const metricTop=`<div class="metric-row"><div class="metric-box"><small>IC ${badge('native')}</small><strong>${fmt(r.metrics?.IC,4)}</strong></div><div class="metric-box"><small>成本后年化超额（源口径） ${badge('native')}</small><strong>${typeof r.metrics?.['1day.excess_return_with_cost.annualized_return']==='number'?fmt(r.metrics['1day.excess_return_with_cost.annualized_return']*100)+'%':'未记录'}</strong></div><div class="metric-box"><small>因子数</small><strong>${r.factor_count??'未记录'}</strong></div></div>`;
 const metrics=Object.entries(r.metrics||{}).map(([k,v])=>`<tr><td>${esc(researchMetricNames[k]||k)}</td><td>${fmt(v,6)}</td></tr>`).join('');
 const factors=(r.factors||[]).map(f=>`<details class="factor"><summary>${esc(f.factor_name||'因子')} — ${esc(f.description||'暂无说明')}</summary><p>公式</p><pre>${esc(f.factor_formulation)}</pre><p>变量</p><pre>${esc(f.variables)}</pre><details><summary>查看生成代码</summary><pre>${esc(f.code||'代码未记录')}</pre></details></details>`).join('');
 const steps=(r.events||[]).map(e=>`<details class="timeline-step"><summary><span>${esc(stageLabel(e.stage))}</span><small>${esc(e.at)}</small></summary>${typeof e.content==='string'?`<pre>${esc(e.content)}</pre>`:readableFields(e.content)}</details>`).join('');
 document.getElementById('content').innerHTML=`<div class="stack">${card('研究结果',facts)}${r.resultDetail?provenancePanel(r.resultDetail):card('来源与限制',badge('limited')+' 仅历史日志摘录；没有完整结果，不等于研究失败。')}${r.review?reviewPanel(r.review,r.evidence):''}${r.warnings?.length?card('产物缺口',r.warnings.map(x=>`<p>${esc(x)}</p>`).join('')):''}${card('结果指标',metrics?`${metricTop}<details><summary>原生指标（保留源口径，空值不填零）</summary><table class="table"><tbody>${metrics}</tbody></table></details>`:empty('没有标量指标；若已生成报告，可在统一回测详情查看权益与费用'))}${card('因子与实现',badge('opinion')+'<p class="panel-note">Agent生成的定义和代码；可执行不等于因子有效，文字声称无未来信息未被独立认证。</p>'+(factors||empty('未记录因子定义；基线回测可能只使用基础特征')))}${card('Agent 评审意见',r.feedback?`${badge('opinion')}<p class="panel-note">模型原文，可能包含错误解释；与已记录数值分开看待。</p>${readableFields(r.feedback)}<p class="panel-note">这是 Agent 的研究反馈，不是平台的实盘建议。</p>`:empty('评审反馈未记录'))}${card('过程时间线',badge('limited')+'<p class="panel-note">离线历史摘录，非实时进度；最多300条，长日志/代码可能截断，未展示完整提示词。标题与结果条目数由工作台编排。</p>'+(steps||empty('没有可恢复的研究阶段')),'点击阶段展开日志 / 耗时 / 反馈')}</div>`;
 document.getElementById('research-back').onclick=()=>{state.researchId=null;const u=new URL(location.href);u.searchParams.delete('research');history.replaceState(null,'',u);render();};
 const result=document.getElementById('research-result');if(result)result.onclick=()=>{selectRun(r.platform_run_id,r.revision_id);setView('backtest');};bindResearch();
}
async function renderAgent(){
 if(state.researchId){await renderResearchDetail();return;}
 const [list,runtime,catalog,attempts]=await Promise.all([api(`/v1/research?limit=20&offset=${state.researchOffset}&query=${encodeURIComponent(state.researchQuery)}`),api('/v1/agents/rdagent'),api('/v1/executions/catalog'),api('/v1/executions?limit=20')]);
 if(catalog.items.length&&!state.executionKey)state.executionKey=newIdempotencyKey();
 const toolbar=`<form id="research-search" class="toolbar"><input aria-label="搜索研究" id="research-query" placeholder="搜索因子名、日期、状态" value="${esc(state.researchQuery)}"><button class="action">搜索</button><button type="button" id="research-refresh" class="action secondary">刷新记录</button><small>共 ${list.total} 条</small></form><p class="panel-note">每条研究可查看结果、假设、生成代码和阶段记录。历史缺失信息会保留为未记录；完整指标可在统一比较页并列查看。</p>`;
 const pager=`<div class="toolbar"><button class="action secondary" id="research-prev" ${state.researchOffset===0?'disabled':''}>上一页</button><button class="action secondary" id="research-next" ${list.next_offset===null?'disabled':''}>下一页</button></div>`;
 const reasons=(runtime.execution?.reasons||[]).map(reasonLabel);
 const ready=`<details><summary>环境与执行能力</summary><p>聊天模型：${esc(runtime.chat?.model||'未连接')}；Embedding：${esc(runtime.embedding?.model||'未连接')}；Linux Docker：${runtime.runtime?.linux_container_available?'可用':'不可用'}。</p><p>界面可启动/取消隔离进程执行；被阻塞的入口会列出缺失条件${reasons.length?'（当前：'+esc(reasons.join('；'))+'）':''}。取消需执行器确认进程结束后才落终态。</p><p class="panel-note">同步已有历史产物：在 RD-Agent 目录执行 .venv/bin/python ../qlib/scripts/export_rdagent_research.py --trust-local-artifacts --synthetic；历史刷新只重新读取已导出的快照，不执行研究。</p></details>`;
 document.getElementById('content').innerHTML=`<div class="stack">${executionPanel(catalog,attempts.items)}${card('执行记录',attemptTable(attempts.items),'平台执行状态；结果进入结果库仍需显式导入')}${card('研究记录',toolbar+researchTable(list.items)+pager)}${card('运行环境',ready)}</div>`;
 document.getElementById('research-search').onsubmit=e=>{e.preventDefault();state.researchQuery=document.getElementById('research-query').value;state.researchOffset=0;render();};
 document.getElementById('research-prev').onclick=()=>{state.researchOffset=Math.max(0,state.researchOffset-20);render();};
 document.getElementById('research-next').onclick=()=>{state.researchOffset=list.next_offset;render();};
 document.getElementById('research-refresh').onclick=async()=>{await refreshRuns();render();};
 bindExecution(catalog);bindResearch();
 if(attempts.items.some(x=>['queued','running'].includes(x.status)))setTimeout(()=>{if(state.view==='agent'&&!state.researchId)render();},5000);
}
async function refreshRuns(){
 let items=[],cursor=null;
 do{const page=await api('/v1/runs?limit=100'+(cursor?'&cursor='+encodeURIComponent(cursor):''));items.push(...page.items);cursor=page.next_cursor;}while(cursor&&items.length<1000);
 state.runs=items;renderRuns();
}

async function renderSystem(){
 const [stats,health]=await Promise.all([api('/v1/observability'),api('/v1/health')]);
 document.getElementById('content').innerHTML=`<div class="stack">${card('API 运行观测',`${badge('measured')}${badge('limited')}<p class="panel-note">仅本工作台HTTP服务的实测，非Qlib或RD-Agent错误率。</p><div class="metric-row"><div class="metric-box"><small>5xx 错误率</small><strong>${stats.error_rate===null?'无样本':fmt(stats.error_rate*100)+'%'}</strong></div><div class="metric-box"><small>已完成请求</small><strong>${stats.completed_requests}</strong></div><div class="metric-box"><small>4xx / 5xx</small><strong>${stats.client_errors} / ${stats.server_errors}</strong></div><div class="metric-box"><small>P95 响应耗时</small><strong>${fmt(stats.p95_ms)} ms</strong></div></div><p class="panel-note">覆盖 ${fmt(stats.coverage_seconds,0)} / 300 秒；${stats.truncated?'达到容量上限，统计覆盖不完整':'未截断'}。${esc(stats.scope)}<br>采集开始 ${esc(stats.collection_started_at)}</p><button id="system-refresh" class="action secondary">刷新观测</button>`)}${await capabilityPanel()}${card('存储与任务',`${badge('measured')}<p>本地结果库：${esc(health.status)}（schema ${esc(health.schema_version)}）。</p><p class="panel-note">执行 Attempt 在“研究中心 → 执行记录”查看，含状态、退出码与日志尾部；本页的请求统计不代替任务失败率，历史过程不完整不等同于失败。</p>`)}</div>`;
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
  const generation=++state.renderGeneration;
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
    bindSeriesPages();
  }catch(error){if(generation!==state.renderGeneration||error.name==='StaleRender')return;setNotice(error.message);document.getElementById('content').innerHTML=empty('页面加载失败，请重试。')+'<button class="action" id="retry-page">重试</button>';document.getElementById('retry-page').onclick=()=>render();}
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
  }catch(error){if(error.name==='StaleRender')return;setNotice(error.message);document.getElementById('content').innerHTML=empty('无法连接本地结果服务');}
}
init();
