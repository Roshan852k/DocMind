import { useEffect, useState, useRef } from "react";
import "./App.css";

const SpeechRecognition =
  window.SpeechRecognition || window.webkitSpeechRecognition;

function getApiBase() {
  const fromEnv = process.env.REACT_APP_API_BASE;
  if (fromEnv && typeof fromEnv === "string") {
    return fromEnv.replace(/\/$/, "");
  }
  const host = window.location.hostname || "localhost";
  return `http://${host}:8000`;
}

function App() {
  const [messages, setMessages] = useState([]);
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  const [listening, setListening] = useState(false);
  const voiceTextRef = useRef("");
  const [liveMode, setLiveMode] = useState(false);
  const [liveSessionId, setLiveSessionId] = useState(null);
  const [liveDocName, setLiveDocName] = useState("");
  const [uploadBusy, setUploadBusy] = useState(false);
  const fileInputRef = useRef(null);

  useEffect(() => {
    setMessages([
      {
        role: "assistant",
        content: "Hi Roshan👋, What can I help you with today?",
      },
    ]);
  }, []);

  const clearLiveSessionOnServer = async (sessionId) => {
    if (!sessionId) return;
    try {
      await fetch(`${getApiBase()}/live/session/${encodeURIComponent(sessionId)}`, {
        method: "DELETE",
      });
    } catch {
      /* non-fatal */
    }
  };

  const handleLiveModeChange = async (nextOn) => {
    if (!nextOn) {
      const sid = liveSessionId;
      setLiveMode(false);
      setLiveDocName("");
      setLiveSessionId(null);
      await clearLiveSessionOnServer(sid);
      setMessages((prev) => [
        ...prev,
        {
          role: "assistant",
          content:
            "Live document mode is off. Questions will use the main document library again.",
        },
      ]);
      return;
    }
    setLiveMode(true);
    setMessages((prev) => [
      ...prev,
      {
        role: "assistant",
        content:
          "Live document mode is on. Upload a PDF below, then ask questions — answers will use only that file.",
      },
    ]);
  };

  const onPickPdf = () => fileInputRef.current?.click();

  const onLivePdfSelected = async (event) => {
    const file = event.target.files?.[0];
    event.target.value = "";
    if (!file || !liveMode) return;
    if (file.type && file.type !== "application/pdf") {
      window.alert("Please choose a PDF file.");
      return;
    }
    setUploadBusy(true);
    try {
      if (liveSessionId) {
        await clearLiveSessionOnServer(liveSessionId);
        setLiveSessionId(null);
        setLiveDocName("");
      }
      const form = new FormData();
      form.append("file", file, file.name);
      const res = await fetch(`${getApiBase()}/live/upload`, {
        method: "POST",
        body: form,
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) {
        const msg =
          typeof data.error === "string"
            ? data.error
            : res.status === 413
              ? "File too large for the server limit."
              : `Upload failed (${res.status}).`;
        window.alert(msg);
        return;
      }
      if (typeof data.session_id !== "string") {
        window.alert("Unexpected response from server.");
        return;
      }
      setLiveSessionId(data.session_id);
      setLiveDocName(typeof data.filename === "string" ? data.filename : file.name);
      setMessages((prev) => [
        ...prev,
        {
          role: "assistant",
          content: `Ready — I indexed "${typeof data.filename === "string" ? data.filename : file.name}". Ask a question about this document.`,
        },
      ]);
    } catch {
      window.alert("Could not reach the server to upload the PDF.");
    } finally {
      setUploadBusy(false);
    }
  };

  const sendMessage = async (text = input) => {
    if (!text.trim()) return;

    if (liveMode && !liveSessionId) {
      setMessages((prev) => [
        ...prev,
        {
          role: "assistant",
          content:
            "Turn on live mode is not enough yet — please upload a PDF first using the button below.",
        },
      ]);
      return;
    }

    const userMessage = { role: "user", content: text };
    const historyPayload = messages
      .filter((m) => m.role === "user" || m.role === "assistant")
      .map(({ role, content }) => ({ role, content }));

    setMessages((prev) => [...prev, userMessage]);
    setInput("");
    setLoading(true);

    try {
      const payload = { message: text, history: historyPayload };
      if (liveMode && liveSessionId) {
        payload.live_session_id = liveSessionId;
      }
      const res = await fetch(`${getApiBase()}/chat`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });

      const data = await res.json().catch(() => ({}));
      const raw = typeof data.answer === "string" ? data.answer : null;

      if (!res.ok || raw == null) {
        const detail =
          typeof data.error === "string"
            ? data.error
            : `Request failed (${res.status}).`;
        setMessages((prev) => [
          ...prev,
          {
            role: "assistant",
            content: `⚠️ ${detail} Start the Flask API on port 8000 (see Backend/app.py) and check app.log if it persists.`,
          },
        ]);
        return;
      }

      let answer = raw;
      if (answer.toLowerCase().includes("i don't know")) {
        answer =
          "I couldn’t find that information in the document. Try asking something else 🙂";
      }

      setMessages((prev) => [...prev, { role: "assistant", content: answer }]);
    } catch {
      setMessages((prev) => [
        ...prev,
        {
          role: "assistant",
          content:
            "⚠️ Could not reach the chat API. Run the Flask backend on port 8000, or set REACT_APP_API_BASE to your API URL.",
        },
      ]);
    }

    setLoading(false);
  };

  const startVoiceInput = () => {
    if (!SpeechRecognition) {
      alert("Voice input not supported in this browser");
      return;
    }

    const recognition = new SpeechRecognition();
    recognition.lang = "en-US";
    recognition.continuous = false;
    recognition.interimResults = false;

    setListening(true);
    recognition.start();

    recognition.onresult = (event) => {
      const voiceText = event.results[0][0].transcript;
      voiceTextRef.current = voiceText;
      setInput(voiceText);
    };

    recognition.onend = () => {
      setListening(false);
      if (voiceTextRef.current.trim()) {
        sendMessage(voiceTextRef.current);
        voiceTextRef.current = "";
      }
    };

    recognition.onerror = () => {
      setListening(false);
      voiceTextRef.current = "";
    };
  };

  return (
    <div className="app">
      <h2 className="chat-title">
        <img src="chat-bot.png" alt="" className="title-icon" />
        Chatbot
      </h2>

      <div className="live-panel" role="region" aria-label="Live document mode">
        <div className="live-toggle-row">
          <label className="live-switch">
            <input
              type="checkbox"
              checked={liveMode}
              onChange={(e) => handleLiveModeChange(e.target.checked)}
            />
            <span className="live-switch-slider" aria-hidden="true" />
            <span className="live-switch-label">Live document Q&amp;A</span>
          </label>
        </div>
        {liveMode && (
          <div className="live-upload-row">
            <input
              ref={fileInputRef}
              type="file"
              accept="application/pdf,.pdf"
              className="live-file-input"
              onChange={onLivePdfSelected}
              aria-label="Upload PDF for live Q and A"
            />
            <button
              type="button"
              className="live-upload-btn"
              onClick={onPickPdf}
              disabled={uploadBusy}
            >
              {uploadBusy ? "Uploading…" : "Upload PDF"}
            </button>
            {liveSessionId && liveDocName && (
              <span className="live-doc-badge" title={liveSessionId}>
                Active: {liveDocName}
              </span>
            )}
          </div>
        )}
      </div>

      <div className="chat-box">
        {messages.map((msg, i) => (
          <div key={i} className={`msg ${msg.role}`}>
            {msg.content}
          </div>
        ))}
        {loading && <div className="msg assistant">Typing...</div>}
      </div>

      <div className="input-box">
        <input
          value={input}
          onChange={(e) => setInput(e.target.value)}
          placeholder={
            liveMode && !liveSessionId
              ? "Upload a PDF above, then ask…"
              : "Type or speak your question..."
          }
          onKeyDown={(e) => e.key === "Enter" && sendMessage()}
          disabled={liveMode && !liveSessionId}
        />
        <button
          type="button"
          onClick={() => sendMessage()}
          disabled={liveMode && !liveSessionId}
        >
          Send
        </button>
        <button type="button" onClick={startVoiceInput}>
          {listening ? "🎙️ Listening..." : "🎤"}
        </button>
      </div>
    </div>
  );
}

export default App;
