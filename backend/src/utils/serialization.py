import hashlib, json
def checksum(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False, allow_nan=False).encode()).hexdigest()
def dataset_dict(d):
    return {'id':d.id, 'name':d.name, 'source':d.source, 'rows':len(d.records), 'checksum':d.checksum, 'created_at':d.created_at}
def job_dict(j):
    return {k:getattr(j,k) for k in ['id','name','dataset_id','params','status','result','error','approved','created_at','finished_at']}
def report_dict(r):
    return {k:getattr(r,k) for k in ['id','name','job_id','destination','interval_seconds','next_run','enabled']}
def delivery_dict(d):
    return {k:getattr(d,k) for k in ['id','report_id','created_at','checksum','filename','destination','status']}
def recon_run_dict(r):
    return {k:getattr(r,k) for k in ['id','started_at','finished_at','status','triggered_by','total','ok_count','missing_count','corrupted_count','no_basis_count','unregistered_count','auto_resolved_count','inflight_count','error']}
def recon_finding_dict(f, delivery=None):
    d={k:getattr(f,k) for k in ['id','run_id','delivery_id','filename','category','detail','status','repair_basis','first_seen_at','last_seen_at','seen_count','resolved_at']}
    if delivery:
        d['destination']=delivery.destination
        d['delivery_status']=delivery.status
        d['repairable']=delivery.csv_content is not None and delivery.json_content is not None
    return d
