import os, hashlib
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from sqlalchemy import select
from src.config.database import get_db
from src.config.settings import ARTIFACT_DIR
from src.models import Report, Delivery
from src.schemas.report import ReportInput
from src.middlewares.auth import current_user, admin_only
from src.services import reports, reconcile
from src.services.audit import record
from src.utils.serialization import report_dict, delivery_dict
router=APIRouter()
@router.get('/reports')
def listing(db=Depends(get_db),u=Depends(current_user)):
    return [report_dict(r) for r in db.scalars(select(Report).order_by(Report.id.desc()))]
@router.post('/reports',status_code=201)
def create(data:ReportInput,db=Depends(get_db),u=Depends(admin_only)):
    r=reports.create(db,data); record(db,u.email,'report.schedule',{'id':r.id,'destination':r.destination}); db.commit()
    return report_dict(r)
@router.post('/reports/{id}/toggle')
def toggle(id:int,db=Depends(get_db),u=Depends(admin_only)):
    r=db.get(Report,id)
    if not r:raise HTTPException(404,'分发计划不存在')
    r.enabled=not r.enabled;record(db,u.email,'report.toggle',{'id':id,'enabled':r.enabled});db.commit()
    return report_dict(r)
@router.get('/deliveries')
def deliveries(db=Depends(get_db),u=Depends(current_user)):
    return [delivery_dict(d) for d in db.scalars(select(Delivery).order_by(Delivery.id.desc()).limit(100))]
@router.get('/deliveries/{id}/download')
def download(id:int,format:str='csv',db=Depends(get_db),u=Depends(current_user)):
    d=db.get(Delivery,id)
    if not d:raise HTTPException(404,'归档不存在')
    if format not in ('csv','json'):raise HTTPException(422,'支持 CSV 或 JSON')
    if d.status!='ok':raise HTTPException(423,'归档已被对账隔离，待修复或人工核验后再下载')
    filename=d.filename+('.json' if format=='json' else '')
    p=os.path.join(ARTIFACT_DIR,filename)
    expected=d.json_checksum if format=='json' else d.checksum
    if not os.path.isfile(p):
        reconcile.flag_from_download(db,d,'missing',filename)
        record(db,u.email,'recon.download_blocked',{'delivery':id,'reason':'missing','file':filename})
        db.commit()
        raise HTTPException(404,'归档文件缺失，已隔离并登记对账差异')
    data=open(p,'rb').read()
    if expected is None:
        reconcile.flag_from_download(db,d,'no_basis',filename)
        record(db,u.email,'recon.download_blocked',{'delivery':id,'reason':'no_basis','file':filename})
        db.commit()
        raise HTTPException(409,'归档缺少留存校验依据，已隔离待人工核验')
    if hashlib.sha256(data).hexdigest()!=expected:
        reconcile.flag_from_download(db,d,'corrupted',filename)
        record(db,u.email,'recon.download_blocked',{'delivery':id,'reason':'corrupted','file':filename})
        db.commit()
        raise HTTPException(409,'归档文件校验不符，已隔离等待对账修复')
    media='application/json' if format=='json' else 'text/csv; charset=utf-8'
    return Response(content=data,media_type=media,headers={'Content-Disposition':f'attachment; filename="{filename}"'})
