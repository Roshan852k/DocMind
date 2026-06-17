// import { useEffect, useState } from "react";
// import "./App.css";

// function App() {
//   const [messages, setMessages] = useState([]);
//   const [input, setInput] = useState("");
//   const [loading, setLoading] = useState(false);

//   // 👋 NEW: initial greeting
//   useEffect(() => {
//     setMessages([
//       {
//         role: "assistant",
//         content: "Hi 👋 How may I help you today?"
//       }
//     ]);
//   }, []);

//   const sendMessage = async () => {
//     if (!input.trim()) return;

//     const userMessage = { role: "user", content: input };
//     setMessages(prev => [...prev, userMessage]);
//     setInput("");
//     setLoading(true);

//     const res = await fetch("http://127.0.0.1:8000/chat", {
//       method: "POST",
//       headers: { "Content-Type": "application/json" },
//       body: JSON.stringify({ message: input })
//     });

//     const data = await res.json();
//     let answer = data.answer;

//     if (answer.toLowerCase().includes("i don't know")) {
//       answer = "I couldn’t find that information in the document. Try asking something else🙂 ";
//     }


//     const botMessage = { role: "assistant", content: answer };
//     setMessages(prev => [...prev, botMessage]);
//     setLoading(false);
//   };

//   return (
//     <div className="app">
//       <h2>📄Chatbot</h2>

//       <div className="chat-box">
//         {messages.map((msg, i) => (
//           <div key={i} className={`msg ${msg.role}`}>
//             {msg.content}
//           </div>
//         ))}
//         {loading && <div className="msg assistant">Typing...</div>}
//       </div>

//       <div className="input-box">
//         <input
//           value={input}
//           onChange={e => setInput(e.target.value)}
//           placeholder="Type your question..."
//           onKeyDown={e => e.key === "Enter" && sendMessage()}
//         />
//         <button onClick={sendMessage}>Send</button>
//       </div>
//     </div>
//   );
// }

// export default App;

// ###############################################################

// import { useEffect, useState } from "react";
// import "./App.css";

// const SpeechRecognition =
//   window.SpeechRecognition || window.webkitSpeechRecognition;

// function App() {
//   const [messages, setMessages] = useState([]);
//   const [input, setInput] = useState("");
//   const [loading, setLoading] = useState(false);
//   const [listening, setListening] = useState(false);

//   // Initial greeting
//   useEffect(() => {
//     setMessages([
//       {
//         role: "assistant",
//         content: "Hi 👋 How may I help you today?"
//       }
//     ]);
//   }, []);

//   const sendMessage = async () => {
//     if (!input.trim()) return;

//     const userMessage = { role: "user", content: input };
//     setMessages(prev => [...prev, userMessage]);
//     setInput("");
//     setLoading(true);

//     try {
//       const res = await fetch("http://127.0.0.1:8000/chat", {
//         method: "POST",
//         headers: { "Content-Type": "application/json" },
//         body: JSON.stringify({ message: userMessage.content })
//       });

//       const data = await res.json();
//       let answer = data.answer;

//       if (answer.toLowerCase().includes("i don't know")) {
//         answer =
//           "I couldn’t find that information in the document. Try asking something else 🙂";
//       }

//       const botMessage = { role: "assistant", content: answer };
//       setMessages(prev => [...prev, botMessage]);
//     } catch (err) {
//       setMessages(prev => [
//         ...prev,
//         { role: "assistant", content: "⚠️ Server error. Try again." }
//       ]);
//     }

//     setLoading(false);
//   };

//   // 🎤 Voice → Text (does NOT auto-send)
//   const startVoiceInput = () => {
//     if (!SpeechRecognition) {
//       alert("Voice input not supported in this browser");
//       return;
//     }

//     const recognition = new SpeechRecognition();
//     recognition.lang = "en-US";
//     recognition.continuous = false;
//     recognition.interimResults = false;

//     setListening(true);
//     recognition.start();

//     recognition.onresult = (event) => {
//       const voiceText = event.results[0][0].transcript;
//       setInput(prev => (prev ? prev + " " + voiceText : voiceText));
//       setListening(false);
//     };

//     recognition.onerror = () => {
//       setListening(false);
//     };

//     recognition.onend = () => {
//       setListening(false);
//     };
//   };

//   return (
//     <div className="app">
//       <h2>📄 Chatbot</h2>

//       <div className="chat-box">
//         {messages.map((msg, i) => (
//           <div key={i} className={`msg ${msg.role}`}>
//             {msg.content}
//           </div>
//         ))}

//         {loading && <div className="msg assistant">Typing...</div>}
//       </div>

//       <div className="input-box">
//         <input
//           value={input}
//           onChange={e => setInput(e.target.value)}
//           placeholder="Type or speak your question..."
//           onKeyDown={e => e.key === "Enter" && sendMessage()}
//         />

//         <button onClick={sendMessage}>Send</button>

//         <button onClick={startVoiceInput}>
//           {listening ? "🎙️ Listening..." : "🎤"}
//         </button>
//       </div>
//     </div>
//   );
// }

// export default App;

// ###############################################################

import { useEffect, useState, useRef } from "react";
import "./App.css";

const SpeechRecognition =
  window.SpeechRecognition || window.webkitSpeechRecognition;

/** Same hostname as the UI (avoids localhost vs 127.0.0.1 mismatch). Override with REACT_APP_API_BASE. */
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

  // Holds voice text safely for auto-send
  const voiceTextRef = useRef("");

  // Initial greeting
  useEffect(() => {
    setMessages([
      {
        role: "assistant",
        content: "Hi Roshan👋, What can I help you with today?"
      }
    ]);
  }, []);

  // Send message (text OR voice)
  const sendMessage = async (text = input) => {
    if (!text.trim()) return;

    const userMessage = { role: "user", content: text };
    setMessages(prev => [...prev, userMessage]);
    setInput("");
    setLoading(true);

    try {
      const res = await fetch(`${getApiBase()}/chat`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ message: text })
      });

      const data = await res.json().catch(() => ({}));
      const raw =
        typeof data.answer === "string" ? data.answer : null;

      if (!res.ok || raw == null) {
        const detail =
          typeof data.error === "string"
            ? data.error
            : `Request failed (${res.status}).`;
        setMessages(prev => [
          ...prev,
          {
            role: "assistant",
            content: `⚠️ ${detail} Start the Flask API on port 8000 (see Backend/app.py) and check app.log if it persists.`
          }
        ]);
        return;
      }

      let answer = raw;
      if (answer.toLowerCase().includes("i don't know")) {
        answer =
          "I couldn’t find that information in the document. Try asking something else 🙂";
      }

      const botMessage = { role: "assistant", content: answer };
      setMessages(prev => [...prev, botMessage]);
    } catch (err) {
      setMessages(prev => [
        ...prev,
        {
          role: "assistant",
          content:
            "⚠️ Could not reach the chat API. Run the Flask backend on port 8000, or set REACT_APP_API_BASE to your API URL."
        }
      ]);
    }

    setLoading(false);
  };

  // 🎤 Voice → auto-send
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
        sendMessage(voiceTextRef.current); // auto send
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
          onChange={e => setInput(e.target.value)}
          placeholder="Type or speak your question..."
          onKeyDown={e => e.key === "Enter" && sendMessage()}
        />

        <button onClick={() => sendMessage()}>Send</button>

        <button onClick={startVoiceInput}>
          {listening ? "🎙️ Listening..." : "🎤"}
        </button>
      </div>
    </div>
  );
}

export default App;
