import enum

from sqlalchemy import JSON, Column, BigInteger, Enum, Integer, String, Text, Boolean, DateTime, ForeignKey, UniqueConstraint
from sqlalchemy.sql import func

from .database import Base


class Repository(Base):
    __tablename__ = "repositories"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    github_id = Column(BigInteger, nullable=False, unique=True)
    owner = Column(Text, nullable=False)
    name = Column(Text, nullable=False)
    full_name = Column(Text, nullable=False)
    default_branch = Column(Text)
    installation_id = Column(BigInteger, nullable=True)
    url = Column(Text)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())


class PullRequest(Base):
    __tablename__ = "pull_requests"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    github_id = Column(BigInteger, nullable=False, unique=True)
    repository_id = Column(BigInteger, ForeignKey("repositories.id"), nullable=False)
    number = Column(Integer, nullable=False)
    title = Column(Text, nullable=False)
    body = Column(Text)
    state = Column(String(20), nullable=False)
    draft = Column(Boolean, nullable=False, default=False)
    author_login = Column(Text, nullable=False)
    source_branch = Column(Text, nullable=False)
    target_branch = Column(Text, nullable=False)
    head_sha = Column(String(40), nullable=False)
    base_sha = Column(String(40), nullable=False)
    url = Column(Text, nullable=False)
    opened_at = Column(DateTime(timezone=True), nullable=False)
    closed_at = Column(DateTime(timezone=True))
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())

    __table_args__ = (
        UniqueConstraint("repository_id", "number", name="uq_repo_pr_number"),
    )


class PullRequestFile(Base):
    __tablename__ = "pull_request_files"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    pull_request_id = Column(BigInteger, ForeignKey("pull_requests.id", ondelete="CASCADE"), nullable=False)
    filename = Column(Text, nullable=False)
    status = Column(String(20), nullable=False)
    additions = Column(Integer, nullable=False, default=0)
    deletions = Column(Integer, nullable=False, default=0)
    changes = Column(Integer, nullable=False, default=0)
    patch = Column(Text)
    sha = Column(String(40))
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())

    __table_args__ = (
        UniqueConstraint("pull_request_id", "filename", name="uq_pr_file"),
    )

class JobStatus(str, enum.Enum):
    pending = "pending"
    running = "running"
    done = "done"
    failed = "failed"

class ExplanationStatus(str, enum.Enum):
    pending = "pending"
    running = "running"
    done = "done"
    failed = "failed"
    skipped = "skipped"

class AnalysisJob(Base):
    __tablename__ = "analysis_jobs"

    id = Column(BigInteger, primary_key=True)
    pull_request_id = Column(BigInteger, ForeignKey("pull_requests.id", ondelete="CASCADE"), nullable=False)
    status = Column(Enum(JobStatus), nullable=False, default=JobStatus.pending)
    error = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    started_at = Column(DateTime(timezone=True), nullable=True)
    finished_at = Column(DateTime(timezone=True), nullable=True)
    results = Column(JSON, nullable=True)


    explanation = Column(JSON, nullable=True)
    explanation_status = Column(
        Enum(ExplanationStatus), nullable=False, default=ExplanationStatus.pending
    )
    explanation_error = Column(Text, nullable=True)
    explanation_started_at = Column(DateTime(timezone=True), nullable=True)
    explanation_finished_at = Column(DateTime(timezone=True), nullable=True)