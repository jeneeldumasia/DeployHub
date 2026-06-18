import os
from pathlib import Path

docs_dir = Path("c:/Project/ShipZen/docs")
for md_file in docs_dir.rglob("*.md"):
    if md_file.name == "0002-database-design.md":
        content = """# ADR 0002: Database Design

**Status:** ACCEPTED (Amended)
**Context:** We need a primary database to serve as the Source of Truth for desired state. 
**Decision:** We will use PostgreSQL as the primary relational database and source of truth instead of MongoDB. It offers efficient and fast querying for strictly relational data models and enforces robust schema validation. Build logs will be stored in S3, not PostgreSQL.
**Consequences:** 
- Allows strong schema validation, referential integrity, and ACID compliance.
- Replaces previous MongoDB implementation.
**Conflict Resolution Policy:** Any implementations using MongoDB or NoSQL for core state will be rejected.
"""
        md_file.write_text(content, encoding='utf-8')
    else:
        content = md_file.read_text(encoding='utf-8')
        new_content = content.replace("MongoDB", "PostgreSQL").replace("Mongo", "Postgres")
        if new_content != content:
            md_file.write_text(new_content, encoding='utf-8')

print("Docs updated for PostgreSQL")
