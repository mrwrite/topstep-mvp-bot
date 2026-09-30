from __future__ import annotations

from datetime import datetime, timedelta

from sqlalchemy.exc import IntegrityError, SQLAlchemyError

from . import database, models


class RateLimitStoreUnavailable(RuntimeError):
    pass


def consume(bucket_key: str, limit: int, *, window_seconds: int = 60) -> bool:
    """Atomically consume a shared database-backed rate-limit slot."""
    now = datetime.utcnow()
    window_floor = now - timedelta(seconds=window_seconds)
    db = database.SessionLocal()
    try:
        bucket = (
            db.query(models.RateLimitBucket)
            .filter(models.RateLimitBucket.bucket_key == bucket_key)
            .with_for_update()
            .first()
        )
        if bucket is None:
            bucket = models.RateLimitBucket(
                bucket_key=bucket_key,
                window_started_at=now,
                request_count=1,
                updated_at=now,
            )
            db.add(bucket)
            try:
                db.commit()
                return True
            except IntegrityError:
                db.rollback()
                bucket = (
                    db.query(models.RateLimitBucket)
                    .filter(models.RateLimitBucket.bucket_key == bucket_key)
                    .with_for_update()
                    .one()
                )
        if bucket.window_started_at <= window_floor:
            bucket.window_started_at = now
            bucket.request_count = 1
        elif bucket.request_count >= limit:
            db.rollback()
            return False
        else:
            bucket.request_count += 1
        bucket.updated_at = now
        db.commit()
        return True
    except SQLAlchemyError as exc:
        db.rollback()
        raise RateLimitStoreUnavailable("Shared rate-limit store is unavailable.") from exc
    finally:
        db.close()
