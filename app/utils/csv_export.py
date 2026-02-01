from __future__ import annotations

import csv
import tempfile
from datetime import datetime

from app.models import Operation


def export_operations_csv(ops: list[Operation]) -> str:
    """Returns path to temporary CSV file."""
    tmp = tempfile.NamedTemporaryFile(mode="w", suffix=".csv", delete=False, encoding="utf-8", newline="")
    path = tmp.name
    tmp.close()

    with open(path, "w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["id", "type", "amount", "category", "comment", "created_at", "created_by"])
        for op in ops:
            cat = op.category.name if op.category else ""
            dt = op.created_at
            if isinstance(dt, datetime):
                dt_str = dt.strftime("%Y-%m-%d %H:%M:%S")
            else:
                dt_str = str(dt)
            writer.writerow([
                op.id,
                op.op_type.value,
                op.amount,
                cat,
                op.comment or "",
                dt_str,
                op.created_by_id,
            ])

    return path
