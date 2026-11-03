"""
core/exceptions.py
Custom exception hierarchy for portfolio catalog data ingestion.
"""


class CatalogError(Exception):
    """Base exception for all catalog ingestion and processing errors."""
    pass


class FetchError(CatalogError):
    """Raised when an official feed or endpoint cannot be reached or returns an HTTP error."""
    pass


class ParsingError(CatalogError):
    """Raised when an expected data structure or format cannot be parsed."""
    pass


class DatabaseError(CatalogError):
    """Raised when database initialization, migration, or upsert operations fail."""
    pass

