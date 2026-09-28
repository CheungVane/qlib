// Transport owns HTTP reads and stale-render detection; mutations retain explicit handling.
export function createTransport(fetchImpl, getGeneration) {
 const request = (path, options) => fetchImpl(path, options);
 async function api(path) {
  const generation=getGeneration();
  const response=await request(path,{headers:{'Accept':'application/json'}});
  const body=await response.json().catch(error=>{if(response.ok)throw error;return {};});
  if(generation!==getGeneration()){const error=new Error('页面已切换');error.name='StaleRender';throw error;}
  if(!response.ok){
    const error=new Error(`${body.message||'请求失败 '+response.status}${body.request_id?' · request_id: '+body.request_id:''}`);
    error.status=response.status;error.code=body.code;throw error;
  }
  return body;
}
 return {api, request};
}
