from sqlalchemy import String, Double, Integer, JSON, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column
from src.config.database import Base
class ReconRun(Base):
    __tablename__ = 'recon_runs'
    id: Mapped[int] = mapped_column(primary_key=True)
    started_at: Mapped[float] = mapped_column(Double)
    finished_at: Mapped[float | None] = mapped_column(Double, nullable=True)
    status: Mapped[str] = mapped_column(String(20), default='running')  # running / completed / failed
    triggered_by: Mapped[str] = mapped_column(String(150), default='worker')
    total: Mapped[int] = mapped_column(Integer, default=0)
    ok_count: Mapped[int] = mapped_column(Integer, default=0)
    missing_count: Mapped[int] = mapped_column(Integer, default=0)
    corrupted_count: Mapped[int] = mapped_column(Integer, default=0)
    no_basis_count: Mapped[int] = mapped_column(Integer, default=0)
    unregistered_count: Mapped[int] = mapped_column(Integer, default=0)
    auto_resolved_count: Mapped[int] = mapped_column(Integer, default=0)
    inflight_count: Mapped[int] = mapped_column(Integer, default=0)
    error: Mapped[str] = mapped_column(String(500), default='')
class ReconFinding(Base):
    __tablename__ = 'recon_findings'
    id: Mapped[int] = mapped_column(primary_key=True)
    run_id: Mapped[int | None] = mapped_column(ForeignKey('recon_runs.id'), nullable=True)
    delivery_id: Mapped[int | None] = mapped_column(ForeignKey('deliveries.id'), nullable=True)
    filename: Mapped[str] = mapped_column(String(200), default='')
    category: Mapped[str] = mapped_column(String(20))  # missing / corrupted / no_basis / unregistered
    detail: Mapped[dict] = mapped_column(JSON, default=dict)
    status: Mapped[str] = mapped_column(String(20))  # quarantined / manual_review / repaired / released / kept
    repair_basis: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    first_seen_at: Mapped[float] = mapped_column(Double)
    last_seen_at: Mapped[float] = mapped_column(Double)
    seen_count: Mapped[int] = mapped_column(Integer, default=1)
    resolved_at: Mapped[float | None] = mapped_column(Double, nullable=True)
