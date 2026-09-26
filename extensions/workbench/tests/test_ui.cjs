const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const {test}=require('node:test');
const source=fs.readFileSync(require('node:path').join(__dirname,'../quant_workbench/ui/app.js'),'utf8').replace(/init\(\);\s*$/,'');
function ui(fetch){
  const elements={};
  const document={getElementById:id=>elements[id]??=( {innerHTML:'',textContent:''}),querySelectorAll:()=>[]};
  const context={URLSearchParams,URL,location:{search:'',hash:'',href:'http://localhost/'},Intl,fetch,document};
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
