from flask import Flask, request, jsonify
from flask_cors import CORS
from dotenv import load_dotenv
import os
import logging
from typing import List
from pathlib import Path

# Repo / run location: always load .env from the same directory as this file
BACKEND_DIR = Path(__file__).resolve().parent
load_dotenv(BACKEND_DIR / ".env")
load_dotenv()

# Logging
logging.basicConfig(
    filename=str(BACKEND_DIR / "app.log"),
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

# -----------------------------
# LangChain imports
# -----------------------------
from pypdf import PdfReader
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_huggingface import HuggingFaceEmbeddings
from langchain_qdrant import QdrantVectorStore
from langchain_groq import ChatGroq
from langchain_core.documents import Document
from qdrant_client import QdrantClient

# -----------------------------
# Config
# -----------------------------
_pdf = os.getenv("PDF_FOLDER", "Policy")
PDF_FOLDER = (
    str((BACKEND_DIR / _pdf).resolve())
    if not Path(_pdf).is_absolute()
    else _pdf
)
QDRANT_URL = os.getenv("QDRANT_URL", "http://localhost:6333")
COLLECTION_NAME = os.getenv("COLLECTION_NAME", "rag_collection")

EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL", "BAAI/bge-base-en-v1.5")
LLM_MODEL = os.getenv("LLM_MODEL", "llama-3.1-8b-instant")
LLM_TEMPERATURE = float(os.getenv("LLM_TEMPERATURE", "0.1"))

CHUNK_SIZE = int(os.getenv("CHUNK_SIZE", "700"))
CHUNK_OVERLAP = int(os.getenv("CHUNK_OVERLAP", "100"))
RETRIEVER_K = int(os.getenv("RETRIEVER_K", "5"))

# -----------------------------
# Prompt
# -----------------------------
SYSTEM_PROMPT = """
You are a helpful assistant answering strictly from context.

Rules:
- Use ONLY provided context
- If not found, say "I don't know 🙂"

Context:
{context}

Question:
{question}

Answer:
"""

# -----------------------------
# Load PDFs
# -----------------------------
def load_pdfs(folder: str) -> List[Document]:
    """Load PDFs with pypdf (avoids deprecated langchain_community PyPDFLoader)."""
    docs = []
    path = Path(folder)

    if not path.exists():
        raise FileNotFoundError(f"{folder} not found")

    for pdf_path in path.glob("*.pdf"):
        reader = PdfReader(str(pdf_path))
        for page_num, page in enumerate(reader.pages):
            text = page.extract_text() or ""
            docs.append(
                Document(
                    page_content=text,
                    metadata={"source": str(pdf_path), "page": page_num},
                )
            )

    return docs


# -----------------------------
# Create Qdrant Vectorstore
# -----------------------------
def create_vectorstore(docs, embeddings):
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=CHUNK_SIZE,
        chunk_overlap=CHUNK_OVERLAP
    )

    chunks = splitter.split_documents(docs)

    vectorstore = QdrantVectorStore.from_documents(
        documents=chunks,
        embedding=embeddings,
        url=QDRANT_URL,
        collection_name=COLLECTION_NAME,
        check_compatibility=False,
    )

    return vectorstore


# -----------------------------
# Init RAG system
# -----------------------------
def _raise_if_qdrant_unreachable(exc: BaseException) -> None:
    """Turn low-level transport errors into a clear message."""
    msg = str(exc).lower()
    if "connection refused" in msg or "errno 111" in msg or "failed to establish" in msg:
        raise RuntimeError(
            f"Cannot reach Qdrant at {QDRANT_URL}. Start the server, e.g. "
            "`docker run -p 6333:6333 qdrant/qdrant`"
        ) from exc


def initialize_rag():
    if not os.environ.get("GROQ_API_KEY"):
        raise RuntimeError(
            "GROQ_API_KEY is not set. Create Backend/.env with GROQ_API_KEY=... "
            "(copy from .env.example). Get a key at https://console.groq.com/keys"
        )

    embeddings = HuggingFaceEmbeddings(
        model_name=EMBEDDING_MODEL,
        encode_kwargs={"normalize_embeddings": True}
    )

    try:
        client = QdrantClient(url=QDRANT_URL, check_compatibility=False)
        collection_ready = client.collection_exists(COLLECTION_NAME)
        points_count = 0
        if collection_ready:
            points_count = client.count(collection_name=COLLECTION_NAME, exact=True).count
    except Exception as e:
        _raise_if_qdrant_unreachable(e)
        raise

    if not collection_ready or points_count == 0:
        logger.info(
            "Building Qdrant index (collection exists=%s, points=%s)...",
            collection_ready,
            points_count,
        )
        docs = load_pdfs(PDF_FOLDER)
        vectorstore = create_vectorstore(docs, embeddings)
    else:
        vectorstore = QdrantVectorStore(
            client=client,
            collection_name=COLLECTION_NAME,
            embedding=embeddings,
        )

    retriever = vectorstore.as_retriever(
        search_kwargs={"k": RETRIEVER_K}
    )

    llm = ChatGroq(
        model=LLM_MODEL,
        temperature=LLM_TEMPERATURE
    )

    return retriever, llm


# -----------------------------
# Initialize
# -----------------------------
INIT_ERROR: str | None = None
try:
    retriever, llm = initialize_rag()
except Exception as e:
    INIT_ERROR = str(e)
    logger.exception("Init failed: %s", e)
    retriever, llm = None, None


# -----------------------------
# Flask App
# -----------------------------
app = Flask(__name__)
CORS(app)


@app.route("/health", methods=["GET"])
def health():
    ok = bool(retriever and llm)
    body: dict = {"status": "ok" if ok else "bad"}
    if not ok and INIT_ERROR:
        body["reason"] = INIT_ERROR
    return jsonify(body)


@app.route("/chat", methods=["POST"])
def chat():
    if not retriever or not llm:
        return jsonify({"error": "System not ready"}), 503

    data = request.get_json()
    query = data.get("message", "")

    if not query:
        return jsonify({"error": "Empty message"}), 400

    # Retrieve (LangChain 1.x: use invoke, not get_relevant_documents)
    docs = retriever.invoke(query)

    context = "\n\n".join(
        d.page_content for d in docs
    )

    prompt = SYSTEM_PROMPT.format(
        context=context,
        question=query
    )

    response = llm.invoke(prompt).content

    return jsonify({"answer": response})


# -----------------------------
# Run server
# -----------------------------
if __name__ == "__main__":
    if retriever is None or llm is None:
        err = INIT_ERROR or "(no message — see app.log)"
        print(
            f"\n[DocMind] RAG failed to initialize.\n"
            f"  Reason: {err}\n"
            "\n  Checklist:\n"
            "  • Qdrant on port 6333 — docker run -p 6333:6333 qdrant/qdrant\n"
            "  • Backend/.env — GROQ_API_KEY=... (https://console.groq.com/keys)\n"
            f"  • PDFs — folder exists: {PDF_FOLDER}\n"
            f"  • Full traceback: {BACKEND_DIR / 'app.log'}\n",
            flush=True,
        )
    app.run(host="0.0.0.0", port=8000, debug=True)