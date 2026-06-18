#!/usr/bin/env python3
"""List Qdrant collections (reads Backend/.env for QDRANT_URL, QDRANT_API_KEY)."""
from __future__ import annotations

import os
import sys
from pathlib import Path

from dotenv import load_dotenv
from qdrant_client import QdrantClient

BACKEND_DIR = Path(__file__).resolve().parent
load_dotenv(BACKEND_DIR / ".env")
load_dotenv()

QDRANT_URL = os.getenv("QDRANT_URL", "http://localhost:6333")
QDRANT_API_KEY = os.getenv("QDRANT_API_KEY") or None
APP_COLLECTION = os.getenv("COLLECTION_NAME", "rag_collection")


def main() -> int:
    kwargs: dict = {"url": QDRANT_URL, "check_compatibility": False}
    if QDRANT_API_KEY:
        kwargs["api_key"] = QDRANT_API_KEY

    print(f"Connecting to: {QDRANT_URL}", flush=True)

    try:
        client = QdrantClient(**kwargs)
        cols = client.get_collections().collections
    except Exception as e:
        print(f"ERROR: {e}", file=sys.stderr, flush=True)
        return 1

    if not cols:
        print(
            f"\nNo collections. Start Qdrant, run `python app.py` from Backend/, "
            f"then expect {APP_COLLECTION!r}. Dashboard: http://localhost:6333/dashboard\n",
            flush=True,
        )
        return 0

    print(f"\n{len(cols)} collection(s):\n", flush=True)
    for c in cols:
        try:
            n = client.count(collection_name=c.name, exact=True).count
        except Exception:
            n = "?"
        mark = "  <-- COLLECTION_NAME" if c.name == APP_COLLECTION else ""
        print(f"  • {c.name!r}  (points: {n}){mark}", flush=True)

    if not any(c.name == APP_COLLECTION for c in cols):
        print(f"\nNote: app uses COLLECTION_NAME={APP_COLLECTION!r}.\n", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
