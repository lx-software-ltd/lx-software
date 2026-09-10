import { useState, type FormEvent } from "react";
import { subscribeToNewsletter, type NewsletterLang, type NewsletterList } from "../lib/newsletter";

export function NewsletterForm() {
  const [list, setList] = useState<NewsletterList>("parents");
  const [lang, setLang] = useState<NewsletterLang>("en");
  const [email, setEmail] = useState("");
  const [status, setStatus] = useState<"idle" | "sending" | "ok" | "error">("idle");
  const [error, setError] = useState("");

  async function onSubmit(event: FormEvent) {
    event.preventDefault();
    setStatus("sending");
    setError("");
    try {
      await subscribeToNewsletter({ list, email, lang });
      setStatus("ok");
      setEmail("");
    } catch (err) {
      setStatus("error");
      setError(err instanceof Error ? err.message : "Could not subscribe.");
    }
  }

  return (
    <form className="d-flex flex-column gap-2" onSubmit={(e) => void onSubmit(e)}>
      <label className="form-label mb-0" htmlFor="nl-email">
        Newsletter
      </label>
      <p className="small text-muted mb-0">
        Fortnightly activity updates. Confirm the email we send; unsubscribe any time.
      </p>
      <input
        id="nl-email"
        className="form-control"
        type="email"
        required
        autoComplete="email"
        placeholder="you@example.com"
        value={email}
        onChange={(e) => setEmail(e.target.value)}
      />
      <div className="d-flex flex-wrap gap-2">
        <select
          className="form-select form-select-sm"
          aria-label="List"
          value={list}
          onChange={(e) => setList(e.target.value as NewsletterList)}
        >
          <option value="parents">Parents</option>
          <option value="providers">Providers</option>
        </select>
        <select
          className="form-select form-select-sm"
          aria-label="Language"
          value={lang}
          onChange={(e) => setLang(e.target.value as NewsletterLang)}
        >
          <option value="en">English</option>
          <option value="zh-HK">繁體中文</option>
        </select>
        <button className="btn btn-sm btn-primary" type="submit" disabled={status === "sending"}>
          {status === "sending" ? "Sending…" : "Subscribe"}
        </button>
      </div>
      {status === "ok" ? (
        <p className="small text-success mb-0">Check your inbox to confirm.</p>
      ) : null}
      {status === "error" ? <p className="small text-danger mb-0">{error}</p> : null}
    </form>
  );
}
