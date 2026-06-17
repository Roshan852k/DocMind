#!/usr/bin/env python3
"""
Create (or optionally recreate) the Qdrant collection used by DocMind.

Uses the same env vars as app.py: QDRANT_URL, COLLECTION_NAME, EMBEDDING_DIM.

Common embedding sizes (set EMBEDDING_DIM if you change EMBEDDING_MODEL):
  BAAI/bge-small-en-v1.5  -> 384
  BAAI/bge-base-en-v1.5   -> 768  (default in app.py)
  BAAI/bge-large-en-v1.5  -> 1024

Usage (from Backend/, with venv active):
  python create_qdrant_collection.py
  python create_qdrant_collection.py --recreate   # delete collection if it exists, then create empty
"""
from __future__ import annotations

import argparse
import os
import sys

from dotenv import load_dotenv
from qdrant_client import QdrantClient
from qdrant_client.http import models

load_dotenv()

QDRANT_URL = os.getenv("QDRANT_URL", "http://localhost:6333")
COLLECTION_NAME = os.getenv("COLLECTION_NAME", "rag_collection")
# Must match the output dimension of your HuggingFace embedding model
EMBEDDING_DIM = int(os.getenv("EMBEDDING_DIM", "768"))


def main() -> int:
    parser = argparse.ArgumentParser(description="Create Qdrant collection for DocMind RAG.")
    parser.add_argument(
        "--recreate",
        action="store_true",
        help="Delete the collection if it exists, then create a new empty one.",
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
            f"Collection {COLLECTION_NAME!r} already exists at {QDRANT_URL} "
            f"(vectors_count={info.points_count}). Nothing to do.",
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
        f"Created collection {COLLECTION_NAME!r} at {QDRANT_URL} "
        f"(vector size={EMBEDDING_DIM}, distance=COSINE).",
        flush=True,
    )
    print(
        "Next: run `python app.py` to index PDFs from PDF_FOLDER into this collection, "
        "or use QdrantVectorStore.from_documents as the app does on first load.",
        flush=True,
    )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:  # noqa: BLE001 — CLI entrypoint
        print(f"Error: {exc}", file=sys.stderr, flush=True)
        raise SystemExit(1) from exc
