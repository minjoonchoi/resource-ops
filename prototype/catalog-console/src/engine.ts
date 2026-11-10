import { parseDocument } from 'yaml';
import { rawDigest, demoId } from './portable-crypto.ts';

export type Kind = 'page' | 'task' | 'capability' | 'service';
export type Status = 'synced' | 'changed' | 'new' | 'deleted' | 'restore' | 'drift' | 'failed' | 'invalid';
export type Snapshot = { id: string; raw: string | null; hash: string | null; gitSha: string; collectedAt: string };
export type Collection = { id: string; at: string; gitSha: string; snapshotId: string; result: 'changed' | 'unchanged' | 'deleted' };
export type Revision = { number: number; snapshot: Snapshot; at: string; operation: 'register' | 'update' | 'delete' | 'restore' };
export type Resource = { id: string; path: string; kind: Kind; name: string; key: string; title: string; snapshots: Snapshot[]; source: Snapshot; collections: Collection[]; revisions: Revision[]; active: number | null; drift: boolean; failure: string | null; failNext: boolean };
export type Run = { id: string; at: string; type: string; status: 'success' | 'partial' | 'failed' | 'info'; message: string; details: {id:string; result:string}[]; gitSha: string };
export type ScenarioResult = {at: string; passed: boolean; detail: string};
export type State = { version: 1; resources: Resource[]; runs: Run[]; gitSha: string; lastCollected: string; checks: Record<string, boolean>; scenarios: Record<string,ScenarioResult> };
export type Validation = { valid: boolean; errors: string[]; key: string; name: string; kind: Kind | null; title: string; checks: {label:string; valid:boolean; detail:string}[] };
export const statusMeta: Record<Status,{label:string;tone:string}> = {
  synced:{label:'동기화 완료',tone:'green'}, changed:{label:'변경 대기',tone:'blue'}, new:{label:'등록 대기',tone:'violet'}, deleted:{label:'삭제 대기',tone:'red'}, restore:{label:'복원 대기',tone:'teal'}, drift:{label:'드리프트',tone:'orange'}, failed:{label:'동기화 실패',tone:'red'}, invalid:{label:'검증 오류',tone:'red'}
};
export const kindLabel: Record<Kind,string> = {page:'Page',task:'Task',capability:'Capability',service:'Service'};
export const operationLabel = {register:'리소스 등록',update:'원문 변경',delete:'리소스 삭제',restore:'리소스 복원'};
export const clone = (s:State):State => structuredClone(s);
export const current = (r:Resource) => r.revisions.find(v=>v.number===r.active);
export const newest = (r:Resource) => r.revisions.at(-1);
export const stamp = () => new Date().toISOString();
export const digest = rawDigest;
const uid=demoId;
export function globalKey(path:string,name:string,kind:Kind) {const org=path.split('/')[1]??'';return kind==='service'?(name.startsWith(org+'-')?name:org+'-'+name):name;}

export function validate(path:string,raw:string|null,resources:Resource[]=[],excludeId?:string):Validation {
 const errors:string[]=[]; const checks:Validation['checks']=[];let name='',title='',kind:Kind|null=null,key='';
 if(raw===null)return {valid:true,errors,key,name,kind,title,checks:[{label:'삭제 원문',valid:true,detail:'완전한 수집에서 파일 부재를 확인한 상태'}]};
 let obj:any;
 try {const doc=parseDocument(raw,{uniqueKeys:true});if(doc.errors.length)throw Error(doc.errors[0].message);obj=doc.toJS({maxAliasCount:0});if(!obj||typeof obj!=='object'||Array.isArray(obj))throw Error('YAML 객체가 필요합니다.');checks.push({label:'YAML 문법',valid:true,detail:'단일 문서 · 중복 키 없음'});}catch(e){return {valid:false,errors:['YAML: '+(e instanceof Error?e.message:'파싱 실패')],key,name,kind,title,checks:[{label:'YAML 문법',valid:false,detail:'구문 오류 또는 허용하지 않는 별칭'}]};}
 const k=String(obj.kind??'').toLowerCase(); if(['page','task','capability','service'].includes(k))kind=k as Kind;
 name=typeof obj.metadata?.name==='string'?obj.metadata.name:'';title=typeof obj.metadata?.title==='string'?obj.metadata.title:name;
 const code='[a-z][a-z0-9_-]*';
 const pm=path.match(new RegExp('^platform/('+code+')/('+code+')/('+code+')/(?:[^/]+/)*[^/]+\\.yaml$'));
 const sm=path.match(new RegExp('^service/('+code+')/(?:[^/]+/)*[^/]+\\.yaml$'));
 const safe=!path.split('/').some(x=>x==='.'||x==='..'||x==='');
 const pathOK=!!kind&&safe&&!!(kind==='service'?sm:pm);
 checks.push({label:'경로 · 유형',valid:pathOK,detail:pathOK?'경로와 리소스 유형 일치':'platform/<platform>/<workspace>/<domain>/**.yaml 또는 service/<organization>/**.yaml 필요'});
 if(!pathOK)errors.push('경로 또는 kind가 지원 규칙과 일치하지 않습니다.');
 let nameOK=false,expected='';
 if(kind==='service') {nameOK=/^[a-z0-9]+(?:-[a-z0-9]+)*-api$/.test(name);expected='서비스 이름: *-api';}
 else if(kind&&pm){const prefix=`${pm[1]}.${pm[2]}.${pm[3]}.${kind}-`;nameOK=name.startsWith(prefix)&&/^[a-z0-9][a-z0-9_-]*$/.test(name.slice(prefix.length));expected=prefix+'*';}
 checks.push({label:'이름 규칙',valid:nameOK,detail:expected||'metadata.name과 지원 kind가 필요합니다.'});if(!nameOK)errors.push('metadata.name 규칙 불일치: '+(expected||'이름과 유형 확인'));
 key=kind?globalKey(path,name,kind):name;
 if(kind==='service'){const org=sm?.[1]??'';const rest=key.slice(org.length+1);const ok=!!org&&key.startsWith(org+'-')&&/^[a-z0-9]+(?:-[a-z0-9]+)*-api$/.test(rest);checks.push({label:'서비스 전역 키',valid:ok,detail:org+'-*-api → '+key});if(!ok)errors.push('조직 접두어를 포함한 전역 키 규칙이 올바르지 않습니다.');}
 const collision=resources.find(r=>r.id!==excludeId&&r.key===key&&(r.source.raw!==null||current(r)?.snapshot.raw!==null));
 const unique=!!key&&!collision;checks.push({label:'전역 유니크',valid:unique,detail:collision?'중복 키: '+collision.path:'전체 유형에 걸친 중복 검사'});if(!unique)errors.push(collision?'전역 키 중복: '+collision.path:'전역 키가 없습니다.');
 return {valid:errors.length===0,errors,key,name,kind,title,checks};
}
export function resourceStatus(r:Resource,all:Resource[]):Status {
 if(!validate(r.path,r.source.raw,all,r.id).valid)return 'invalid';
 if(r.failure)return 'failed';if(r.drift)return 'drift';
 const a=current(r);if(!a)return r.source.raw===null?'synced':'new';
 if(r.source.hash===a.snapshot.hash&&r.source.raw===a.snapshot.raw)return 'synced';
 if(r.source.raw===null)return 'deleted';if(a.snapshot.raw===null)return 'restore';return 'changed';
}
function addRun(s:State,type:string,status:Run['status'],message:string,details:Run['details']=[]) {s.runs.unshift({id:uid(),at:stamp(),type,status,message,details,gitSha:s.gitSha});s.runs=s.runs.slice(0,100);}
export async function collect(s0:State,patches:Record<string,string|null>={},paths:Record<string,string>={},complete=true):Promise<State>{
 const s=clone(s0);if(!complete){addRun(s,'수집','failed','트리 탐색 실패 · 삭제 판정을 중단하고 마지막 정상 원문을 유지했습니다.');return s;}
 const at=stamp();const hasChange=Object.entries(patches).some(([id,raw])=>s.resources.find(r=>r.id===id)?.source.raw!==raw)||Object.entries(paths).some(([id,path])=>s.resources.find(r=>r.id===id)?.path!==path);
 const gitSha=hasChange?(await digest(s.gitSha+JSON.stringify(patches)+JSON.stringify(paths))).slice(0,40):s.gitSha;
 let changed=0;
 for(const r of s.resources){const raw=Object.hasOwn(patches,r.id)?patches[r.id]:r.source.raw;const path=paths[r.id]??r.path;
  if(raw!==r.source.raw||path!==r.path){changed++;r.path=path;const hash=raw===null?null:await digest(raw);const snapshot={id:uid(),raw,hash,gitSha,collectedAt:at};r.snapshots.push(snapshot);r.source=snapshot;const v=validate(r.path,raw);if(raw!==null){r.kind=v.kind??r.kind;r.key=v.key||r.key;r.name=v.name||r.name;r.title=v.title||r.title;}r.failure=null;}
  r.collections.unshift({id:uid(),at,gitSha,snapshotId:r.source.id,result:r.source.raw===null?'deleted':Object.hasOwn(patches,r.id)&&r.source.collectedAt===at?'changed':'unchanged'});r.collections=r.collections.slice(0,150);
 }
 s.gitSha=gitSha;s.lastCollected=at;addRun(s,'수집','success',`${s.resources.length}개 파일 확인 · 원문 변경 ${changed}개 · 새 리비전 0개`);return s;
}
export function sync(s0:State,ids?:string[]):State {
 const s=clone(s0);const targets=s.resources.filter(r=>!ids||ids.includes(r.id));let success=0,failed=0,skipped=0,created=0;const details:Run['details']=[];
 for(const r of targets){const v=validate(r.path,r.source.raw,s.resources,r.id);if(!v.valid){failed++;details.push({id:r.id,result:'검증 차단: '+v.errors.join(' / ')});continue;}
  if(r.failNext){r.failNext=false;r.failure='SIMULATED_TIMEOUT · 파일 반영 전에 실패했습니다. 기존 리비전을 유지합니다.';failed++;details.push({id:r.id,result:r.failure});continue;}
  const a=current(r);const same=a?.snapshot.raw===r.source.raw&&a?.snapshot.hash===r.source.hash;
  if((same&&!r.drift)||(!a&&r.source.raw===null)){skipped++;r.failure=null;details.push({id:r.id,result:'변경 없음 · 리비전 유지'});continue;}
  const n=newest(r);let result='';
  if(n&&n.snapshot.raw===r.source.raw&&n.snapshot.hash===r.source.hash){r.active=n.number;result=r.drift?'드리프트 복구 · 리비전 유지':'기존 리비전 재적용';}
  else {const op:Revision['operation']=!a?'register':r.source.raw===null?'delete':a.snapshot.raw===null?'restore':'update';const number=(n?.number??0)+1;r.revisions.push({number,snapshot:structuredClone(r.source),at:stamp(),operation:op});r.active=number;created++;result=operationLabel[op]+` · r${number} 생성`;}
  r.drift=false;r.failure=null;success++;details.push({id:r.id,result});
 }
 addRun(s,ids?'선택 동기화':'전체 동기화',failed?(success?'partial':'failed'):'success',`반영 ${success} · 실패/차단 ${failed} · 변경 없음 ${skipped} · 새 리비전 ${created}`,details);return s;
}
export function rollback(s0:State,id:string,number:number,reason:string):State {
 const s=clone(s0);const r=s.resources.find(r=>r.id===id);const rev=r?.revisions.find(v=>v.number===number);if(!r||!rev)throw Error('선택한 리비전을 찾을 수 없습니다.');if(!reason.trim())throw Error('롤백 사유를 입력해 주세요.');if(r.active===number)throw Error('이미 현재 적용 중인 리비전입니다.');
 const v=validate(r.path,rev.snapshot.raw,s.resources,r.id);if(!v.valid)throw Error('대상 리비전 검증 실패: '+v.errors.join(', '));
 r.active=number;r.drift=r.source.hash!==rev.snapshot.hash||r.source.raw!==rev.snapshot.raw;r.failure=null;addRun(s,'선택 롤백','success',`${r.title} → r${number} · ${reason}`,[{id,result:'기존 리비전 포인터 전환 · 원문과 Git 유지 · 새 리비전 없음'}]);return s;
}
const base='2026-11-10T09:24:08.000Z';
export function sampleYaml(kind:Kind,name:string,title:string,version=1) {return `# resource-ops console · 시뮬레이션 예시\n# spec의 실행 의미와 소비자 계약은 미확인\napi-version: resource-ops/preview\nkind: ${kindLabel[kind]}\nmetadata:\n  name: ${name}\n  title: ${title}\nspec:\n  description: ${title} 카탈로그 정의\n  example-version: ${version}\n`;}
export async function createSeed():Promise<State>{
 const defs:[string,Kind,string,string,string,number,Status][]=[
 ['members','page','platform/orion/backoffice/member/pages/members.yaml','orion.backoffice.member.page-members','회원 목록',3,'changed'],
 ['read','task','platform/orion/backoffice/member/tasks/read.yaml','orion.backoffice.member.task-read','회원 조회',2,'changed'],
 ['export','capability','platform/orion/backoffice/member/capabilities/export.yaml','orion.backoffice.member.capability-export','회원 내보내기',0,'new'],
 ['member-api','service','service/member-team/member-api.yaml','member-api','회원 API',4,'synced'],
 ['identity-api','service','service/identity-team/identity-api.yaml','identity-api','인증 API',2,'synced'],
 ['detail','page','platform/orion/backoffice/member/pages/detail.yaml','orion.backoffice.member.page-detail','회원 상세',2,'synced'],
 ['cap-read','capability','platform/orion/backoffice/member/capabilities/read.yaml','orion.backoffice.member.capability-read','회원 읽기 권한',3,'synced'],
 ['disable','task','platform/orion/backoffice/member/tasks/disable.yaml','orion.backoffice.member.task-disable','회원 비활성화',1,'failed'],
 ['audit','page','platform/orion/backoffice/audit/pages/history.yaml','orion.backoffice.audit.page-history','감사 이력',1,'synced'],
 ['legacy','task','platform/orion/backoffice/member/tasks/legacy-export.yaml','orion.backoffice.member.task-legacy-export','구형 내보내기',2,'deleted'],
 ['restore','capability','platform/orion/backoffice/audit/capabilities/read.yaml','orion.backoffice.audit.capability-read','감사 읽기 권한',3,'restore'],
 ['payment-api','service','service/payment-team/payment-api.yaml','payment-gateway','결제 API',0,'invalid']
 ];
 const gitSha=(await digest('DEMO resource-ops 2026-11-10 catalog')).slice(0,40);const resources:Resource[]=[];
 for(const [id,kind,path,name,title,count,status] of defs){const snapshots:Snapshot[]=[];const revisions:Revision[]=[];
  for(let i=1;i<=count;i++){const raw=status==='restore'&&i===count?null:sampleYaml(kind,name,title,i);const at=new Date(Date.parse(base)-(count-i+1)*86400000).toISOString();const snap={id:`${id}-s${i}`,raw,hash:raw===null?null:await digest(raw),gitSha:(await digest('DEMO commit '+at)).slice(0,40),collectedAt:at};snapshots.push(snap);revisions.push({number:i,snapshot:snap,at,operation:raw===null?'delete':i===1?'register':'update'});}
  const raw=status==='deleted'?null:sampleYaml(kind,name,title,status==='synced'?count:count+1);let source=snapshots.find(s=>s.raw===raw);if(!source){source={id:`${id}-head`,raw,hash:raw===null?null:await digest(raw),gitSha,collectedAt:base};snapshots.push(source);}
  resources.push({id,path,kind,name,key:globalKey(path,name,kind),title,snapshots,source,collections:[{id:`${id}-collection`,at:base,gitSha,snapshotId:source.id,result:status==='synced'?'unchanged':raw===null?'deleted':'changed'}],revisions,active:count||null,drift:false,failure:status==='failed'?'SIMULATED_TIMEOUT · 예시 실패 기록. 재시도할 수 있습니다.':null,failNext:false});
 }
 return {version:1,resources,gitSha,lastCollected:base,checks:{},scenarios:{},runs:[{id:'seed-collect',at:base,type:'초기 데모',status:'info',message:'12개 예시 파일 · 저장소를 변경하지 않는 로컬 시뮬레이션',details:[],gitSha}]};
}
export const scenarioDefinitions=[
 {id:'noop',title:'동일 원문 재수집',description:'수집 시각만 추가하고 원문 스냅샷과 리비전을 유지합니다.',icon:'repeat'},
 {id:'register',title:'최초 리소스 등록',description:'새 파일을 수집한 뒤 최초 동기화에서 r1을 만듭니다.',icon:'plus'},
 {id:'delete',title:'원문 삭제',description:'완전한 수집에서 부재를 확인한 파일을 삭제합니다.',icon:'trash'},
 {id:'restore',title:'삭제된 리소스 복원',description:'동일한 전역 키의 원문을 다시 수집하고 복원합니다.',icon:'restore'},
 {id:'drift',title:'드리프트 복구',description:'원문 변경 없이 적용 상태만 복구하고 리비전을 유지합니다.',icon:'drift'},
 {id:'retry',title:'실패 후 재시도',description:'실패 시 기존 리비전을 보존하고 다음 시도를 기록합니다.',icon:'retry'},
 {id:'partial',title:'부분 실패',description:'독립 파일 두 개 중 하나만 실패시킨 후 실패 건만 재시도합니다.',icon:'partial'},
 {id:'incomplete',title:'불완전한 수집',description:'트리 조회 실패를 원문 삭제로 해석하지 않습니다.',icon:'shield'},
];
export async function exercise(s0:State,id:string):Promise<State>{
 let s=clone(s0);let passed=false,detail='';const target=()=>s.resources.find(r=>r.id==='member-api')!;
 if(id==='noop'){const counts=s.resources.map(r=>[r.snapshots.length,r.revisions.length]);s=await collect(s);passed=s.resources.every((r,i)=>r.snapshots.length===counts[i][0]&&r.revisions.length===counts[i][1]);detail='수집 시각 추가 · 스냅샷 / 리비전 증가 없음';}
 if(id==='register'){const n=s.resources.length+1;const name=`orion.backoffice.demo.task-new-${n}`;const raw=sampleYaml('task',name,'신규 작업 '+n);const snap={id:uid(),raw,hash:await digest(raw),gitSha:s.gitSha,collectedAt:stamp()};const r:Resource={id:'new-'+uid(),path:`platform/orion/backoffice/demo/tasks/new-${n}.yaml`,kind:'task',name,key:name,title:'신규 작업 '+n,snapshots:[snap],source:snap,collections:[{id:uid(),at:stamp(),gitSha:s.gitSha,snapshotId:snap.id,result:'changed'}],revisions:[],active:null,drift:false,failure:null,failNext:false};s.resources.push(r);s=sync(s,[r.id]);passed=s.resources.find(x=>x.id===r.id)?.revisions[0]?.operation==='register';detail='미등록 → 동기화 → 리소스 등록 / r1';}
 if(id==='delete'){s=sync(s,['member-api']);const prev=target().revisions.length;if(target().source.raw===null){s=await collect(s,{'member-api':sampleYaml('service','member-api','회원 API',prev+1)});s=sync(s,['member-api']);}s=await collect(s,{'member-api':null});s=sync(s,['member-api']);passed=current(target())?.snapshot.raw===null;detail='삭제 원문 스냅샷과 삭제 리비전 보존 · 리소스 비활성';}
 if(id==='restore'){if(target().source.raw!==null){s=await collect(s,{'member-api':null});s=sync(s,['member-api']);}s=await collect(s,{'member-api':sampleYaml('service','member-api','회원 API',target().revisions.length+1)});s=sync(s,['member-api']);passed=newest(target())?.operation==='restore';detail='동일 ID / 전역 키 유지 · 복원 리비전 생성';}
 if(id==='drift'){s=sync(s,['member-api']);const before=target().revisions.length;target().drift=true;s=sync(s,['member-api']);passed=!target().drift&&target().revisions.length===before;detail='실제 적용 상태 복구 시뮬레이션 · 새 리비전 0개';}
 if(id==='retry'||id==='partial'){const a=s.resources.find(r=>r.id==='read')!,b=s.resources.find(r=>r.id==='detail')!;s=await collect(s,{[a.id]:a.source.raw+'\n# 변경 시나리오 '+uid()+(id==='partial'?'\n':'') ,...(id==='partial'?{[b.id]:b.source.raw+'\n# 부분 실패 '+uid()}: {})});const prev=s.resources.find(r=>r.id===a.id)!.revisions.length;s.resources.find(r=>r.id===a.id)!.failNext=true;s=sync(s,id==='partial'?[a.id,b.id]:[a.id]);const preserved=s.resources.find(r=>r.id===a.id)!.revisions.length===prev;const partial=s.runs[0].status==='partial';s=sync(s,[a.id]);passed=preserved&&!s.resources.find(r=>r.id===a.id)!.failure&&(id!=='partial'||partial);detail=id==='partial'?'파일 1 성공 / 파일 1 실패 → 실패 건만 재시도 · 성공 건 리비전 유지':'첫 시도 리비전 유지 → 재시도 1회 성공 · 감사 이력 보존';}
 if(id==='incomplete'){const before=JSON.stringify(s.resources);s=await collect(s,{}, {},false);passed=JSON.stringify(s.resources)===before;detail='수집 실패 기록 · 삭제 없음 · 정상 스냅샷 보존';}
 s.scenarios[id]={at:stamp(),passed,detail};return s;
}
