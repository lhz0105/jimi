"""按文件名顺序执行 migrations/*.sql，已执行的记入 schema_migrations。"""

from __future__ import annotations

import logging
from pathlib import Path

from app.core.clock import now_ms
from app.db.database import Database

logger = logging.getLogger(__name__)

MIGRATIONS_DIR = Path(__file__).resolve().parent / "migrations"

_BOOTSTRAP = """
CREATE TABLE IF NOT EXISTS schema_migrations (
  version TEXT PRIMARY KEY,
  applied_at INTEGER NOT NULL
);
"""


async def migrate(db: Database, migrations_dir: Path = MIGRATIONS_DIR) -> list[str]:
    await db.executescript(_BOOTSTRAP)
    rows = await db.fetchall("SELECT version FROM schema_migrations")
    applied = {row["version"] for row in rows}

    applied_now: list[str] = []
    for path in sorted(migrations_dir.glob("*.sql")):
        version = path.stem
        if version in applied:
            continue
        script = path.read_text(encoding="utf-8")
        await db.executescript(script)
        await db.execute(
            "INSERT INTO schema_migrations(version, applied_at) VALUES (?, ?)",
            (version, now_ms()),
        )
        applied_now.append(version)
        logger.info("migration applied: %s", version)
    if not applied_now:
        logger.info("no pending migrations")
    return applied_now
