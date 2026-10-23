import { type FormEvent, useEffect, useRef, useState } from "react";

import { post } from "../api";
import type { ChatAnswer, ChatTurn, SourceRef } from "../types";
import { Icon } from "./Icon";
import { Basis } from "./Sources";

const SUGGESTIONS = [
  "Покажите влияние в разрезе контрагентов",
  "Что банк ожидает по ставке и курсу?",
  "Где первоисточник этих цифр?",
  "Как это касается моей роли?",
];

/** Уточняющие вопросы к разбору (POST /api/chat): ответ со ссылками только на найденные источники. */
export function Chat({ insightId, onSources }: { insightId: string; onSources: (refs: SourceRef[]) => void }) {
  const [turns, setTurns] = useState<ChatTurn[]>([]);
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const end = useRef<HTMLDivElement>(null);

  useEffect(() => {
    setTurns([]);
  }, [insightId]);
  useEffect(() => end.current?.scrollIntoView({ block: "nearest" }), [turns, busy]);

  const ask = async (question: string) => {
    const q = question.trim();
    if (!q || busy) return;
    const history = turns.slice(-6).map(({ role, content }) => ({ role, content })); // backend читает 6 последних
    setTurns((t) => [...t, { role: "user", content: q }]);
    setText("");
    setBusy(true);
    setError(null);
    try {
      const r = await post<ChatAnswer>("/chat", { insight_id: insightId, question: q, history });
      onSources(r.sources);
      setTurns((t) => [...t, { role: "assistant", content: r.answer, sources: r.sources }]);
    } catch (e) {
      setError((e as Error).message);
      setTurns((t) => t.slice(0, -1));
      setText(q);
    } finally {
      setBusy(false);
    }
  };

  const submit = (e: FormEvent) => {
    e.preventDefault();
    void ask(text);
  };

  return (
    <section className="chat" aria-labelledby="chat-title">
      <h2 id="chat-title">Спросить о событии</h2>
      <p className="muted">Другой разрез, детали или первоисточник. Ответ опирается на данные компании, аналитику банка и новости.</p>
      <div className="chat-log">
        {turns.map((t, i) => (
          <div key={i} className={`bubble bubble-${t.role}`}>
            <p>{t.content}</p>
            {t.sources && t.sources.length > 0 && <Basis ids={t.sources.map((s) => s.source_id)} />}
          </div>
        ))}
        {busy && <div className="bubble bubble-assistant bubble-wait">Ищу в данных компании и аналитике банка…</div>}
        <div ref={end} />
      </div>
      {!turns.length && (
        <div className="suggestions">
          {SUGGESTIONS.map((s) => <button key={s} className="chip-button" onClick={() => void ask(s)} disabled={busy}>{s}</button>)}
        </div>
      )}
      {error && <p className="error-text" role="alert">{error}</p>}
      <form className="chat-form" onSubmit={submit}>
        <label htmlFor="chat-input" className="visually-hidden">Вопрос</label>
        <textarea id="chat-input" rows={2} maxLength={2000} placeholder="Например: а если рубль ослабнет?" value={text}
                  onChange={(e) => setText(e.target.value)}
                  onKeyDown={(e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); void ask(text); } }} />
        <button className="button primary icon-only" disabled={busy || !text.trim()} title="Отправить">
          <Icon name="send" size={18} /><span className="visually-hidden">Отправить</span>
        </button>
      </form>
    </section>
  );
}
