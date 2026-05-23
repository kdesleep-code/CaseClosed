from __future__ import annotations

from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    pass


# Import the initial model set so Alembic can see Base.metadata.
from caseclosed.db import models as models  # noqa: E402,F401
