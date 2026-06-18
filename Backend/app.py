import io
import logging
import os
import shutil
import uuid
from pathlib import Path
from typing import List

from dotenv import load_dotenv
from flask import Flask, request, jsonify
from flask_cors import CORS
from langchain_core.documents import Document
from langchain_groq import ChatGroq
from langchain_huggingface import HuggingFaceEmbeddings
from langchain_qdrant import QdrantVectorStore
from langchain_text_splitters import RecursiveCharacterTextSplitter
from pypdf import PdfReader
from qdrant_client import QdrantClient, models as qmodels
from werkzeug.utils import secure_filename

BACKEND_DIR = Path(__file__).resolve().parent
load_dotenv(BACKEND_DIR / ".env")
load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[
        logging.FileHandler(BACKEND_DIR / "app.log"),
        logging.StreamHandler(),
    ],
    force=True,
)
logger = logging.getLogger(__name__)

USER_FILES_DIR = (BACKEND_DIR / "User_Files").resolve()

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
CHAT_HISTORY_MAX_MESSAGES = int(os.getenv("CHAT_HISTORY_MAX_MESSAGES", "24"))
_HISTORY_MSG_MAX_CHARS = 8000
LIVE_UPLOAD_MAX_BYTES = int(os.getenv("LIVE_UPLOAD_MAX_BYTES", str(15 * 1024 * 1024)))
LIVE_SESSION_META_KEY = "live_session_id"
# Qdrant payload nests LangChain document metadata under "metadata" (see langchain_qdrant).
LIVE_SESSION_FILTER_KEY = f"metadata.{LIVE_SESSION_META_KEY}"

SYSTEM_PROMPT = """You are a policy / document Q&A assistant. Answer using ONLY the document context block below.

Hard rules (violations are failures):
- Treat the Context block as the only source of facts. Do NOT use general knowledge, training data, or "typical company policy" unless those exact ideas appear in the Context.
- Prior conversation lists earlier user questions only (for follow-ups like "brief it more"). Never treat it as facts.
- If the answer is not in the Context, say exactly: I don't know 🙂 — and do not fill in with unrelated compliance or ethics stories.
- If the user uses different words than the document (e.g. "paid leave" vs "Privilege Leave"), you may map once to the term used in the Context, then answer only from the Context.
- Stay on the subject of the Current question as it relates to the Context. Do not pivot to insider trading, media, or competitors unless the Context explicitly covers that.

Context:
{context}

Prior conversation (user questions only — for follow-up clarity; not a factual source):
{chat_history}

Current question:
{question}

Answer:
- If the user asked for a brief, summary, or shorter answer: be concise and structured (bullet points OK).
- Otherwise: clear, professional, step-by-step when the Context lists procedures.
- Do not mention page numbers or document structure.
"""


def _documents_from_pdf_reader(reader: PdfReader, source_label: str) -> List[Document]:
    docs: List[Document] = []
    for page_num, page in enumerate(reader.pages):
        text = page.extract_text() or ""
        docs.append(
            Document(
                page_content=text,
                metadata={"source": source_label, "page": page_num},
            )
        )
    return docs


def load_pdfs(folder: str) -> List[Document]:
    docs: List[Document] = []
    path = Path(folder)
    if not path.exists():
        raise FileNotFoundError(f"{folder} not found")
    for pdf_path in path.glob("*.pdf"):
        reader = PdfReader(str(pdf_path))
        docs.extend(_documents_from_pdf_reader(reader, str(pdf_path)))
    return docs


def _is_pdf_magic(data: bytes) -> bool:
    if len(data) < 4:
        return False
    return data[:4] == b"%PDF"


def _parse_live_session_id(raw: object) -> str | None:
    if raw is None:
        return None
    if not isinstance(raw, str):
        return None
    s = raw.strip()
    if not s:
        return None
    try:
        uuid.UUID(s)
    except ValueError:
        return None
    return s


def _live_session_filter(session_id: str) -> qmodels.Filter:
    return qmodels.Filter(
        must=[
            qmodels.FieldCondition(
                key=LIVE_SESSION_FILTER_KEY,
                match=qmodels.MatchValue(value=session_id),
            )
        ]
    )


def _live_session_user_dir(session_id: str) -> Path:
    """Directory on disk for one live-upload session (session_id is a validated UUID)."""
    return (USER_FILES_DIR / session_id).resolve()


def _remove_live_session_user_dir(session_id: str) -> None:
    d = _live_session_user_dir(session_id)
    if not d.is_dir():
        return
    try:
        d.relative_to(USER_FILES_DIR)
    except ValueError:
        logger.warning("Refusing to remove path outside User_Files: %s", d)
        return
    shutil.rmtree(d, ignore_errors=True)


def _sanitize_history(raw: object) -> list[dict[str, str]]:
    if not isinstance(raw, list):
        return []
    out: list[dict[str, str]] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        role = item.get("role")
        content = item.get("content")
        if role not in ("user", "assistant") or not isinstance(content, str):
            continue
        text = content.strip()
        if not text:
            continue
        if role == "assistant" and text.startswith("⚠"):
            continue
        if len(text) > _HISTORY_MSG_MAX_CHARS:
            text = text[:_HISTORY_MSG_MAX_CHARS] + "…"
        out.append({"role": role, "content": text})
    return out[-CHAT_HISTORY_MAX_MESSAGES:]


def _format_chat_history(messages: list[dict[str, str]]) -> str:
    if not messages:
        return "(None — first question in this conversation.)"
    lines = []
    for m in messages:
        if m["role"] != "user":
            continue
        lines.append(f"User: {m['content']}")
    if not lines:
        return "(None — first question in this conversation.)"
    return "\n".join(lines)


def _retrieval_query(question: str, history: list[dict[str, str]]) -> str:
    q = question.strip()
    prev_user = ""
    for m in reversed(history):
        if m.get("role") == "user":
            prev_user = (m.get("content") or "").strip()
            break
    if not prev_user or prev_user == q:
        return q
    tail = prev_user[:1500] if len(prev_user) > 1500 else prev_user
    return f"{q}\n\n(Earlier question in this conversation: {tail})"


def create_vectorstore(docs, embeddings):
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=CHUNK_SIZE,
        chunk_overlap=CHUNK_OVERLAP,
    )
    chunks = splitter.split_documents(docs)
    return QdrantVectorStore.from_documents(
        documents=chunks,
        embedding=embeddings,
        url=QDRANT_URL,
        collection_name=COLLECTION_NAME,
        check_compatibility=False,
    )


def build_embeddings() -> HuggingFaceEmbeddings:
    logger.info(
        "Embeddings: HuggingFace model=%r normalize_embeddings=True",
        EMBEDDING_MODEL,
    )
    return HuggingFaceEmbeddings(
        model_name=EMBEDDING_MODEL,
        encode_kwargs={"normalize_embeddings": True},
    )


def _raise_if_qdrant_unreachable(exc: BaseException) -> None:
    msg = str(exc).lower()
    if "connection refused" in msg or "errno 111" in msg or "failed to establish" in msg:
        raise RuntimeError(
            f"Cannot reach Qdrant at {QDRANT_URL}. Start the server, e.g. "
            "`docker run -p 6333:6333 qdrant/qdrant`"
        ) from exc


def initialize_rag():
    embeddings = build_embeddings()
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
        logger.info(
            "Qdrant index already present — skipping build (collection=%r url=%s points=%s).",
            COLLECTION_NAME,
            QDRANT_URL,
            points_count,
        )
        vectorstore = QdrantVectorStore(
            client=client,
            collection_name=COLLECTION_NAME,
            embedding=embeddings,
        )

    retriever = vectorstore.as_retriever(search_kwargs={"k": RETRIEVER_K})
    llm = None
    if os.environ.get("GROQ_API_KEY"):
        llm = ChatGroq(model=LLM_MODEL, temperature=LLM_TEMPERATURE)
    else:
        logger.warning(
            "GROQ_API_KEY not set — /chat disabled until set in Backend/.env."
        )
    return vectorstore, retriever, llm


INIT_ERROR: str | None = None
vectorstore: QdrantVectorStore | None = None
try:
    vectorstore, retriever, llm = initialize_rag()
except Exception as e:
    INIT_ERROR = str(e)
    logger.exception("Init failed: %s", e)
    vectorstore, retriever, llm = None, None, None

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = max(20 * 1024 * 1024, LIVE_UPLOAD_MAX_BYTES + 1024 * 1024)
CORS(app)


@app.route("/health", methods=["GET"])
def health():
    ok = bool(retriever and llm)
    body: dict = {
        "status": "ok" if ok else "bad",
        "vector_index": "ready" if retriever else "missing",
        "live_upload": "ready" if vectorstore else "missing",
        "llm": "ready" if llm else "missing",
    }
    if not ok and INIT_ERROR:
        body["reason"] = INIT_ERROR
    if retriever and not llm:
        body["hint"] = "Set GROQ_API_KEY in Backend/.env to enable /chat."
    return jsonify(body)


@app.route("/live/upload", methods=["POST"])
def live_upload():
    """Accept a user PDF, chunk + embed into Qdrant tagged with a session id (live Q&A only)."""
    if not vectorstore:
        return jsonify(
            {"error": "Vector index not ready", "reason": INIT_ERROR or "unknown"}
        ), 503

    if "file" not in request.files:
        return jsonify({"error": "Missing file field (multipart form key: file)"}), 400
    upload = request.files["file"]
    if not upload or upload.filename == "":
        return jsonify({"error": "No file selected"}), 400

    raw = upload.read()
    if len(raw) > LIVE_UPLOAD_MAX_BYTES:
        return jsonify(
            {
                "error": "File too large",
                "max_bytes": LIVE_UPLOAD_MAX_BYTES,
            }
        ), 400
    if not _is_pdf_magic(raw):
        return jsonify({"error": "Not a PDF (invalid file signature)"}), 400

    safe_name = secure_filename(upload.filename) or "document.pdf"
    try:
        reader = PdfReader(io.BytesIO(raw))
        base_docs = _documents_from_pdf_reader(reader, safe_name)
    except Exception as e:
        logger.warning("PDF parse failed: %s", e)
        return jsonify({"error": "Could not read PDF"}), 400

    if not base_docs:
        return jsonify({"error": "PDF has no pages"}), 400
    if not any((d.page_content or "").strip() for d in base_docs):
        return jsonify(
            {"error": "No extractable text in this PDF (it may be scanned images only)."}
        ), 400

    session_id = str(uuid.uuid4())
    session_dir = _live_session_user_dir(session_id)
    session_dir.mkdir(parents=True, exist_ok=True)
    stored_rel = Path("User_Files") / session_id / safe_name
    disk_path = session_dir / safe_name
    try:
        disk_path.write_bytes(raw)
    except OSError as e:
        logger.warning("Could not write user PDF to disk: %s", e)
        _remove_live_session_user_dir(session_id)
        return jsonify({"error": "Could not save PDF on server"}), 500

    for d in base_docs:
        d.metadata[LIVE_SESSION_META_KEY] = session_id

    splitter = RecursiveCharacterTextSplitter(
        chunk_size=CHUNK_SIZE,
        chunk_overlap=CHUNK_OVERLAP,
    )
    chunks = splitter.split_documents(base_docs)
    point_ids = [str(uuid.uuid4()) for _ in chunks]
    try:
        vectorstore.add_documents(documents=chunks, ids=point_ids)
    except Exception as e:
        logger.exception("Live upload indexing failed: %s", e)
        _remove_live_session_user_dir(session_id)
        return jsonify({"error": "Failed to index PDF", "detail": str(e)}), 500

    logger.info(
        "Live PDF indexed session_id=%s file=%s chunks=%s stored=%s",
        session_id,
        safe_name,
        len(chunks),
        disk_path,
    )
    return jsonify(
        {
            "session_id": session_id,
            "filename": safe_name,
            "chunks": len(chunks),
            "stored_path": str(stored_rel).replace("\\", "/"),
        }
    )


@app.route("/live/session/<session_id>", methods=["DELETE"])
def live_session_delete(session_id: str):
    if not vectorstore:
        return jsonify(
            {"error": "Vector index not ready", "reason": INIT_ERROR or "unknown"}
        ), 503
    sid = _parse_live_session_id(session_id)
    if not sid:
        return jsonify({"error": "Invalid session id"}), 400

    try:
        vectorstore.client.delete(
            collection_name=COLLECTION_NAME,
            points_selector=qmodels.FilterSelector(filter=_live_session_filter(sid)),
        )
    except Exception as e:
        logger.exception("Live session delete failed: %s", e)
        return jsonify({"error": "Delete failed", "detail": str(e)}), 500

    _remove_live_session_user_dir(sid)
    logger.info("Live session vectors and User_Files folder removed session_id=%s", sid)
    return jsonify({"ok": True})


@app.route("/chat", methods=["POST"])
def chat():
    if not retriever:
        return jsonify(
            {"error": "Vector index not ready", "reason": INIT_ERROR or "unknown"}
        ), 503
    if not llm:
        return jsonify(
            {
                "error": "LLM not configured",
                "detail": "Set GROQ_API_KEY in Backend/.env then restart the server.",
            }
        ), 503

    data = request.get_json(silent=True) or {}
    query = (data.get("message") or "").strip()
    if not query:
        return jsonify({"error": "Empty message"}), 400

    live_sid = _parse_live_session_id(data.get("live_session_id"))
    if data.get("live_session_id") and live_sid is None:
        return jsonify({"error": "Invalid live_session_id (expected UUID)"}), 400

    history = _sanitize_history(data.get("history"))
    retrieval_query = _retrieval_query(query, history)

    if live_sid:
        if not vectorstore:
            return jsonify({"error": "Vector index not ready"}), 503
        scoped = vectorstore.as_retriever(
            search_kwargs={
                "k": RETRIEVER_K,
                "filter": _live_session_filter(live_sid),
            }
        )
        docs = scoped.invoke(retrieval_query)
    else:
        docs = retriever.invoke(retrieval_query)
    context = "\n\n".join(d.page_content for d in docs)
    chat_history = _format_chat_history(history)
    prompt = SYSTEM_PROMPT.format(
        context=context,
        chat_history=chat_history,
        question=query,
    )
    response = llm.invoke(prompt).content
    return jsonify({"answer": response})


if __name__ == "__main__":
    if retriever is None:
        err = INIT_ERROR or "(no message — see app.log)"
        print(
            f"\n[DocMind] Vector index failed to initialize.\n  Reason: {err}\n"
            "\n  • Qdrant: docker run -p 6333:6333 qdrant/qdrant\n"
            f"  • PDFs: {PDF_FOLDER}\n"
            f"  • Log: {BACKEND_DIR / 'app.log'}\n",
            flush=True,
        )
    elif llm is None:
        print(
            "\n[DocMind] Index ready; /chat needs GROQ_API_KEY in Backend/.env\n",
            flush=True,
        )
    app.run(host="0.0.0.0", port=8000, debug=True)
