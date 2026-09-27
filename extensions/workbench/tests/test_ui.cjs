const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const {test}=require('node:test');
const source=fs.readFileSync(require('node:path').join(__dirname,'../quant_workbench/ui/app.js'),'utf8').replace(/init\(\);\s*$/,'');
// ids that exist in index.html; they are always resolvable, everything else must be rendered
const STATIC_IDS=['content','notice','page-title','page-subtitle','page-help','source-legend-help','health-label',
  'run-list','run-list-toggle','run-search','help-modal','help-modal-title','help-modal-body','help-modal-close'];
function htmlIds(html){return [...String(html).matchAll(/id="([^"]+)"/g)].map(m=>m[1]);}
function ui(fetch,options={}){
  const strict=!!options.strict;
  const elements={};
  const declared=new Set(STATIC_IDS);
  const make=id=>{
    // close enough to a real element that missing DOM APIs do not look like app bugs
    const el={textContent:'',hidden:false,value:'',dataset:{},style:{},
      querySelectorAll:()=>[],querySelector:()=>null,setAttribute(){},getAttribute(){return null;},
      focus(){},classList:{toggle(){},add(){},remove(){},contains(){return false;}}};
    let html='';
    Object.defineProperty(el,'innerHTML',{get:()=>html,set:value=>{html=String(value);htmlIds(html).forEach(x=>declared.add(x));}});
    return el;
  };
  const document={getElementById:id=>{
    if(elements[id])return elements[id];
    if(strict&&!declared.has(id))return null;
    return elements[id]=make(id);
  },querySelectorAll:()=>[],querySelector:()=>null};
  const context={URLSearchParams,URL,location:{search:'',hash:'',href:'http://localhost/'},Intl,fetch,document,history:{replaceState(){},pushState(){}},window:{addEventListener(){},innerWidth:1280,location:{hash:''}},crypto:require('node:crypto').webcrypto};
  vm.createContext(context);vm.runInContext(source,context);return {context,elements,run:code=>vm.runInContext(code,context)};
}
const response=(data,status=200)=>({ok:status===200,status,json:async()=>data});

test('R07: failures preserve request id; only absent series returns null',async()=>{
  const x=ui(async()=>response({message:'failed',request_id:'request-123',code:'internal_error'},500));
  await assert.rejects(x.run("series('r','m','v')"),/request-123/);
  x.context.fetch=async()=>{throw new Error('network down')};
  await assert.rejects(x.run("series('r','m','v')"),/network down/);
  x.context.fetch=async()=>response({code:'not_found'},404);
  assert.equal(await x.run("series('r','m','v')"),null);
  assert.match(x.run("seriesPanel({series:{availability:'error'}})"),/读取失败/);
  assert.match(x.run("seriesPanel({series:{availability:'unsupported'}})"),/不支持/);
  assert.match(x.run("seriesPanel({series:{availability:'empty'}})"),/暂无观测/);
});

test('R08: gaps break lines and preserve uneven coordinate spacing',()=>{
  const x=ui();
  const gap=x.run("chart([{x:0,value:1},{x:1,value:null,reason:'missing'},{x:100,value:3}],'ratio','step')");
  assert.equal((gap.match(/<polyline/g)||[]).length,0);
  assert.equal((gap.match(/<circle/g)||[]).length,2);
  assert.match(gap,/已断线/);
  const uneven=x.run("chart([{x:0,value:1},{x:1,value:2},{x:100,value:3}],'ratio','step')");
  assert.match(uneven,/55\.32,142\.50/);
});

test('R06: KPI uses full-revision review, bounded chart pages expose next offset',async()=>{
  const summary={run_id:'r',revision_id:'v',run:{title:'long',engine:{id:'other'},dataset:{version:'content'},status:'unknown',synthetic:true}};
  const details={...summary,evidence:{},series:[]};
  const review={facts:{ending_equity:500000,observed_equity_change:-.5,max_observed_drawdown:-.6,total_cost:100},gaps:[],findings:[],next_steps:[],conclusion:'test',basis:'full result'};
  const payload={run_id:'r',revision_id:'v',series:{metric_id:'platform.equity',unit:'CNY',axis:'step',availability:'available',points:[{x:0,value:1000000},{x:1999,value:999999}]},offset:0,limit:2000,total_points:2002,next_offset:2000,downsampled:false};
  const paths=[];
  const x=ui(async path=>{
    paths.push(path);
    if(path.includes('/review?'))return response(review);
    if(path.includes('/revisions/'))return response(details);
    if(path.includes('metric_id=platform.equity'))return response(payload);
    return response({code:'not_found'},404);
  });
  x.context.input=summary;x.run("state.runs=[input];state.selected='r'");
  await x.run('renderBacktest()');
  assert.match(x.elements.content.innerHTML,/<strong>500,000 <small>CNY/);
  assert.match(x.elements.content.innerHTML,/共 2002 点/);
  assert.match(x.elements.content.innerHTML,/data-series-page="2000"/);
  assert.equal(paths.filter(p=>p.includes('metric_id=platform.equity')).length,1);
  x.run("state.seriesOffsets[seriesKey('r','platform.equity','v')]=2000");
  await x.run("series('r','platform.equity','v')");
  assert.match(paths.at(-1),/offset=2000/);
});

test('R06: training last value uses full summary including zero',async()=>{
  const x=ui(async path=>response(path.includes('/review?')?{facts:{},gaps:[],findings:[],next_steps:[],conclusion:'test'}:{revision_id:'v',run:{title:'training',engine:{id:'engine'},dataset:{version:'d'}},evidence:{},series:[{metric_id:'loss',axis:'step',unit:'ratio',point_count:3000,summary:{last:0}}]}));
  x.run("state.selected='r';state.runs=[{run_id:'r',revision_id:'v'}]");
  await x.run('renderTraining()');assert.match(x.elements.content.innerHTML,/<td>0<\/td>/);
});

test('obsolete page requests cannot replace the current selection',async()=>{
  let finish;
  const x=ui(()=>new Promise(resolve=>{finish=resolve;}));
  const old=x.run("api('/old')");x.run('state.renderGeneration++');
  finish(response({title:'old'}));
  await assert.rejects(old,e=>e.name==='StaleRender');
});

test('EXEC09: a successful launch rotates the idempotency key so the same entry can run again',async()=>{
  const posts=[];
  const x=ui(async(path,options)=>{
    if(options?.method==='POST'){posts.push(JSON.parse(options.body));return response({created:true,attempt:{label:'桩入口',attempt_id:'abcdefgh-0000',status:'running'}});}
    if(path.startsWith('/v1/research'))return response({items:[],total:0,next_offset:null});
    return response({items:[]});
  });
  x.elements['execution-form']={innerHTML:'',textContent:''};
  x.elements['execution-kind']={innerHTML:'',textContent:'',value:'stub.kind'};
  x.elements['execution-note']={innerHTML:'',textContent:'',value:'note'};
  x.elements['execution-submit']={innerHTML:'',textContent:'',disabled:false};
  x.run("state.view='agent';state.executionKey='key-1';bindExecution({items:[]})");
  await x.elements['execution-form'].onsubmit({preventDefault(){}});
  await new Promise(resolve=>setTimeout(resolve,0));
  assert.equal(posts.length,1);
  assert.equal(posts[0].idempotency_key,'key-1');
  const rotated=x.run('state.executionKey');
  assert.notEqual(rotated,'key-1');
  await x.elements['execution-form'].onsubmit({preventDefault(){}});
  await new Promise(resolve=>setTimeout(resolve,0));
  assert.equal(posts.length,2);
  assert.equal(posts[1].idempotency_key,rotated);
  assert.notEqual(posts[1].idempotency_key,posts[0].idempotency_key);
});

const helpFixture={
  catalog:{items:[{kind:'stub.kind',executor_id:'stub',label:'桩入口',probe:false,data_nature:'test',
    description:'测试入口',available:true,reasons:[],
    checks:[{id:'stub.ready',status:'ok',detail:'就绪',required_for:['stub.kind']}]}]},
  attempts:[{attempt_id:'abcdefgh-0000-1111-2222-333333333333',kind:'stub.kind',label:'桩入口',probe:false,
    status:'running',has_log:true,cancel_pending:false,exit_code:null,started_at:'2026-09-26T00:00:00Z',
    created_at:'2026-09-26T00:00:00Z',ended_at:null,outcome:null,error_code:null,error_message:null,
    config_fingerprint:'f'.repeat(64),workspace_label:'ws'}],
};

test('U14: every rendered help icon resolves to a registry entry',()=>{
  const x=ui(async()=>response({items:[]}));
  const used=(html)=>[...html.matchAll(/data-help="([^"]+)"/g)].map(match=>match[1]);
  const keys=x.run('helpKeys');
  assert.ok(keys.length>=20);

  const panels=x.run(`executionPanel(${JSON.stringify(helpFixture.catalog)},${JSON.stringify(helpFixture.attempts)})`)
    +x.run(`attemptTable(${JSON.stringify(helpFixture.attempts)})`);
  const panelKeys=used(panels);
  assert.ok(panelKeys.length>=4,'execution surfaces must expose help entries');
  panelKeys.forEach(key=>assert.ok(keys.includes(key),`unknown help key rendered: ${key}`));
  assert.match(panels,/help-tip/);

  const misc=used(x.run("help('page.overview')+help('source.legend')+card('权益曲线','x','',null)"));
  misc.forEach(key=>assert.ok(keys.includes(key),`unknown help key rendered: ${key}`));

  const missingPages=x.run("['overview','backtest','training','compare','agent','live','data','system'].filter(v=>!HELP['page.'+v])");
  assert.deepEqual([...missingPages],[]);
  const orphanCards=x.run('Object.entries(cardHelp).filter(([,k])=>!HELP[k]).map(([t,k])=>`${t} → ${k}`)');
  assert.deepEqual([...orphanCards],[]);
  const incomplete=x.run('helpKeys.filter(k=>{const i=HELP[k];return !i.title||!i.summary||!(i.body&&i.body.length)||!i.ref})');
  assert.deepEqual([...incomplete],[],'每个说明必须有标题、摘要、正文与规范依据');
  assert.equal(x.run("help('not.a.key')"),'');
});

test('U14: hover summary and click dialog share one registry entry',()=>{
  const x=ui();
  const tip=x.run("help('exec.status')");
  assert.match(tip,/class="help" data-help="exec.status"/);
  assert.match(tip,/class="help-tip" role="tooltip"/);
  assert.match(tip,/aria-label="说明：执行状态含义/);
  assert.match(tip,/点击查看完整说明/);

  const button={dataset:{help:'exec.status'},attrs:{},setAttribute(name,value){this.attrs[name]=value;},focus(){this.focused=true;}};
  x.context.helpButton=button;
  assert.equal(x.run("openHelp('not.a.key', helpButton)"),false);
  assert.equal(x.elements['help-modal'].hidden,false);
  assert.equal(x.run("openHelp('exec.status', helpButton)"),true);
  assert.equal(x.elements['help-modal'].hidden,false);
  assert.equal(x.elements['help-modal-title'].textContent,'执行状态含义');
  assert.match(x.elements['help-modal-body'].innerHTML,/规范依据：EXECUTION\.md EXEC02/);
  assert.equal(button.attrs['aria-expanded'],'true');
  x.run('closeHelp()');
  assert.equal(x.elements['help-modal'].hidden,true);
  assert.equal(button.attrs['aria-expanded'],'false');
  assert.equal(button.focused,true);
});

test('U15: history folds long lists and keeps totals visible',()=>{
  const x=ui();
  assert.equal(x.run('foldRows([1,2,3,4,5],false,2).length'),2);
  assert.equal(x.run('foldRows([1,2,3],true,2).length'),3);
  assert.equal(x.run('foldRows([1,2,3],false,2)[0]'),1);
  assert.match(x.run("foldToggle('history',20,8,false)"),/展开全部（共 20 条）/);
  assert.match(x.run("foldToggle('history',20,20,true)"),/收起，只看最近 8 条/);
  assert.match(x.run("foldToggle('history',20,8,false)"),/当前显示 8 \/ 20 条/);
  assert.equal(x.run("foldToggle('history',5,5,false)"),'');
});

test('U15: the research centre renders sub-tabs with a scrolling, folded pane',async()=>{
  const attempt=(index)=>({attempt_id:`attempt-${String(index).padStart(4,'0')}-1111-2222-333333333333`,
    kind:'qlib.cn_synthetic_backtest',label:'Qlib 回测',probe:false,status:'succeeded',has_log:true,
    cancel_pending:false,exit_code:0,started_at:'2026-09-26T00:00:00Z',created_at:'2026-09-26T00:00:00Z',
    ended_at:'2026-09-26T00:01:00Z',outcome:{result_import:{status:'imported',run_id:'run-0001'}},
    error_code:null,error_message:null,config_fingerprint:'f'.repeat(64),workspace_label:'ws'});
  const attempts=Array.from({length:20},(_,index)=>attempt(index));
  const research=Array.from({length:25},(_,index)=>({id:`research-${index}`,title:`研究 ${index}`,
    session:'Loop_0',status:'result_available',factor_count:3,synthetic:true,facts:{},metrics:{}}));
  const x=ui(async path=>{
    if(path.startsWith('/v1/research?'))return response({items:research,total:25,next_offset:null});
    if(path.startsWith('/v1/agents/'))return response({chat:{},embedding:{},runtime:{},execution:{reasons:[]}});
    if(path==='/v1/executions/catalog')return response({items:[{kind:'stub.kind',executor_id:'stub',
      label:'桩入口',probe:false,data_nature:'test',description:'入口',available:true,checks:[],reasons:[]}]});
    if(path.startsWith('/v1/executions'))return response({items:attempts});
    return response({items:[]});
  });
  await x.run("state.view='agent';state.historyTab='attempts';state.historyExpanded=false;renderAgent()");
  let html=x.elements['content'].innerHTML;
  assert.match(html,/class="history-scroll"/);
  assert.match(html,/data-history-tab="attempts"/);
  assert.match(html,/data-history-tab="research"/);
  assert.equal((html.match(/<tr><td><code>/g)||[]).length,8,'默认只展开最近 8 条执行记录');
  assert.match(html,/展开全部（共 20 条）/);
  assert.match(html,/当前显示 8 \/ 20 条/);

  await x.run("state.historyExpanded=true;renderAgent()");
  html=x.elements['content'].innerHTML;
  assert.equal((html.match(/<tr><td><code>/g)||[]).length,20,'展开后显示全部执行记录');

  await x.run("state.historyTab='research';state.historyExpanded=false;renderAgent()");
  html=x.elements['content'].innerHTML;
  assert.equal((html.match(/data-research="/g)||[]).length,8,'研究记录同样默认折叠');
  assert.match(html,/展开全部（共 25 条）/);
  assert.match(html,/class="subtab active"[^>]*data-history-tab="research"|data-history-tab="research"[^>]*class="subtab active"|data-history-tab="research"/);
});

const catalogFixture={items:[
  {kind:'qlib.cn_synthetic_backtest',executor_id:'qlib_subprocess',label:'Qlib CN 合成行情训练+回测',probe:false,
   data_nature:'synthetic_current_rules_counterfactual',result_destination:'auto_import',description:'编译独立工作目录并用 Qlib 运行',available:true,checks:[],reasons:[]},
  {kind:'rdagent.factor.baseline',executor_id:'rdagent_subprocess',label:'RD-Agent 因子基线（集成探针）',probe:true,
   data_nature:'synthetic_scenario',result_destination:'manual_export_required',description:'本地因子基线回测',available:true,checks:[],reasons:[]},
  {kind:'rdagent.factor.loop',executor_id:'rdagent_subprocess',label:'RD-Agent 单轮因子循环（集成探针）',probe:true,
   data_nature:'synthetic_scenario',result_destination:'manual_export_required',description:'单轮因子演化循环',available:true,checks:[],reasons:[]},
]};

test('U16: every execution entry explains itself and the choice survives a re-render',()=>{
  const x=ui();
  const panel=x.run(`executionPanel(${JSON.stringify(catalogFixture)},{items:[]})`);
  catalogFixture.items.forEach(entry=>{
    assert.match(panel,new RegExp(`data-help="exec.kind.${entry.kind.replace(/\./g,'\\.')}"`),`${entry.kind} needs a help entry`);
  });
  assert.match(panel,/成功后自动入库/);
  assert.match(panel,/需可信离线导出后入库/);
  assert.match(panel,/训练 LightGBM/);
  assert.match(panel,/不发聊天请求/);
  assert.match(panel,/耗时几分钟/);

  x.context.catalog=catalogFixture;
  x.run("state.executionKind='rdagent.factor.loop'");
  const rerendered=x.run('executionPanel(catalog,{items:[]})');
  assert.match(rerendered,/value="rdagent\.factor\.loop" selected/,'选中的入口必须在重新渲染后保留');
  assert.match(rerendered,/value="qlib\.cn_synthetic_backtest"/);
  assert.ok(!/value="qlib\.cn_synthetic_backtest" selected/.test(rerendered));
  const feedback=x.run("entryFeedback('rdagent.factor.loop')");
  assert.match(feedback,/让 Agent 生成并回测新因子/);
});

test('U16: history controls stay outside the scrolling pane',async()=>{
  const attempts=[{attempt_id:'attempt-0001-1111-2222-333333333333',kind:'qlib.cn_synthetic_backtest',label:'回测',
    probe:false,status:'succeeded',has_log:true,cancel_pending:false,exit_code:0,started_at:'2026-09-26T00:00:00Z',
    created_at:'2026-09-26T00:00:00Z',ended_at:'2026-09-26T00:01:00Z',outcome:null,error_code:null,
    error_message:null,config_fingerprint:'f'.repeat(64),workspace_label:'ws'}];
  const research=Array.from({length:12},(_,i)=>({id:`research-${i}`,title:`研究 ${i}`,session:'Loop_0',
    status:'result_available',factor_count:1,synthetic:true,facts:{},metrics:{}}));
  const x=ui(async path=>{
    if(path.startsWith('/v1/research?'))return response({items:research,total:12,next_offset:null});
    if(path.startsWith('/v1/agents/'))return response({chat:{},embedding:{},runtime:{},execution:{reasons:[]}});
    if(path==='/v1/executions/catalog')return response(catalogFixture);
    if(path.startsWith('/v1/executions'))return response({items:attempts,next_cursor:null});
    return response({items:[]});
  });
  await x.run("state.view='agent';state.historyTab='research';state.historyExpanded=false;renderAgent()");
  const html=x.elements['content'].innerHTML;
  const toolbarAt=html.indexOf('id="research-search"');
  const scrollerAt=html.indexOf('class="history-scroll"');
  const pagerAt=html.indexOf('id="research-next"');
  assert.ok(toolbarAt>=0&&scrollerAt>=0,'搜索栏与滚动区都必须渲染');
  assert.ok(toolbarAt<scrollerAt,'搜索栏必须在滚动区之外，不能被一起滚动');
  assert.ok(pagerAt>scrollerAt,'翻页按钮固定在滚动区下方');
  assert.match(html,/id="execution-kind"/);
});

test('U17: the comparison table marks best/worst with colour and text',()=>{
  const x=ui();
  const table={run_ids:['a','b'],
    runs:[{run_id:'a',title:'运行 A',engine_id:'qlib',dataset_version:'content-v1',synthetic:true},
          {run_id:'b',title:'运行 B',engine_id:'qlib',dataset_version:'content-v1',synthetic:true}],
    rows:[
      {metric_id:'platform.equity',label:'期末权益',unit:'CNY',direction:'higher_better',
       direction_label:'越高越好',ranking_allowed:true,reasons:[],
       cells:[{run_id:'a',value:1100000,availability:'available',unit:'CNY',reason:null,mark:'best',tied:false},
              {run_id:'b',value:900000,availability:'available',unit:'CNY',reason:null,mark:'worst',tied:false}]},
      {metric_id:'native.qlib.turnover',label:'换手率（末值）',unit:'ratio',direction:'unknown',
       direction_label:'方向未登记',ranking_allowed:false,reasons:['direction_not_registered'],
       cells:[{run_id:'a',value:0.4,availability:'available',unit:'ratio',reason:null,mark:null,tied:false},
              {run_id:'b',value:null,availability:'empty',unit:'ratio',reason:'no_valid_point',mark:null,tied:false}]},
    ]};
  x.context.compareTable=table;
  const html=x.run('compareTableHtml(compareTable)');
  assert.match(html,/class="cell-best"/);
  assert.match(html,/class="cell-worst"/);
  assert.match(html,/rank-mark rank-best">最优/);
  assert.match(html,/rank-mark rank-worst">最劣/);
  assert.match(html,/本行不做优劣判断：该指标方向未登记/);
  assert.match(html,/红=最优、绿=最劣/);
  assert.match(html,/1,100,000/);
  assert.equal((html.match(/cell-best/g)||[]).length,1,'只有已允许的行才着色');
  assert.equal((html.match(/cell-worst/g)||[]).length,1);
  assert.match(html,/方向未登记/);
  assert.match(html,/暂无观测|未知/);
});

test('U16b: strict DOM mode fails on missing-element bindings',async()=>{
  const attempts=[{attempt_id:'attempt-0001-1111-2222-333333333333',kind:'qlib.cn_synthetic_backtest',label:'回测',
    probe:false,status:'succeeded',has_log:true,cancel_pending:false,exit_code:0,started_at:'2026-09-26T00:00:00Z',
    created_at:'2026-09-26T00:00:00Z',ended_at:'2026-09-26T00:01:00Z',outcome:null,error_code:null,
    error_message:null,config_fingerprint:'f'.repeat(64),workspace_label:'ws'}];
  const research=Array.from({length:3},(_,i)=>({id:`research-${i}`,title:`研究 ${i}`,session:'Loop_0',
    status:'result_available',factor_count:1,synthetic:true,facts:{},metrics:{}}));
  const x=ui(async path=>{
    if(path.startsWith('/v1/research?'))return response({items:research,total:3,next_offset:null});
    if(path.startsWith('/v1/agents/'))return response({chat:{},embedding:{},runtime:{},execution:{reasons:[]}});
    if(path==='/v1/executions/catalog')return response({items:[]});
    if(path.startsWith('/v1/executions'))return response({items:attempts,next_cursor:null});
    return response({items:[]});
  },{strict:true});
  // attempts tab: the research toolbar is not rendered, so binding it would throw in strict mode
  await x.run("state.view='agent';state.historyTab='attempts';renderAgent()");
  const attemptsHtml=x.elements['content'].innerHTML;
  assert.match(attemptsHtml,/class="history-scroll"/);
  assert.ok(!/id="research-search"/.test(attemptsHtml),'执行tab不渲染研究工具栏');
  // research tab: the toolbar is rendered and must be resolvable
  await x.run("state.historyTab='research';renderAgent()");
  const researchHtml=x.elements['content'].innerHTML;
  assert.match(researchHtml,/id="research-search"/);
  assert.equal(typeof x.elements['research-search'].onsubmit,'function');
});

test('U18/U19: compare rows carry groups and the factor view renders statistics',async()=>{
  const x=ui(async path=>{
    if(path.startsWith('/v1/factor-analysis')){assert.match(path,/analysis_version=2/);return response({schema_version:2,basis:{sample:{start:'2019-10-08',end:'2022-01-10',dates:552,instruments:16},
      factor_count:2,horizons:[1,5,10]},factors:[
      {factor_id:'f1',name:'mom_5d',coverage:0.98,rank_ic:{ic_mean:0.01,t_stat:1.2,p_value:0.2,icir:0.05,days:540},
       ic:{ic_mean:0.011},quantile_spread:{top_minus_bottom:0.0004,monotonic:false},turnover:{turnover:0.25},fdr_q:0.4},
      {factor_id:'f2',name:'vol_10d',coverage:0.97,rank_ic:{ic_mean:-0.015,t_stat:-1.3,p_value:0.18,icir:-0.06,days:541},
       ic:{ic_mean:-0.016},quantile_spread:{top_minus_bottom:-0.0009,monotonic:true},turnover:{turnover:0.15},fdr_q:0.45}],
      overlap:{value_correlation:{labels:['mom_5d','vol_10d'],matrix:[[1,0.1],[0.1,1]]},
        redundancy:{pairs:[{left:'mom_5d',right:'vol_10d',correlation:0.1,redundancy:0.9}]},
        collinearity:{available:true,max_vif:1.2,high_collinearity:false,perfect_collinearity:false},
        incremental_ic:[{factor:'mom_5d',without_ic:0.004,delta:0.002},{factor:'vol_10d',without_ic:0.006,delta:-0.001}],
        combined_ic:{days:540,ic_mean:0.006},
        ic_series_correlation:{labels:['mom_5d','vol_10d'],matrix:[[1,0.2],[0.2,1]]},
        not_available:[{metric:'holding_overlap',reason:'缺少持仓/成交明细'},{metric:'crowding',reason:'缺少市场层面数据'}]},
      limitations:['因子面板来自已导入的记录']});}
    if(path==='/v1/factors')return response({items:[
      {factor_id:'f1',name:'mom_5d',source_instance_id:'rdagent-local',panel_count:1,dataset:{id:'cn-current-synthetic',version:'eb27e8cc5b04a9761381af168958ff5d6291db7bc5f58e34ca72b08058ecd9ca'},
       definition:{formulation:'Close_t/Close_{t-5}-1'},provenance:{experiment_key:'Loop_0:runner'}},
      {factor_id:'f2',name:'vol_10d',source_instance_id:'rdagent-local',panel_count:1,dataset:{id:'cn-current-synthetic',version:'eb27e8cc5b04a9761381af168958ff5d6291db7bc5f58e34ca72b08058ecd9ca'},
       definition:{},provenance:{experiment_key:'Loop_0:runner'}}]});
    return response({items:[]});
  });
  await x.run("state.view='factors';renderFactors()");
  const html=x.elements['content'].innerHTML;
  assert.match(html,/单因子统计/);
  assert.match(html,/探索性分析/);
  assert.match(html,/Rank IC/);
  assert.match(html,/FDR q/);
  assert.match(html,/重叠性：相关、相似度与距离/);
  assert.match(html,/持仓重叠|holding_overlap/);
  assert.match(html,/拥挤|holding|not_available/);
  assert.match(html,/增量贡献/);
  assert.match(html,/data-factor-group=/);

  // group labels and the "side by side only" reason on the compare table
  const table={run_ids:['a'],runs:[{run_id:'a',title:'运行 A',engine_id:'qlib',dataset_version:'v',synthetic:true}],
    rows:[{metric_id:'native.qlib.mlflow.l2.train',label:'训练 L2',unit:'ratio',direction:'unknown',
      direction_label:'方向未登记',group:'training',group_label:'训练',ranking_allowed:false,
      reasons:['group_only_side_by_side:training'],cells:[{run_id:'a',value:0.5,availability:'available',unit:'ratio',mark:null,tied:false}],experiment_variables:[]}]};
  x.context.compareTable=table;
  const tableHtml=x.run('compareTableHtml(compareTable)');
  assert.match(tableHtml,/group-tag">训练组/);
  assert.match(tableHtml,/训练组只并排，不做排名/);
  assert.equal((tableHtml.match(/cell-best|cell-worst/g)||[]).length,0,'非回测组不得着色');
});

test('U20/U21: attention chip, command palette and the validation card',async()=>{
  const attention={total:2,counts:{high:1,medium:1,low:0},scope:'来自已记录状态',
    items:[{kind:'execution_failed',severity:'high',title:'执行失败：Qlib CN 合成行情训练+回测',detail:'nonzero_exit: exit 1',target:{view:'agent',history:'attempts'},ref:'abc12345'},
           {kind:'result_not_imported',severity:'medium',title:'结果未入库：基线回测',detail:'manual_import_required',target:{view:'agent',history:'attempts'},ref:'def67890'}]};
  const runs={items:[{run_id:'run-1',display_title:'Qlib CN 回测 · 2026-09-26',run:{title:'mlflow_recorder',engine:{id:'qlib'},status:'succeeded',dataset:{version:'v1'}}}]};
  const research={items:[{id:'r1',title:'因子研究 · mom_5d',status:'result_available',factor_count:3}],total:1,next_offset:null};
  const factors={items:[{factor_id:'f1',name:'mom_5d',panel_count:1,source_instance_id:'rdagent-local'}]};
  const validation={basis:{parameters:{horizon:1,blocks:4},sample:{observations:120},configs:[]},
    configs:[{run_id:'a',title:'运行 A',observations:120,sharpe:0.4,psr:{psr:0.7},dsr:{dsr:0.55},return_source:'derived: platform.equity 日收益（平台计算）'},
             {run_id:'b',title:'运行 B',observations:120,sharpe:0.1,psr:{psr:0.4},dsr:{dsr:0.3},return_source:'native.qlib.return（引擎报告日收益）'}],
    pbo:{pbo:0.42,blocks:4,splits:6,configurations:2,observations:120},
    leakage:{purged_folds:{folds:[{purged_ratio:0.2},{purged_ratio:0.4}]},uniqueness:{effective_samples:80,samples:119}},
    not_available:[{metric:'live_out_of_sample',reason:'尚无前瞻/实盘样本'}],limitations:['x']};
  const x=ui(async path=>{
    if(path.startsWith('/v1/attention'))return response(attention);
    if(path.startsWith('/v1/runs'))return response(runs);
    if(path.startsWith('/v1/research'))return response(research);
    if(path==='/v1/factors')return response(factors);
    if(path.startsWith('/v1/validation'))return response(validation);
    return response({items:[]});
  });
  // attention chip
  x.context.runs=runs;
  x.run('state.runs=runs.items');
  await x.run('refreshAttention()');
  assert.equal(x.elements['attention-chip'].hidden,false);
  assert.match(x.elements['attention-chip'].textContent,/待处理 2/);

  // command palette index and filtering
  await x.run('openPalette()');
  const kinds=x.run('[...new Set(state.paletteIndex.map(entry=>entry.kind))]');
  assert.deepEqual([...kinds],['命令','运行','研究','因子']);
  assert.match(x.run("(state.paletteIndex.find(entry=>entry.kind==='运行')||{}).label"),/Qlib CN 回测/);
  x.run("renderPaletteResults('因子研究')");
  assert.equal(x.run('state.paletteResults.length'),1);
  assert.equal(x.run('state.paletteResults[0].kind'),'研究');
  x.run("state.paletteSelection=0;runPaletteEntry(0)");
  assert.equal(x.run('state.researchId'),'r1');
  assert.equal(x.elements['command-modal'].hidden,true);

  // validation card
  const card=x.run("renderValidationCard(['a','b'])");
  return card.then(html=>{
    assert.match(html,/PSR/);
    assert.match(html,/DSR/);
    assert.match(html,/PBO（过拟合概率）/);
    assert.match(html,/有效样本数/);
    assert.match(html,/尚未前瞻|尚无前瞻/);
    assert.match(html,/工作台计算；不能替代前瞻验证/);
  });
});

test('T01-R: legacy risk presentation discloses its definition limit',async()=>{
  const x=ui(async()=>response({items:[{metrics:{sortino:1},basis:{sample:{},parameters:{}},calendar:{}}]}));
  const html=await x.run("renderRiskCard('r')");
  assert.match(html,/旧定义，未满足当前纠正合同/);
});

test('T01-U: risk requests v2, shows corrected zero, assumptions and exact inputs',async()=>{
 const x=ui(async path=>{
  assert.match(path,/analysis_version=2/);
  return response({items:[{schema_version:2,revision_id:'immutable-revision',metrics:{sortino_target_downside:0,sortino:99},
   provenance:{data_nature:'handwritten_fixture'},return_source:'recorded',basis:{sample:{observations:20},parameters:{risk_free_rate:{value:0,source:'default'},target_return:{value:0.01,source:'caller'},periods_per_year:238}},
   definitions:{drawdown_episodes:{availability:'available'},sharpe:{input_basis:{cost_basis:'before_cost'}}},calendar:{},limitations:['限制样例']}]});
 });
 const html=await x.run("renderRiskCard('r')");
 assert.match(html,/Sortino（目标下行偏差）<\/small><strong>0/);
 assert.doesNotMatch(html,/>99/);
 assert.match(html,/immutable-revision/);assert.match(html,/默认假设/);assert.match(html,/本次指定/);
 assert.match(html,/手写演示样本/);assert.match(html,/成本前/);assert.match(html,/限制样例/);
});

test('T01-U: unavailable risk does not imply zero or no drawdown',async()=>{
 const x=ui(async()=>response({items:[{schema_version:2,metrics:{},basis:{sample:{observations:null},parameters:{}},
  definitions:{drawdown_episodes:{availability:'unavailable',reason:'missing_or_nonfinite_observation'}},
  not_available:[{metric:'sharpe',reason:'missing_or_nonfinite_observation'}],calendar:{}}]}));
 const html=await x.run("renderRiskCard('r')");
 assert.match(html,/存在缺测或非有限观测/);assert.match(html,/来源性质未知/);
 assert.doesNotMatch(html,/样本内没有观测回撤/);assert.doesNotMatch(html,/0 个观测/);
});

test('T01-U: factor significance and pair values follow server definitions',()=>{
 const x=ui();
 const row=x.run(`factorStatsRow({name:'<unsafe>',rank_ic:{ic_mean:0,significance_available:false,significance_reason:'missing_trading_day_ic',t_stat:99,p_value:0},fdr_q:0})`);
 assert.match(row,/&lt;unsafe&gt;/);assert.match(row,/检验窗口内有交易日缺少有效 IC/);
 assert.doesNotMatch(row,/>99/);assert.match(row,/来源性质未知/);
 const pair=x.run(`factorCorrelationTable({labels:['a','b'],matrix:[[1,0],[0,1]]},{pairs:[{left:'a',right:'b',correlation:0,value:0,valid_days:20}]},{pairs:[{left:'a',right:'b',value:1}]})`);
 assert.match(pair,/相似度 0/);assert.match(pair,/距离 1/);assert.match(pair,/有效 20 天/);
 assert.doesNotMatch(pair,/冗余度/);
});


test('T01-U: selected historical revision never displays latest risk values',async()=>{
 const x=ui(async()=>response({items:[{schema_version:2,revision_id:'latest',metrics:{sharpe:99}}]}));
 const html=await x.run("renderRiskCard('r','historical')");
 assert.match(html,/版本与页面选择不一致/);assert.match(html,/historical/);assert.match(html,/latest/);
 assert.doesNotMatch(html,/>99/);
});
