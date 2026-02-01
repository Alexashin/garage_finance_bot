from __future__ import annotations

import glob
import os
import subprocess
import sys
import time

from sqlalchemy import create_engine, text

from app.settings import Settings


def _run(cmd: list[str]) -> None:
    print(" ".join(cmd), flush=True)
    subprocess.check_call(cmd)


def wait_for_db(settings: Settings, timeout_sec: int = 60) -> None:
    url = settings.database_url_sync
    start = time.time()
    while True:
        try:
            engine = create_engine(url, pool_pre_ping=True)
            with engine.connect() as conn:
                conn.execute(text("SELECT 1"))
            return
        except Exception as e:
            if time.time() - start > timeout_sec:
                raise RuntimeError(f"DB not ready after {timeout_sec}s: {e}") from e
            time.sleep(1)


def ensure_migrations_exist() -> None:
    versions = glob.glob("alembic/versions/*.py")
    versions = [p for p in versions if not p.endswith("__init__.py")]
    if versions:
        return

    # Нет миграций — создаём init
    _run([sys.executable, "-m", "alembic", "revision", "--autogenerate", "-m", "init"])


def upgrade_head() -> None:
    _run([sys.executable, "-m", "alembic", "upgrade", "head"])


def main() -> None:
    settings = Settings()
    wait_for_db(settings)
    ensure_migrations_exist()
    upgrade_head()


if __name__ == "__main__":
    main()
