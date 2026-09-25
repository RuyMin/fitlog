"""Future import boundary.

CSV/XLSX/Google Sheets adapters should normalize source rows into validated
input schemas, then call the same services as REST endpoints. Keep source
credentials, parsing, deduplication and transaction policies outside ORM models.
Actual importing, authentication and network access are deferred to Phase 5.
"""
