"""SQLSTATE codes raised by the immutability triggers (plan §6.3, migration cd795a034367)."""

from enum import StrEnum


class DbRuleViolation(StrEnum):
    POSTED_JOURNAL_READ_ONLY = "RV001"
    BATCH_NOT_BALANCED = "RV002"
    PERIOD_CLOSED = "RV003"
    POSTED_SCHEDULE_LINE = "RV004"
    APPEND_ONLY = "RV005"
