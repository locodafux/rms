import { useEffect, useRef, useState } from "react";
import { api } from "./api";
import { useAuth } from "./auth";
import type { ChatMessage, OnlineUser } from "./types";

function ago(iso: string) {
  const secs = Math.max(0, (Date.now() - new Date(iso).getTime()) / 1000);
  if (secs < 90) return "just now";
  return `${Math.round(secs / 60)} min ago`;
}

function clock(iso: string) {
  return new Date(iso).toLocaleTimeString([], { hour: "numeric", minute: "2-digit" });
}

/** Shared team room, floating bottom-right. Presence lives in the header here —
 *  it's last-activity, not a real session (auth is stateless JWT), so someone who
 *  closes the tab lingers until the server-side 5 min window lapses.
 *
 *  ponytail: polling, not a socket. Every other live thing in this app polls, and
 *  the ?after= cursor makes an idle poll an empty array. Swap for a WebSocket
 *  (uvicorn[standard] already ships one) if the team outgrows ~10 people. */
export default function ChatBox() {
  const { user } = useAuth();
  const [open, setOpen] = useState(false);
  const [msgs, setMsgs] = useState<ChatMessage[]>([]);
  const [online, setOnline] = useState<OnlineUser[]>([]);
  const [draft, setDraft] = useState("");
  const [unread, setUnread] = useState(false);
  const listRef = useRef<HTMLDivElement>(null);
  // Read inside the interval callback, so the poll always uses the latest id
  // without re-creating the timer on every message.
  const lastId = useRef(0);

  /** Merge by id: a poll in flight during a send (and StrictMode's double mount
   *  in dev) can hand us a message we already appended. */
  function merge(fresh: ChatMessage[]) {
    if (!fresh.length) return;
    lastId.current = Math.max(lastId.current, ...fresh.map((m) => m.id));
    setMsgs((prev) => {
      const seen = new Set(prev.map((m) => m.id));
      const added = fresh.filter((m) => !seen.has(m.id));
      return added.length ? [...prev, ...added] : prev;
    });
  }

  useEffect(() => {
    const poll = () =>
      api
        .chat(lastId.current || undefined)
        .then((fresh) => {
          if (!fresh.length) return;
          merge(fresh);
          if (!open) setUnread(true);
        })
        .catch(() => {});

    const tick = () => {
      poll();
      if (open) api.online().then(setOnline).catch(() => {});
    };
    tick();
    const t = setInterval(tick, open ? 5_000 : 30_000);
    return () => clearInterval(t);
  }, [open]);

  useEffect(() => {
    if (open) setUnread(false);
  }, [open, msgs.length]);

  useEffect(() => {
    const el = listRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [msgs.length, open]);

  async function send(e: React.FormEvent) {
    e.preventDefault();
    const body = draft.trim();
    if (!body) return;
    setDraft("");
    try {
      merge([await api.sendChat(body)]);
    } catch {
      setDraft(body); // put it back rather than silently eating what they typed
    }
  }

  if (!open) {
    return (
      <button
        className="chat-launch"
        onClick={() => setOpen(true)}
        aria-label="Open team chat"
        title="Team chat"
      >
        💬 Chat
        {unread && <span className="chat-unread" aria-label="new messages" />}
      </button>
    );
  }

  return (
    <div className="chat-panel">
      <div className="chat-head">
        <span className="chat-title">Team chat</span>
        <span
          className="chat-presence"
          title={online.map((u) => u.full_name ?? "Unnamed user").join("\n") || "No one else"}
        >
          <span className="legend-dot" style={{ background: "var(--ok)" }} />
          {online.length} online
        </span>
        <button className="chat-close" onClick={() => setOpen(false)} aria-label="Close chat">
          ✕
        </button>
      </div>

      <div className="chat-list" ref={listRef} aria-live="polite">
        {msgs.length === 0 && <div className="muted">No messages yet. Say hi.</div>}
        {msgs.map((m, i) => {
          const mine = m.user_id === user?.id;
          // The name heads each run; consecutive messages from the same person
          // don't repeat it. i === 0 keeps the first message headed.
          const startsRun = i === 0 || msgs[i - 1].user_id !== m.user_id;
          return (
            <div
              key={m.id}
              className={`chat-msg ${mine ? "mine" : ""} ${startsRun ? "start" : ""}`}
            >
              {startsRun && (
                <div className="chat-meta">
                  {m.full_name ?? "Unnamed user"}
                  {m.role && <span className="badge">{m.role}</span>}
                </div>
              )}
              <div className="chat-bubble" title={ago(m.created_at)}>
                {m.body}
              </div>
              <div className="chat-time">{clock(m.created_at)}</div>
            </div>
          );
        })}
      </div>

      <form className="chat-form" onSubmit={send}>
        <label className="chat-sronly" htmlFor="chat-draft">
          Message
        </label>
        <input
          id="chat-draft"
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          placeholder="Type a message…"
          maxLength={2000}
          autoComplete="off"
        />
        <button className="btn sm" type="submit" disabled={!draft.trim()}>
          Send
        </button>
      </form>
    </div>
  );
}
