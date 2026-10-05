"""SQLite database for reviews (SQLAlchemy).

Four tables:
  reviews   one row per submission (status, request, live progress, error, times)
  patches   one row per reviewed file: its final verified code, diff and explanation
  findings  one row per pylint finding in the ORIGINAL file, with whether it was fixed
  feedback  thumbs up / down on a review, or on one file in it

The file defaults to reviews.db in the project root; set REVIEW_DB to use another
path (the tests use a temporary one). Times are stored as ISO-8601 UTC strings, the
same text the API returns.
"""
import os

from sqlalchemy import (Boolean, ForeignKey, Integer, String, Text, JSON,
                        create_engine, event)
from sqlalchemy.orm import (DeclarativeBase, Mapped, mapped_column, relationship,
                            sessionmaker)

DB_PATH = os.environ.get("REVIEW_DB", "reviews.db")


class Base(DeclarativeBase):
    pass


class Review(Base):
    __tablename__ = "reviews"
    id: Mapped[str] = mapped_column(String(12), primary_key=True)
    status: Mapped[str] = mapped_column(String(10), index=True)  # queued/running/done/failed
    source_type: Mapped[str] = mapped_column(String(10))           # code/folder/github
    request: Mapped[dict] = mapped_column(JSON)
    progress: Mapped[dict] = mapped_column(JSON)
    error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[str] = mapped_column(String(32))
    started_at: Mapped[str | None] = mapped_column(String(32))
    finished_at: Mapped[str | None] = mapped_column(String(32))

    patches: Mapped[list["Patch"]] = relationship(
        back_populates="review", order_by="Patch.id", cascade="all, delete-orphan")
    feedback: Mapped[list["Feedback"]] = relationship(
        back_populates="review", order_by="Feedback.id", cascade="all, delete-orphan")


class Patch(Base):
    """The outcome for one file: corrected_code is None when no fix was verified."""
    __tablename__ = "patches"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    review_id: Mapped[str] = mapped_column(ForeignKey("reviews.id"), index=True)
    filepath: Mapped[str] = mapped_column(Text)
    original_code: Mapped[str] = mapped_column(Text)
    corrected_code: Mapped[str | None] = mapped_column(Text)
    diff: Mapped[str | None] = mapped_column(Text)
    explanation: Mapped[str | None] = mapped_column(Text)
    explanation_source: Mapped[str | None] = mapped_column(String(64))
    explanation_problems: Mapped[list] = mapped_column(JSON, default=list)
    fixed_issues: Mapped[list] = mapped_column(JSON, default=list)      # pylint summary
    remaining_issues: Mapped[list] = mapped_column(JSON, default=list)  # line numbers are post-fix
    verified_fix: Mapped[bool] = mapped_column(Boolean)
    history: Mapped[list] = mapped_column(JSON, default=list)           # the agent's steps

    review: Mapped[Review] = relationship(back_populates="patches")
    findings: Mapped[list["Finding"]] = relationship(
        back_populates="patch", order_by="Finding.id", cascade="all, delete-orphan")


class Finding(Base):
    __tablename__ = "findings"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    patch_id: Mapped[int] = mapped_column(ForeignKey("patches.id"), index=True)
    review_id: Mapped[str] = mapped_column(ForeignKey("reviews.id"), index=True)
    line: Mapped[int | None] = mapped_column(Integer)
    type: Mapped[str | None] = mapped_column(String(20))
    symbol: Mapped[str | None] = mapped_column(String(80), index=True)
    message: Mapped[str | None] = mapped_column(Text)
    fixed: Mapped[bool] = mapped_column(Boolean)

    patch: Mapped[Patch] = relationship(back_populates="findings")


class Feedback(Base):
    __tablename__ = "feedback"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    review_id: Mapped[str] = mapped_column(ForeignKey("reviews.id"), index=True)
    rating: Mapped[str] = mapped_column(String(4))  # up / down
    filepath: Mapped[str | None] = mapped_column(Text)
    comment: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[str] = mapped_column(String(32))

    review: Mapped[Review] = relationship(back_populates="feedback")


# check_same_thread=False: the worker thread writes while API threads read. Each
# function in jobs.py opens its own short session, so no session is shared.
engine = create_engine(f"sqlite:///{DB_PATH}", connect_args={"check_same_thread": False})


@event.listens_for(engine, "connect")
def _sqlite_pragmas(dbapi_conn, _):
    cur = dbapi_conn.cursor()
    cur.execute("PRAGMA journal_mode=WAL")  # readers don't block the worker's writes
    cur.execute("PRAGMA foreign_keys=ON")
    cur.close()


Session = sessionmaker(engine, expire_on_commit=False)


def init_db() -> None:
    Base.metadata.create_all(engine)
