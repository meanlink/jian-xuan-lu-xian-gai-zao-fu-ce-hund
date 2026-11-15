from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from src.config.database import get_db
from src.models import Delivery, ReconRun, ReconFinding
from src.schemas.recon import ReviewInput
from src.middlewares.auth import current_user, admin_only
from src.services import reconcile
from src.services.audit import record
from src.utils.serialization import recon_run_dict, recon_finding_dict
router = APIRouter(prefix='/reconcile')
@router.post('/run', status_code=201)
def run(db=Depends(get_db), u=Depends(admin_only)):
    lock = reconcile.ScanLock()
    if not lock.acquire():
        raise HTTPException(409, '对账正在执行，请稍后查看结果')
    try:
        r = reconcile.run_scan(db, u.email)
        record(db, u.email, 'recon.run', {'run': r.id, 'status': r.status, 'total': r.total,
                                          'missing': r.missing_count, 'corrupted': r.corrupted_count,
                                          'no_basis': r.no_basis_count, 'unregistered': r.unregistered_count})
        db.commit()
        return recon_run_dict(r)
    finally:
        lock.release()
@router.get('/runs')
def runs(db=Depends(get_db), u=Depends(current_user)):
    return [recon_run_dict(r) for r in db.scalars(select(ReconRun).order_by(ReconRun.id.desc()).limit(20))]
@router.get('/findings')
def findings(db=Depends(get_db), u=Depends(current_user)):
    order = list(reconcile.OPEN_STATUSES)
    all_findings = db.scalars(select(ReconFinding).order_by(ReconFinding.id.desc()).limit(200)).all()
    all_findings.sort(key=lambda f: (0 if f.status in order else 1, -f.id))
    deliveries = {d.id: d for d in db.scalars(select(Delivery))}
    return [recon_finding_dict(f, deliveries.get(f.delivery_id)) for f in all_findings]
@router.post('/findings/{fid}/repair')
def repair(fid: int, db=Depends(get_db), u=Depends(admin_only)):
    f = db.get(ReconFinding, fid)
    if not f:
        raise HTTPException(404, '对账差异不存在')
    try:
        reconcile.repair_finding(db, f, u.email)
    except ValueError as e:
        db.commit()  # 保留“转人工核验”等状态推进
        raise HTTPException(409, str(e))
    record(db, u.email, 'recon.repair', {'finding': f.id, 'delivery': f.delivery_id, 'basis': f.repair_basis})
    db.commit()
    d = db.get(Delivery, f.delivery_id) if f.delivery_id else None
    return recon_finding_dict(f, d)
@router.post('/findings/{fid}/review')
def review(fid: int, data: ReviewInput, db=Depends(get_db), u=Depends(admin_only)):
    f = db.get(ReconFinding, fid)
    if not f:
        raise HTTPException(404, '对账差异不存在')
    try:
        reconcile.review_finding(db, f, data.decision, data.note, u.email)
    except ValueError as e:
        db.commit()
        raise HTTPException(409, str(e))
    record(db, u.email, 'recon.review', {'finding': f.id, 'delivery': f.delivery_id,
                                         'decision': data.decision, 'note': data.note})
    db.commit()
    d = db.get(Delivery, f.delivery_id) if f.delivery_id else None
    return recon_finding_dict(f, d)
