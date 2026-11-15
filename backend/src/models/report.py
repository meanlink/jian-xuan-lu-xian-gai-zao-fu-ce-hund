from sqlalchemy import String, Double, ForeignKey, Boolean, Text
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.dialects.mysql import MEDIUMTEXT
from src.config.database import Base
SnapshotText = Text().with_variant(MEDIUMTEXT(), 'mysql')
class Report(Base):
    __tablename__ = 'reports'
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(160))
    job_id: Mapped[int] = mapped_column(ForeignKey('jobs.id'))
    destination: Mapped[str] = mapped_column(String(120))
    interval_seconds: Mapped[int]
    next_run: Mapped[float] = mapped_column(Double)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
class Delivery(Base):
    __tablename__ = 'deliveries'
    id: Mapped[int] = mapped_column(primary_key=True)
    report_id: Mapped[int] = mapped_column(ForeignKey('reports.id'))
    created_at: Mapped[float] = mapped_column(Double)
    checksum: Mapped[str] = mapped_column(String(64))
    filename: Mapped[str] = mapped_column(String(160))
    destination: Mapped[str] = mapped_column(String(120))
    json_checksum: Mapped[str | None] = mapped_column(String(64), nullable=True)
    # 归档时留存的可信快照：两种下载文件的原始内容，修复只能以它为据
    csv_content: Mapped[str | None] = mapped_column(SnapshotText, nullable=True)
    json_content: Mapped[str | None] = mapped_column(SnapshotText, nullable=True)
    status: Mapped[str] = mapped_column(String(20), default='ok')  # ok / quarantined / manual_review
