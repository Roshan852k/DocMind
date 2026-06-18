#!/usr/bin/env python3
"""Create or --recreate Qdrant collection (env: QDRANT_URL, COLLECTION_NAME, EMBEDDING_DIM default 768)."""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from dotenv import load_dotenv
from qdrant_client import QdrantClient
from qdrant_client.http import models

BACKEND_DIR = Path(__file__).resolve().parent
load_dotenv(BACKEND_DIR / ".env")
load_dotenv()

QDRANT_URL = os.getenv("QDRANT_URL", "http://localhost:6333")
COLLECTION_NAME = os.getenv("COLLECTION_NAME", "rag_collection")
EMBEDDING_DIM = int(os.getenv("EMBEDDING_DIM", "768"))


def main() -> int:
    parser = argparse.ArgumentParser(description="Create Qdrant collection for DocMind.")
    parser.add_argument(
        "--recreate",
        action="store_true",
        help="Delete existing collection first.",
    )
    args = parser.parse_args()

    client = QdrantClient(url=QDRANT_URL, check_compatibility=False)
    exists = client.collection_exists(COLLECTION_NAME)
    if exists and args.recreate:
        client.delete_collection(COLLECTION_NAME)
        print(f"Deleted collection {COLLECTION_NAME!r}.", flush=True)
        exists = False

    if exists:
        info = client.get_collection(COLLECTION_NAME)
        print(
            f"Collection {COLLECTION_NAME!r} at {QDRANT_URL} "
            f"(points={info.points_count}). Nothing to do.",
            flush=True,
        )
        return 0

    client.create_collection(
        collection_name=COLLECTION_NAME,
        vectors_config=models.VectorParams(
            size=EMBEDDING_DIM,
            distance=models.Distance.COSINE,
        ),
    )
    print(
        f"Created {COLLECTION_NAME!r} at {QDRANT_URL} (dim={EMBEDDING_DIM}, COSINE).",
        flush=True,
    )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr, flush=True)
        raise SystemExit(1) from exc
