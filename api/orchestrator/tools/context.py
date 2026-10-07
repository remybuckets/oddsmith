from dataclasses import dataclass
from datetime import datetime

import asyncpg


@dataclass(frozen=True)
class ToolContext:
    """What every tool needs: a database connection and the time staleness is measured from."""

    conn: asyncpg.Connection
    now: datetime
