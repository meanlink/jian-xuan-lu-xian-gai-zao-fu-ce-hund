import time, json, logging, os
from pathlib import Path
from sqlalchemy import select
from redis import Redis
from src.config.database import Session
from src.config.settings import REDIS_URL
from src.models import Job, Dataset, Report
from src.services.business import analyze
from src.services.reports import deliver
from src.services.reconcile import run_scan, ScanLock
from src.services.audit import record
logging.basicConfig(level=logging.INFO)
RECON_INTERVAL=float(os.getenv('RECON_INTERVAL_SECONDS','600'))
last_recon=0.0
def execute(job_id):
    with Session() as db:
        j=db.get(Job,job_id)
        if not j or j.status!='queued':return
        j.status='running'; db.commit()
        try:
            d=db.get(Dataset,j.dataset_id)
            result=analyze(d.records,j.params)
            json.dumps(result,allow_nan=False)
            j.result=result;j.status='completed';j.finished_at=time.time()
            record(db,'worker','job.completed',{'id':j.id})
        except Exception as e:
            logging.exception('Analysis failed')
            j.status='failed';j.error=str(e)[:990];j.finished_at=time.time()
            record(db,'worker','job.failed',{'id':j.id,'error':j.error})
        db.commit()
def reconcile_due():
    global last_recon
    if time.time()-last_recon<RECON_INTERVAL:return
    last_recon=time.time()
    lock=ScanLock()
    if not lock.acquire():return
    try:
        with Session() as db:
            run=run_scan(db,'worker')
            db.commit()
        if run.status!='completed' or run.missing_count or run.corrupted_count or run.no_basis_count or run.unregistered_count:
            logging.warning('Recon scan %s finished: %s missing, %s corrupted, %s no_basis, %s unregistered',
                            run.id,run.missing_count,run.corrupted_count,run.no_basis_count,run.unregistered_count)
    except Exception:
        logging.exception('Recon scan failed')
    finally:
        lock.release()
def tick():
    with Session() as db:
        queued=list(db.scalars(select(Job.id).where(Job.status=='queued').limit(3)))
    for job_id in queued:execute(job_id)
    with Session() as db:
        for r in db.scalars(select(Report).where(Report.enabled==True,Report.next_run<=time.time())):
            d=deliver(db,r)
            if d:record(db,'worker','report.delivered',{'id':r.id,'delivery':d.id})
        db.commit()
    reconcile_due()
def main():
    r=Redis.from_url(REDIS_URL,socket_timeout=3)
    # This Compose stack has a single worker. A crash must not strand its jobs.
    with Session() as db:
        for j in db.scalars(select(Job).where(Job.status=='running')):
            j.status='queued';record(db,'worker','job.recovered',{'id':j.id})
        db.commit()
    while True:
        Path('/tmp/heartbeat').touch()
        try:
            item=r.blpop('analysis:queue',timeout=1)
            if item:execute(int(item[1]))
            tick()
        except Exception:
            logging.exception('Worker retry');time.sleep(2)
if __name__=='__main__':main()
