const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const {test}=require('node:test');
const source=fs.readFileSync(require('node:path').join(__dirname,'../quant_workbench/ui/app.js'),'utf8').replace(/init\(\);\s*$/,'');
function ui(fetch){
  const elements={};
  const document={getElementById:id=>elements[id]??=( {innerHTML:'',textContent:''}),querySelectorAll:()=>[]};
  const context={URLSearchParams,URL,location:{search:'',hash:'',href:'http://localhost/'},Intl,fetch,document,crypto:require('node:crypto').webcrypto};
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
  assert.equal(x.elements['help-modal'].hidden,undefined);
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
