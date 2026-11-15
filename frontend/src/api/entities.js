import {api} from './client.js';
export const datasets={list:()=>api('/datasets'),get:id=>api('/datasets/'+id),create:data=>api('/datasets',{method:'POST',body:JSON.stringify(data)})};
export const jobs={list:()=>api('/jobs'),get:id=>api('/jobs/'+id),create:data=>api('/jobs',{method:'POST',body:JSON.stringify(data)}),approve:id=>api('/jobs/'+id+'/approve',{method:'POST'})};
export const reports={list:()=>api('/reports'),create:data=>api('/reports',{method:'POST',body:JSON.stringify(data)}),toggle:id=>api('/reports/'+id+'/toggle',{method:'POST'}),deliveries:()=>api('/deliveries')};
export const recon={runs:()=>api('/reconcile/runs'),findings:()=>api('/reconcile/findings'),run:()=>api('/reconcile/run',{method:'POST'}),repair:id=>api('/reconcile/findings/'+id+'/repair',{method:'POST'}),review:(id,data)=>api('/reconcile/findings/'+id+'/review',{method:'POST',body:JSON.stringify(data)})};
