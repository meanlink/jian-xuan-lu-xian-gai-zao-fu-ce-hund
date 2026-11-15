import time, os, csv, io, hashlib, json
from fastapi import HTTPException
from src.models import Job, Report, Delivery
from src.config.settings import ARTIFACT_DIR
def create(db, data):
    j=db.get(Job,data.job_id)
    if not j or j.status!='completed' or not j.approved:
        raise HTTPException(409,'请先选择已完成且获批准的分析结果')
    r=Report(name=data.name, job_id=j.id, destination=data.destination, interval_seconds=data.interval_seconds, next_run=time.time()+data.delay_seconds, enabled=True)
    db.add(r); db.flush()
    return r
def render_csv(result):
    out=io.StringIO()
    out.write('\ufeff')
    table=result.get('table',{})
    cols=table.get('columns',[])
    writer=csv.writer(out)
    def safe(v):
        if isinstance(v,(int,float)) and not isinstance(v,bool): return v
        text=str(v)
        return "'"+text if text.startswith(('=','+','-','@','\t','\r')) else text
    writer.writerow([safe(c['label']) for c in cols])
    for row in table.get('rows',[]): writer.writerow([safe(row.get(c['key'],'')) for c in cols])
    return out.getvalue()
def render_json(job_name, params, result, checksum):
    return json.dumps({'job':job_name,'params':params,'result':result,'checksum':checksum},ensure_ascii=False,allow_nan=False)
def write_atomic(path, data):
    tmp=f'{path}.tmp-{os.getpid()}-{time.time_ns()}'
    with open(tmp,'wb') as f:
        f.write(data); f.flush(); os.fsync(f.fileno())
    os.replace(tmp,path)
def deliver(db, report):
    j=db.get(Job,report.job_id)
    if not j or not j.approved: return
    csv_text=render_csv(j.result)
    data=csv_text.encode('utf-8')
    checksum=hashlib.sha256(data).hexdigest()
    json_text=render_json(j.name,j.params,j.result,checksum)
    # 归档时留存可信快照与两种文件的校验指纹，供日后对账与修复；快照只在此刻写入，之后不再改动
    delivery=Delivery(report_id=report.id, created_at=time.time(), checksum=checksum, filename='', destination=report.destination,
                      json_checksum=hashlib.sha256(json_text.encode('utf-8')).hexdigest(),
                      csv_content=csv_text, json_content=json_text, status='ok')
    db.add(delivery); db.flush()
    delivery.filename=f'report-{report.id}-delivery-{delivery.id}.csv'
    os.makedirs(ARTIFACT_DIR,exist_ok=True)
    write_atomic(os.path.join(ARTIFACT_DIR,delivery.filename),data)
    write_atomic(os.path.join(ARTIFACT_DIR,delivery.filename+'.json'),json_text.encode('utf-8'))
    report.next_run=time.time()+report.interval_seconds
    return delivery
