'use strict';
let token = '', run = null, streamAbort = null, cursor = 0;
const $ = (id) => document.getElementById(id);
const showError = (e) => { $('error').textContent = e.message || String(e); };
async function api(path, body, extraHeaders = {}) {
  const response = await fetch(path, {method: body === undefined ? 'GET' : 'POST', headers: {'Authorization': `Bearer ${token}`, ...(body === undefined ? {} : {'Content-Type': 'application/json'}), ...extraHeaders}, body: body === undefined ? undefined : JSON.stringify(body)});
  const data = await response.json();
  if (!response.ok) throw new Error(typeof data.detail === 'string' ? data.detail : JSON.stringify(data.detail));
  return data;
}
function button(label, fn) { const b=document.createElement('button'); b.textContent=label; b.onclick=async()=>{b.disabled=true; try{await fn(); $('error').textContent='';}catch(e){showError(e);}finally{b.disabled=false;}}; $('actions').appendChild(b); }
async function update(value) {
  run=value; $('runId').value=run.id; $('status').textContent=run.status; $('actions').replaceChildren();
  const guidance={AWAITING_INPUT:'Fill in the asset and time window, then answer the clarification.',READY_TO_DRAFT:'The request is complete. Retrieve evidence and generate a draft.',AWAITING_APPROVAL:'Nothing has been submitted. An independent approver must review the exact proposal.',APPROVED:'Approval is recorded. Submission rechecks current permissions and evidence.',SUCCEEDED:'The destination confirmed this incident.',OUTCOME_UNKNOWN:'The outcome is uncertain. Reconcile before any retry.',EXECUTING:'Execution may already have committed. Reconcile; do not resubmit.',REJECTED:'The proposal was rejected. No incident was created.',CANCELLED:'The pending workflow was cancelled.',INSUFFICIENT_EVIDENCE:'No approved procedure was available. The system did not invent one.'};
  $('guidance').textContent=guidance[run.status]||run.status;
  $('summary').textContent=run.proposal?.body.draft.summary||'No draft yet.';
  $('evidence').textContent=run.proposal?JSON.stringify({sources:run.proposal.body.draft.evidence_refs,limitations:run.proposal.body.draft.limitations,records:run.proposal.body.evidence},null,2):'No evidence yet.';
  $('proposal').textContent=JSON.stringify(run.proposal,null,2);
  $('result').textContent=run.result?`Confirmed incident: ${run.result.incident_id}`:'No confirmed incident.';
  const action=async(suffix,body={})=>update(await api(`/api/runs/${run.id}/${suffix}`,body));
  if(run.status==='AWAITING_INPUT')button('Submit clarification',()=>action('clarify',{asset_id:$('asset').value,hours:Number($('hours').value),expected_version:run.version}));
  if(run.status==='READY_TO_DRAFT')button('Retrieve and draft',()=>action('prepare'));
  if(run.status==='AWAITING_APPROVAL')for(const decision of ['approve','reject'])button(decision==='approve'?'Approve exact proposal':'Reject proposal',()=>action('decision',{proposal_hash:run.proposal.hash,expected_version:run.version,decision}));
  if(run.status==='APPROVED')button('Submit approved incident',()=>action('execute'));
  if(['EXECUTING','OUTCOME_UNKNOWN'].includes(run.status))button('Reconcile destination',()=>action('reconcile'));
  if(['AWAITING_INPUT','READY_TO_DRAFT','AWAITING_APPROVAL','APPROVED'].includes(run.status))button('Cancel pending work',()=>action('cancel',{expected_version:run.version}));
  button('Refresh status',()=>api(`/api/runs/${run.id}`).then(update));
}
async function startStream(id) {
  streamAbort?.abort(); streamAbort=new AbortController(); const controller=streamAbort;
  cursor=0; $('activity').replaceChildren();
  while(!controller.signal.aborted && run?.id===id){
    try{
      const response=await fetch(`/api/runs/${id}/stream?after=${cursor}`,{headers:{Authorization:`Bearer ${token}`},signal:controller.signal});
      if(!response.ok)throw new Error(`Activity connection failed (${response.status}).`);
      const reader=response.body.getReader(); const decoder=new TextDecoder(); let buffer='';
      while(true){ const {value,done}=await reader.read(); if(done)break; buffer+=decoder.decode(value,{stream:true}); let index;
        while((index=buffer.indexOf('\n\n'))>=0){ const frame=buffer.slice(0,index); buffer=buffer.slice(index+2); if(frame.includes('event: access.revoked')){controller.abort(); throw new Error('Access to this activity stream ended.');} const line=frame.split('\n').find(x=>x.startsWith('data: ')); if(!line)continue;
          const item=JSON.parse(line.slice(6)); if(item.id<=cursor)continue; cursor=item.id;
          const li=document.createElement('li'); li.textContent=`${item.kind} · ${new Date(item.created_at*1000).toLocaleTimeString()} · ${JSON.stringify(item.payload)}`; $('activity').appendChild(li);
        }
      }
    }catch(e){if(controller.signal.aborted)break;showError(e);}
    if(!controller.signal.aborted)await new Promise(resolve=>setTimeout(resolve,1200));
  }
}
$('connect').onsubmit=async(e)=>{
  e.preventDefault();streamAbort?.abort();const previousRunId=run?.id;run=null;cursor=0;
  for(const id of ['identity','status','guidance','summary','evidence','proposal','result','error'])$(id).textContent='';
  $('actions').replaceChildren();$('activity').replaceChildren();$('runId').value='';
  token=$('token').value.trim();$('token').value='';
  try{const me=await api('/api/me');$('identity').textContent=`${me.id} · ${me.team} · ${me.role} · ${me.model_mode}`;
    if(previousRunId){await update(await api(`/api/runs/${previousRunId}`));void startStream(run.id);}
  }catch(err){showError(err);}
};
$('request').onsubmit=async(e)=>{e.preventDefault();try{const value=await api('/api/runs',{message:$('message').value,asset_id:$('asset').value||null,hours:$('hours').value?Number($('hours').value):null},{'Idempotency-Key':crypto.randomUUID()});await update(value);void startStream(run.id);$('error').textContent='';}catch(err){showError(err);}};
$('load').onclick=async()=>{try{await update(await api(`/api/runs/${$('runId').value.trim()}`));void startStream(run.id);}catch(e){showError(e);}};
window.addEventListener('beforeunload',()=>streamAbort?.abort());
