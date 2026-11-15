"""归档完整性对账：逐份核对归档记录、留存快照与两种下载文件。

原则：
- 异常归档立即隔离，下载被阻断；
- 修复只能使用归档时留存的可信快照（deliveries.csv_content / json_content），
  绝不拿当前分析结果补造历史；
- 写入一律临时文件 + 原子替换，下载不会读到半份文件；
- 对账与修复幂等：重试不重复建归档，中断后由下次对账按实际校验结果收尾；
- 没有可信快照的旧归档不自动处置，留待人工核验；未登记文件移入隔离区保留。
"""
import os, time, hashlib, threading, logging
from redis import Redis
from sqlalchemy import select
from src.config.settings import ARTIFACT_DIR, REDIS_URL
from src.models import Delivery, ReconRun, ReconFinding

GRACE_SECONDS = float(os.getenv('RECON_GRACE_SECONDS', '30'))  # 新归档宽限期，避免误判正在写入的分发
QUARANTINE_DIR = 'quarantine'
OPEN_STATUSES = ('quarantined', 'manual_review')
REPAIRABLE_CATEGORIES = ('missing', 'corrupted')

def sha256_bytes(data):
    return hashlib.sha256(data).hexdigest()

def has_snapshot(d):
    return d.csv_content is not None and d.json_content is not None

def _paths(d):
    csv_path = os.path.join(ARTIFACT_DIR, d.filename)
    return csv_path, csv_path + '.json'

def verify_delivery(d):
    """逐文件核对两种下载文件。返回 (category, detail)。

    category: ok / missing / corrupted / no_basis
    每个文件状态: ok / missing / mismatch / unverifiable（无留存指纹可比对）
    """
    csv_path, json_path = _paths(d)
    files = {}
    for key, path, expected in (('csv', csv_path, d.checksum), ('json', json_path, d.json_checksum)):
        if not os.path.isfile(path):
            files[key] = {'state': 'missing', 'expected': expected}
            continue
        actual = sha256_bytes(open(path, 'rb').read())
        if expected is None:
            files[key] = {'state': 'unverifiable', 'actual': actual}
        elif actual != expected:
            files[key] = {'state': 'mismatch', 'expected': expected, 'actual': actual}
        else:
            files[key] = {'state': 'ok', 'actual': actual}
    states = {f['state'] for f in files.values()}
    if 'missing' in states:
        return 'missing', {'files': files}
    if 'mismatch' in states:
        return 'corrupted', {'files': files}
    if 'unverifiable' in states:
        return 'no_basis', {'files': files}
    return 'ok', {'files': files}

def _open_finding(db, delivery_id=None, filename=None):
    q = select(ReconFinding).where(ReconFinding.status.in_(OPEN_STATUSES))
    if delivery_id is not None:
        q = q.where(ReconFinding.delivery_id == delivery_id)
    else:
        q = q.where(ReconFinding.delivery_id.is_(None), ReconFinding.filename == filename)
    return db.scalars(q).first()

def _flag(db, run_id, d, category, detail, now):
    """登记或刷新差异，并立即隔离归档。返回 finding。"""
    repairable = category in REPAIRABLE_CATEGORIES and has_snapshot(d)
    target = 'quarantined' if repairable else 'manual_review'
    d.status = target
    f = _open_finding(db, delivery_id=d.id)
    if f:
        f.run_id, f.category, f.detail, f.status = run_id, category, detail, target
        f.last_seen_at, f.seen_count = now, f.seen_count + 1
    else:
        f = ReconFinding(run_id=run_id, delivery_id=d.id, filename=d.filename, category=category,
                         detail=detail, status=target, first_seen_at=now, last_seen_at=now, seen_count=1)
        db.add(f)
    db.flush()
    return f

def _resolve_open(db, run_id, delivery_id, status, basis, now):
    for f in db.scalars(select(ReconFinding).where(ReconFinding.delivery_id == delivery_id,
                                                   ReconFinding.status.in_(OPEN_STATUSES))):
        f.status, f.repair_basis, f.resolved_at, f.run_id = status, basis, now, run_id

def flag_from_download(db, d, category, filename, detail=None):
    """下载时发现的异常：立即隔离并登记差异（无需等对账）。"""
    if detail is None:
        _, detail = verify_delivery(d)
        detail['detected_at'] = 'download'
    f = _flag(db, None, d, category, detail, time.time())
    return f

def _kept_finding_matches(db, d, category, detail):
    """人工已确认保持隔离且文件状态未变：不再重复登记，隔离保持生效。"""
    f = db.scalars(select(ReconFinding).where(ReconFinding.delivery_id == d.id,
                                              ReconFinding.status == 'kept')
                     .order_by(ReconFinding.id.desc())).first()
    if not f or f.category != category:
        return False
    old = (f.detail or {}).get('files', {})
    new = detail.get('files', {})
    return all(old.get(k, {}).get('state') == v.get('state') and old.get(k, {}).get('actual') == v.get('actual')
               for k, v in new.items())

def run_scan(db, triggered_by):
    """全量对账：核对所有归档记录与收件箱文件，返回 ReconRun（由调用方提交事务）。"""
    now = time.time()
    run = ReconRun(started_at=now, status='running', triggered_by=triggered_by)
    db.add(run)
    db.flush()
    try:
        counts = dict.fromkeys(['total', 'ok', 'missing', 'corrupted', 'no_basis',
                                'unregistered', 'auto_resolved', 'inflight'], 0)
        registered = set()
        for d in db.scalars(select(Delivery).order_by(Delivery.id)):
            registered.add(d.filename)
            registered.add(d.filename + '.json')
            if now - d.created_at < GRACE_SECONDS:
                counts['inflight'] += 1  # 分发与对账并发：新归档还在写入窗口，本轮不判
                continue
            counts['total'] += 1
            category, detail = verify_delivery(d)
            if category == 'ok':
                counts['ok'] += 1
                if d.status != 'ok':
                    # 修复中断等场景：文件已与留存指纹一致，自动收尾，不重复建归档
                    d.status = 'ok'
                    _resolve_open(db, run.id, d.id, 'repaired',
                                  {'source': 'integrity_verified', 'run': run.id,
                                   'note': '文件与归档留存指纹一致，对账自动恢复'}, now)
                    counts['auto_resolved'] += 1
                continue
            counts[category] += 1
            if _kept_finding_matches(db, d, category, detail):
                d.status = 'quarantined' if (category in REPAIRABLE_CATEGORIES and has_snapshot(d)) else 'manual_review'
                continue
            _flag(db, run.id, d, category, detail, now)
        counts['unregistered'] = _sweep_unregistered(db, run.id, registered, now)
        run.status = 'completed'
        for key in counts:
            setattr(run, 'total' if key == 'total' else key + '_count', counts[key])
    except Exception as e:
        logging.exception('Reconciliation scan failed')
        run.status, run.error = 'failed', str(e)[:490]
    run.finished_at = time.time()
    db.flush()
    return run

def _sweep_unregistered(db, run_id, registered, now):
    """未登记文件先隔离保留：移入 quarantine/ 并登记，重扫不重复登记。"""
    if not os.path.isdir(ARTIFACT_DIR):
        return 0
    moved = 0
    for name in sorted(os.listdir(ARTIFACT_DIR)):
        path = os.path.join(ARTIFACT_DIR, name)
        if not os.path.isfile(path) or name in registered or '.tmp-' in name:
            continue
        if now - os.path.getmtime(path) < GRACE_SECONDS:
            continue  # 可能正在写入的新归档文件，下轮再看
        qdir = os.path.join(ARTIFACT_DIR, QUARANTINE_DIR)
        os.makedirs(qdir, exist_ok=True)
        dest = os.path.join(qdir, name)
        if os.path.exists(dest):
            dest = os.path.join(qdir, f'{int(now)}-{name}')
        size = os.path.getsize(path)
        os.replace(path, dest)
        moved += 1
        f = _open_finding(db, filename=name)
        detail = {'moved_to': dest, 'size': size, 'sha256': sha256_bytes(open(dest, 'rb').read())}
        if f:
            f.run_id, f.detail, f.last_seen_at, f.seen_count = run_id, detail, now, f.seen_count + 1
        else:
            db.add(ReconFinding(run_id=run_id, delivery_id=None, filename=name, category='unregistered',
                                detail=detail, status='quarantined', first_seen_at=now, last_seen_at=now))
    db.flush()
    return moved

def repair_finding(db, f, actor):
    """仅凭归档时留存的可信快照修复；幂等，重试不重复建归档。"""
    from src.services.reports import write_atomic
    now = time.time()
    if f.status not in OPEN_STATUSES:
        return f  # 已处理（修复/放行/确认隔离），重试直接返回既有结果
    if not f.delivery_id:
        raise ValueError('未登记文件没有归档记录，无法按快照修复，仅隔离保留')
    d = db.get(Delivery, f.delivery_id)
    if not d:
        raise ValueError('归档记录不存在')
    if not has_snapshot(d):
        d.status = f.status = 'manual_review'
        db.flush()
        raise ValueError('缺少归档时留存的可信快照，无法修复，已转人工核验')
    csv_bytes = d.csv_content.encode('utf-8')
    json_bytes = d.json_content.encode('utf-8')
    if sha256_bytes(csv_bytes) != d.checksum or (d.json_checksum and sha256_bytes(json_bytes) != d.json_checksum):
        d.status = f.status = 'manual_review'
        db.flush()
        raise ValueError('留存快照与归档校验指纹不一致，已转人工核验')
    category, _ = verify_delivery(d)
    if category != 'ok':
        csv_path, json_path = _paths(d)
        os.makedirs(ARTIFACT_DIR, exist_ok=True)
        write_atomic(csv_path, csv_bytes)      # 原子替换，下载不会读到半份文件
        write_atomic(json_path, json_bytes)
        category, _ = verify_delivery(d)
        if category != 'ok':
            raise ValueError('修复后校验仍未通过，请人工核验')
    d.status = 'ok'
    f.status, f.resolved_at = 'repaired', now
    f.repair_basis = {'source': 'archive_snapshot', 'actor': actor,
                      'csv_checksum': d.checksum, 'json_checksum': d.json_checksum,
                      'files': [d.filename, d.filename + '.json']}
    db.flush()
    return f

def review_finding(db, f, decision, note, actor):
    """人工核验：放行（以人工核验结论为据）或确认保持隔离。"""
    now = time.time()
    if f.status not in OPEN_STATUSES:
        return f  # 已处理，重试幂等
    if decision == 'keep':
        f.status, f.resolved_at = 'kept', now
        f.repair_basis = {'source': 'manual_review', 'decision': 'keep', 'actor': actor, 'note': note}
        db.flush()
        return f
    if decision != 'release':
        raise ValueError('未知的核验决定')
    if not f.delivery_id:
        raise ValueError('未登记文件不能放行，仅隔离保留')
    d = db.get(Delivery, f.delivery_id)
    if not d:
        raise ValueError('归档记录不存在')
    category, detail = verify_delivery(d)
    if category == 'missing':
        raise ValueError('文件仍缺失，无法放行')
    # 人工核验通过：以当前文件为人工确认版本，留存其指纹作为后续对账依据
    previous = {'csv': d.checksum, 'json': d.json_checksum}
    attested = {k: v.get('actual') for k, v in detail['files'].items()}
    d.checksum, d.json_checksum = attested['csv'], attested['json']
    d.status = 'ok'
    f.status, f.resolved_at = 'released', now
    f.repair_basis = {'source': 'manual_attestation', 'actor': actor, 'note': note,
                      'previous': previous, 'attested': attested}
    db.flush()
    return f

class ScanLock:
    """对账互斥：优先 Redis（跨进程），Redis 不可用时退化为进程内锁。"""
    KEY = 'recon:scan:lock'
    _local = threading.Lock()
    def __init__(self):
        self._redis = None
        self._mode = None
    def acquire(self):
        try:
            r = Redis.from_url(REDIS_URL, socket_timeout=2)
            if r.set(self.KEY, str(time.time()), nx=True, ex=300):
                self._redis, self._mode = r, 'redis'
                return True
            r.close()
            return False
        except Exception:
            if self._local.acquire(blocking=False):
                self._mode = 'local'
                return True
            return False
    def release(self):
        if self._mode == 'redis' and self._redis:
            try:
                self._redis.delete(self.KEY)
                self._redis.close()
            except Exception:
                pass
        elif self._mode == 'local':
            self._local.release()
        self._mode, self._redis = None, None
