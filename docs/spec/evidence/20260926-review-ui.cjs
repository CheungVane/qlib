const fs=require('fs'),vm=require('vm');
const source=fs.readFileSync('extensions/workbench/quant_workbench/ui/app.js','utf8').replace(/init\(\);\s*$/,'');
const context={URLSearchParams, URL, location:{search:'',hash:'',href:'http://localhost/'},Intl, fetch:async()=>({ok:false,status:500,json:async()=>({message:'isolated failure'})})};
vm.createContext(context);vm.runInContext(source,context);
(async()=>{
 const out={};out.series_error_swallowed=(await vm.runInContext("series('r','m','v')",context))===null;
 let calls=0;context.fetch=async()=>{calls++;return {ok:true,json:async()=>({series:{points:[{x:1999,value:2000}]},total_points:2001,next_offset:2000})}};
 const result=await vm.runInContext("series('r','m','v')",context);out.pagination={requests:calls,next_offset:result.next_offset,shown_ending_equity:result.series.points.at(-1).value};
 const html=vm.runInContext("chart([{x:0,value:1},{x:1,value:null,reason:'gap'},{x:2,value:3}])",context);
 out.gap_chart={polylines:(html.match(/<polyline/g)||[]).length,claims_two_points:html.includes('共2个数据点'),connects_across_gap:html.includes('48.00,235.00 780.00,50.00')};
 console.log(JSON.stringify(out,null,2));
})();
