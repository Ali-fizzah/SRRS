"""Declarative base for all SQLAlchemy models (tables are added in P1-T1)."""

from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    pass
