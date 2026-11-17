"""Queries over records."""

from .models import Record


def find(record_id: int) -> Record:
    """Find a record by id."""
    record = Record()
    record.id = record_id
    return record
