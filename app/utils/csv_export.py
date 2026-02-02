from __future__ import annotations

import csv
import tempfile
from datetime import datetime
from zoneinfo import ZoneInfo

from app.models import Operation

MSK = ZoneInfo("Europe/Moscow")


def _fmt_dt(dt: datetime) -> str:
    try:
        return dt.astimezone(MSK).strftime("%Y-%m-%d %H:%M:%S")
    except Exception:
        return dt.strftime("%Y-%m-%d %H:%M:%S")


def export_operations_csv(ops: list[Operation]) -> str:
    """Returns path to temporary CSV file (Excel-friendly)."""
    tmp = tempfile.NamedTemporaryFile(
        mode="w", suffix=".csv", delete=False, encoding="utf-8", newline=""
    )
    path = tmp.name
    tmp.close()

    with open(path, "w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(
            [
                "id",
                "type",
                "amount",
                "category",
                "comment",
                "created_at_msk",
                "created_by_id",
                "created_by_name",
            ]
        )
        for op in ops:
            cat = op.category.name if getattr(op, "category", None) else ""
            dt = op.created_at
            dt_str = _fmt_dt(dt) if isinstance(dt, datetime) else str(dt)

            created_by = getattr(op, "created_by", None)
            created_by_name = getattr(created_by, "name", "") or ""
            writer.writerow(
                [
                    op.id,
                    op.op_type.value,
                    op.amount,
                    cat,
                    op.comment or "",
                    dt_str,
                    op.created_by_id,
                    created_by_name,
                ]
            )

    return path
