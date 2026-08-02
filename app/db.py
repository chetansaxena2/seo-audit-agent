"""Storage. SQLite by default, any SQLAlchemy URL via DATABASE_URL
(Postgres recommended once you are past a few thousand audits)."""
from __future__ import annotations

import json
import secrets
import uuid
from datetime import date, datetime, timezone
from typing import Any

from sqlalchemy import (JSON, Column, DateTime, Float, Integer, String, Text,
                        create_engine, func, select)
from sqlalchemy.orm import Session, declarative_base, sessionmaker

from .config import settings

Base = declarative_base()
_engine = create_engine(
    settings.database_url,
    connect_args={"check_same_thread": False} if settings.database_url.startswith("sqlite") else {},
    pool_pre_ping=True,
)
SessionLocal = sessionmaker(bind=_engine, expire_on_commit=False)


class Audit(Base):
    __tablename__ = "audits"

    id = Column(String(32), primary_key=True)
    url = Column(String(2048), nullable=False)
    domain = Column(String(255), index=True)
    status = Column(String(20), default="queued", index=True)  # queued|running|completed|failed
    stage = Column(String(255), default="")
    progress = Column(Integer, default=0)
    options = Column(JSON, default=dict)
    result = Column(JSON)
    error = Column(Text)
    webhook_url = Column(String(2048))
    share_token = Column(String(48), unique=True, index=True)
    client_ref = Column(String(255), index=True)     # your CRM / client id
    api_key = Column(String(64))
    overall_score = Column(Float)
    grade = Column(String(2))
    authority = Column(Float)
    ai_score = Column(Float)
    error_score = Column(Float)
    page_speed = Column(Float)
    google_optimized = Column(Float)
    critical_issues = Column(Integer)
    total_issues = Column(Integer)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), index=True)
    started_at = Column(DateTime)
    finished_at = Column(DateTime)
    duration_sec = Column(Float)
    pdf_path = Column(String(1024))
    html_path = Column(String(1024))

    def summary(self) -> dict[str, Any]:
        return {
            "audit_id": self.id,
            "url": self.url,
            "domain": self.domain,
            "status": self.status,
            "stage": self.stage,
            "progress": self.progress,
            "client_ref": self.client_ref,
            "overall_score": self.overall_score,
            "grade": self.grade,
            "scores": {
                "authority": self.authority,
                "ai_score": self.ai_score,
                "error_score": self.error_score,
                "page_speed": self.page_speed,
                "google_optimized": self.google_optimized,
            },
            "issues": {"critical": self.critical_issues, "total": self.total_issues},
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "finished_at": self.finished_at.isoformat() if self.finished_at else None,
            "duration_sec": self.duration_sec,
            "share_url": (f"{settings.public_base_url.rstrip('/')}/share/{self.share_token}"
                          if self.share_token else None),
            "report_html": f"{settings.public_base_url.rstrip('/')}/audits/{self.id}/report.html",
            "report_pdf": f"{settings.public_base_url.rstrip('/')}/audits/{self.id}/report.pdf",
            "error": self.error,
        }


def init_db() -> None:
    Base.metadata.create_all(_engine)


def create_audit(url: str, options: dict, api_key: str = "", webhook_url: str = "",
                 client_ref: str = "") -> Audit:
    from urllib.parse import urlparse
    with SessionLocal() as s:
        audit = Audit(
            id=uuid.uuid4().hex[:16],
            url=url,
            domain=urlparse(url if "//" in url else f"https://{url}").netloc,
            options=options,
            api_key=api_key[:64],
            webhook_url=webhook_url,
            client_ref=client_ref,
            share_token=secrets.token_urlsafe(24),
            status="queued",
        )
        s.add(audit)
        s.commit()
        return audit


def update(audit_id: str, **fields: Any) -> None:
    with SessionLocal() as s:
        audit = s.get(Audit, audit_id)
        if not audit:
            return
        for key, value in fields.items():
            setattr(audit, key, value)
        s.commit()


def save_result(audit_id: str, result: dict) -> None:
    scores = result.get("scores", {})
    head = scores.get("headline", {})
    counts = scores.get("issue_counts", {})
    update(
        audit_id,
        status=result.get("status", "completed"),
        result=result,
        progress=100,
        stage="completed",
        finished_at=datetime.now(timezone.utc),
        duration_sec=result.get("duration_sec"),
        overall_score=scores.get("overall_score"),
        grade=scores.get("grade"),
        authority=head.get("authority"),
        ai_score=head.get("ai_score"),
        error_score=head.get("error_score"),
        page_speed=head.get("page_speed"),
        google_optimized=head.get("google_optimized"),
        critical_issues=counts.get("critical"),
        total_issues=counts.get("total"),
    )


def get(audit_id: str) -> Audit | None:
    with SessionLocal() as s:
        return s.get(Audit, audit_id)


def get_by_token(token: str) -> Audit | None:
    with SessionLocal() as s:
        return s.scalar(select(Audit).where(Audit.share_token == token))


def list_audits(limit: int = 50, offset: int = 0, status: str | None = None,
                domain: str | None = None, client_ref: str | None = None) -> list[dict]:
    with SessionLocal() as s:
        stmt = select(Audit).order_by(Audit.created_at.desc()).limit(limit).offset(offset)
        if status:
            stmt = stmt.where(Audit.status == status)
        if domain:
            stmt = stmt.where(Audit.domain.contains(domain))
        if client_ref:
            stmt = stmt.where(Audit.client_ref == client_ref)
        return [a.summary() for a in s.scalars(stmt).all()]


def count_today() -> int:
    with SessionLocal() as s:
        start = datetime.combine(date.today(), datetime.min.time())
        return s.scalar(select(func.count(Audit.id)).where(Audit.created_at >= start)) or 0


def pending_audits() -> list[str]:
    """Requeue anything left mid-flight by a restart."""
    with SessionLocal() as s:
        stmt = select(Audit).where(Audit.status.in_(["queued", "running"])).order_by(Audit.created_at)
        return [a.id for a in s.scalars(stmt).all()]


def stats() -> dict:
    with SessionLocal() as s:
        total = s.scalar(select(func.count(Audit.id))) or 0
        done = s.scalar(select(func.count(Audit.id)).where(Audit.status == "completed")) or 0
        failed = s.scalar(select(func.count(Audit.id)).where(Audit.status == "failed")) or 0
        avg = s.scalar(select(func.avg(Audit.overall_score)).where(Audit.status == "completed"))
        avg_time = s.scalar(select(func.avg(Audit.duration_sec)).where(Audit.status == "completed"))
        return {
            "total_audits": total,
            "completed": done,
            "failed": failed,
            "in_progress": total - done - failed,
            "today": count_today(),
            "daily_quota": settings.daily_audit_quota,
            "quota_remaining": max(0, settings.daily_audit_quota - count_today()),
            "avg_overall_score": round(avg, 1) if avg else None,
            "avg_duration_sec": round(avg_time, 1) if avg_time else None,
        }
