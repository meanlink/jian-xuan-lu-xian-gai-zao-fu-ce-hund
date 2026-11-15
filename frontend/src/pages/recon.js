import {recon} from '../api/entities.js';
import {session} from '../stores/session.js';
import {heading} from '../components/common/shell.js';
import {esc,date,notify} from '../utils/dom.js';
import {ReconCategory,ReconStatus,ReconRunStatus} from '../constants/enums.js';
const short=v=>v?esc(String(v).slice(0,12))+'…':'—';
const fileLabel={csv:'CSV',json:'JSON'};
function diffText(f){
 if(f.category==='unregistered')return '收件箱出现未登记文件，已移至隔离区保留'+(f.detail&&f.detail.size!=null?'（'+f.detail.size+' 字节）':'');
 const files=(f.detail&&f.detail.files)||{};
 return Object.keys(fileLabel).map(k=>{
  const s=files[k];if(!s)return '';
  if(s.state==='missing')return fileLabel[k]+' 文件缺失';
  if(s.state==='mismatch')return fileLabel[k]+' 校验不符 · 留存 '+short(s.expected)+' 实际 '+short(s.actual);
  if(s.state==='unverifiable')return fileLabel[k]+' 无留存指纹，无法核验';
  return '';
 }).filter(Boolean).join('；')||'—';
}
function basisText(f){
 const b=f.repair_basis;
 if(!b)return f.status==='quarantined'&&f.delivery_id?'等待按留存快照修复':'—';
 if(b.source==='archive_snapshot')return '归档时留存快照 · CSV '+short(b.csv_checksum)+' JSON '+short(b.json_checksum);
 if(b.source==='integrity_verified')return '文件与留存指纹一致，对账自动恢复';
 if(b.source==='manual_attestation')return '人工核验放行 · '+esc(b.actor||'')+' · '+esc(b.note||'');
 if(b.source==='manual_review')return '人工确认保持隔离 · '+esc(b.actor||'')+' · '+esc(b.note||'');
 return '—';
}
function actions(f){
 if(session.user.role!=='admin')return '';
 if(f.status==='quarantined'&&f.delivery_id&&f.repairable)return '<button class="text-button" data-repair="'+f.id+'">按留存快照修复</button>';
 if(f.status==='manual_review'&&f.delivery_id)return '<button class="text-button" data-release="'+f.id+'">人工放行</button><button class="text-button" data-keep="'+f.id+'">保持隔离</button>';
 if(f.status==='quarantined'&&!f.delivery_id)return '<button class="text-button" data-keep="'+f.id+'">确认隔离保留</button>';
 return '';
}
export async function reconPage(){
 const [runs,findings]=await Promise.all([recon.runs(),recon.findings()]);
 const latest=runs[0],open=findings.filter(f=>['quarantined','manual_review'].includes(f.status));
 const cards=latest?[['正常',latest.ok_count],['缺失',latest.missing_count],['损坏',latest.corrupted_count],['无可信依据',latest.no_basis_count],['未登记文件',latest.unregistered_count],['自动恢复',latest.auto_resolved_count]]:[];
 return heading('06 / RECONCILIATION','归档完整性对账','逐份核对归档记录、留存快照与两种下载文件。异常归档立即隔离，仅凭归档时留存的可信快照修复；没有可信依据的旧归档留待人工核验。','<button class="button primary" id="run-recon" '+(session.user.role!=='admin'?'disabled':'')+'>立即对账 ⟳</button>')
 +'<section class="overview-hero recon-hero"><div class="narrative"><p class="eyebrow">最近对账</p><h2>'+(latest?(ReconRunStatus[latest.status]||latest.status)+' · 核对 '+latest.total+' 份归档':'尚未执行对账')+'</h2><p>'+(latest?date(latest.started_at)+' · 触发：'+esc(latest.triggered_by)+(latest.inflight_count?' · '+latest.inflight_count+' 份新归档在写入宽限期，本轮跳过':'')+(latest.error?' · '+esc(latest.error):''):'点击「立即对账」开始首次核对。')+'</p><p class="hint">当前待处理差异 '+open.length+' 条。对账与分发并发时，新归档不会被误判；修复中断后由下次对账自动收尾。</p></div><div class="numbers">'+cards.map(([k,v])=>'<div><span>'+k+'</span><strong>'+v+'</strong></div>').join('')+'</div></section>'
 +'<section class="panel"><div class="section-title"><h2>差异与处理</h2><span>'+open.length+' 条待处理 · 共 '+findings.length+' 条记录</span></div><div class="table-wrap"><table><thead><tr><th>归档 / 文件</th><th>类别</th><th>差异明细</th><th>状态</th><th>修复依据</th><th>发现</th><th>操作</th></tr></thead><tbody>'
 +(findings.length?findings.map(f=>'<tr><td><strong>'+esc(f.filename||('归档 #'+(f.delivery_id??'')))+'</strong><br><small>'+esc(f.destination||'未登记文件')+'</small></td><td>'+(ReconCategory[f.category]||f.category)+'</td><td>'+diffText(f)+'</td><td><span class="status recon-'+esc(f.status)+'">'+(ReconStatus[f.status]||f.status)+'</span></td><td>'+basisText(f)+'</td><td>'+date(f.last_seen_at)+(f.seen_count>1?'<br><small>第 '+f.seen_count+' 次</small>':'')+'</td><td class="recon-actions">'+actions(f)+'</td></tr>').join(''):'<tr><td colspan="7" class="empty">暂无差异记录。执行对账后，异常归档会在此列出。</td></tr>')
 +'</tbody></table></div></section>'
 +'<section class="panel"><div class="section-title"><h2>对账进度</h2><span>最近 '+runs.length+' 次</span></div><div class="table-wrap"><table><thead><tr><th>批次</th><th>触发</th><th>状态</th><th>核对</th><th>正常</th><th>缺失</th><th>损坏</th><th>无依据</th><th>未登记</th><th>自动恢复</th><th>耗时</th></tr></thead><tbody>'
 +(runs.length?runs.map(r=>'<tr><td>#'+r.id+'</td><td>'+esc(r.triggered_by)+'</td><td>'+(ReconRunStatus[r.status]||r.status)+'</td><td>'+r.total+'</td><td>'+r.ok_count+'</td><td>'+r.missing_count+'</td><td>'+r.corrupted_count+'</td><td>'+r.no_basis_count+'</td><td>'+r.unregistered_count+'</td><td>'+r.auto_resolved_count+'</td><td>'+(r.finished_at?Math.max(0.1,r.finished_at-r.started_at).toFixed(1)+' 秒':'进行中')+'</td></tr>').join(''):'<tr><td colspan="11" class="empty">暂无对账记录。</td></tr>')
 +'</tbody></table></div></section>';
}
export function bindRecon(refresh){
 const runBtn=document.querySelector('#run-recon');
 if(runBtn)runBtn.onclick=async()=>{runBtn.disabled=true;try{const r=await recon.run();notify('对账完成：核对 '+r.total+' 份 · 缺失 '+r.missing_count+' · 损坏 '+r.corrupted_count+' · 无依据 '+r.no_basis_count+' · 未登记 '+r.unregistered_count);}catch(e){notify(e.message,true);}await refresh();};
 document.querySelectorAll('[data-repair]').forEach(b=>b.onclick=async()=>{try{await recon.repair(b.dataset.repair);notify('已按归档时留存快照修复，下载恢复');}catch(e){notify(e.message,true);}await refresh();});
 const review=async(id,decision)=>{const note=window.prompt(decision==='release'?'填写人工核验依据（已与批准结果核对说明）：':'填写保持隔离的原因：');if(!note)return;try{await recon.review(id,{decision,note});notify(decision==='release'?'已人工放行':'已确认保持隔离');}catch(e){notify(e.message,true);}await refresh();};
 document.querySelectorAll('[data-release]').forEach(b=>b.onclick=()=>review(b.dataset.release,'release'));
 document.querySelectorAll('[data-keep]').forEach(b=>b.onclick=()=>review(b.dataset.keep,'keep'));
}
