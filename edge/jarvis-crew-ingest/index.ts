/** One-shot Jarvis V2 Crew chat. Exact signed GitHub identity; <= 10 events/run.
 *  Stores only short, redacted, idempotent role messages; full transcripts
 *  remain temporary GitHub artifact. No general-purpose ingestion or writes.
 */
import { createClient } from "npm:@supabase/supabase-js@2.49.8";
import { createRemoteJWKSet, jwtVerify } from "npm:jose@6.1.0";
const ISSUER="https://token.actions.githubusercontent.com";
const JWKS=createRemoteJWKSet(new URL(ISSUER+"/.well-known/jwks"));
const WF_NAME="Jarvis V2 CrewAI review — requires expense approval";
const WF_REF="MatteoCurro/paper-kestrel/.github/workflows/jarvis-v2-crew-review.yml@refs/heads/infra/transactional-v2";
const ROLES=new Set(["Senior Product Engineer","UX Critic","Independent Security and Release Reviewer","Controller"]);
const TYPES=new Set(["agent_message","agent_handoff","run_started","run_completed","run_failed"]);
const phases=new Set(["setup","planning","qa","done"]);
const resp=(data:unknown,status=200)=>Response.json(data,{status,headers:{"cache-control":"no-store"}});
function admin(){
  const secrets=JSON.parse(Deno.env.get("SUPABASE_SECRET_KEYS")||"{}");
  const key=secrets.default||Deno.env.get("SUPABASE_SERVICE_ROLE_KEY");
  const url=Deno.env.get("SUPABASE_URL");
  if(!url||!key)throw new Error("Admin environment unavailable");
  return createClient(url,key,{auth:{persistSession:false,autoRefreshToken:false}});
}
Deno.serve(async req=>{
  if(req.method!=="POST")return resp({error:"method not allowed"},405);
  const bearer=req.headers.get("authorization")||"";
  if(!bearer.startsWith("Bearer "))return resp({error:"OIDC required"},401);
  try{
    const {payload}=await jwtVerify(bearer.slice(7),JWKS,
      {issuer:ISSUER,audience:"jarvis-supabase"});
    if(payload.repository!=="MatteoCurro/paper-kestrel"||
       String(payload.repository_id)!=="1409141984"||
       payload.workflow!==WF_NAME||payload.workflow_ref!==WF_REF||
       payload.ref!=="refs/heads/infra/transactional-v2"||
       payload.event_name!=="push")return resp({error:"invalid GitHub workflow"},403);
    const runId=Number(payload.run_id),attempt=Number(payload.run_attempt);
    if(!Number.isSafeInteger(runId)||runId<=0||
       !Number.isSafeInteger(attempt)||attempt<=0)return resp({error:"invalid run ID"},403);
    const raw=await req.text();
    if(raw.length>3200)return resp({error:"payload too large"},413);
    let body:Record<string,unknown>;
    try{body=JSON.parse(raw)}catch{return resp({error:"invalid JSON"},400)}
    const eventKey=String(body.event_key||"");
    const message=String(body.message||"");
    const agent=String(body.agent||"");
    const type=String(body.event_type||"").replaceAll(".","_");
    const phase=String(body.phase||"planning");
    const status=String(body.status||"in_progress");
    const match=/^v2chat:(0[0-9])$/.exec(eventKey);
    if(!match||Number(match[1])>9||message.length===0||message.length>520||
       !ROLES.has(agent)||!TYPES.has(type)||!phases.has(phase)||
       !["in_progress","success","failure"].includes(status))
       return resp({error:"out-of-scope review event"},400);
    if(type==="run_completed"&&status!=="success"||
       type==="run_failed"&&status!=="failure")return resp({error:"status mismatch"},400);
    const target=body.handoff_to==null?null:String(body.handoff_to);
    if(target&&!ROLES.has(target))return resp({error:"unrecognized destination"},400);
    // Fail closed against accidental sensitive content in the compact feed.
    if(/sb_secret_|sk-proj-|ghp_|-----BEGIN|(?:api[_-]?key|password|bearer)\\s*[=:]/i.test(message)||
       /[A-Z0-9._%+-]+@[A-Z0-9.-]+\\.[A-Z]{2,}/i.test(message))
       return resp({error:"private data in summary"},400);
    const db=admin();
    const {data:id,error:runError}=await db.rpc("jarvis_ingest_run",{
      p_patch:{
        github_run_id:runId,run_attempt:attempt,status,phase,
        spec_path:"orders/jarvis-control-room-v2.md",
        summary:"Jarvis V2 — verifica multi-agente in TSAND",
        active_agents:status==="in_progress"?[agent]:[],
      },
    });
    if(runError||typeof id!=="string")return resp({error:"run transition rejected"},409);
    const key=`${runId}:${attempt}:${eventKey}`;
    const {error:insertError}=await db.from("agent_events").upsert({
      run_id:id,event_key:key,occurred_at:new Date().toISOString(),
      agent,event_type:type,status:status,message,
      handoff_to:target,
      metadata:{kind:type==="agent_message"||type==="agent_handoff"?"agent_chat":"run_lifecycle",truncated:true,source:"github_actions"},
    },{onConflict:"event_key",ignoreDuplicates:true});
    if(insertError)return resp({error:"event rejected"},409);
    return resp({ok:true,run_id:id,accepted_event_key:key});
  }catch(error){
    console.error("Jarvis crew ingest failed:",error instanceof Error?error.name:"unknown");
    return resp({error:"unauthorized or unavailable"},401);
  }
});
