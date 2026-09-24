import { useEffect, useId, useMemo, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { useNavigate } from "react-router-dom";
import { adminCommandItems } from "../../lib/adminNav";

export function AdminCommandPalette() {
  const navigate = useNavigate();
  const dialogRef = useRef<HTMLDialogElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);
  const titleId = useId();
  const listId = useId();
  const [query, setQuery] = useState("");
  const [active, setActive] = useState(0);
  const items = useMemo(() => adminCommandItems(), []);
  const filtered = useMemo(() => {
    const needle = query.trim().toLowerCase();
    if (!needle) return items.slice(0, 8);
    return items
      .filter((item) => `${item.label} ${item.hint}`.toLowerCase().includes(needle))
      .slice(0, 12);
  }, [items, query]);

  const close = () => {
    dialogRef.current?.close();
    setQuery("");
    setActive(0);
  };

  const open = () => {
    const dialog = dialogRef.current;
    if (!dialog || dialog.open) return;
    dialog.showModal();
    setQuery("");
    setActive(0);
    queueMicrotask(() => inputRef.current?.focus());
  };

  const go = (to: string) => {
    close();
    navigate(to);
  };

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "k") {
        event.preventDefault();
        if (dialogRef.current?.open) close();
        else open();
      }
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, []);

  const activeId = filtered[active] ? `${listId}-option-${active}` : undefined;

  const dialog = (
    <dialog
      ref={dialogRef}
      className="admin-command-dialog"
      aria-labelledby={titleId}
      onClose={() => setQuery("")}
    >
      <h2 id={titleId} className="visually-hidden">
        Search the admin
      </h2>
      <input
        ref={inputRef}
        className="form-control admin-command-input"
        placeholder="Jump to a page or section"
        aria-label="Jump to a page or section"
        role="combobox"
        aria-autocomplete="list"
        aria-expanded="true"
        aria-controls={filtered.length > 0 ? listId : undefined}
        aria-activedescendant={activeId}
        value={query}
        onChange={(event) => {
          setQuery(event.target.value);
          setActive(0);
        }}
        onKeyDown={(event) => {
          if (event.key === "ArrowDown") {
            event.preventDefault();
            setActive((index) => Math.min(filtered.length - 1, index + 1));
          } else if (event.key === "ArrowUp") {
            event.preventDefault();
            setActive((index) => Math.max(0, index - 1));
          } else if (event.key === "Enter" && filtered[active]) {
            event.preventDefault();
            go(filtered[active].to);
          }
        }}
      />
      {filtered.length === 0 ? (
        <p className="admin-command-empty" role="status">
          No matches
        </p>
      ) : (
        <div id={listId} className="admin-command-list" role="listbox" aria-label="Matching pages">
          {filtered.map((item, index) => (
            <button
              key={item.id}
              id={`${listId}-option-${index}`}
              type="button"
              role="option"
              aria-selected={index === active}
              className={`admin-command-item${index === active ? " is-active" : ""}`}
              onMouseEnter={() => setActive(index)}
              onClick={() => go(item.to)}
            >
              <span>{item.label}</span>
              <span className="admin-command-hint">{item.hint}</span>
            </button>
          ))}
        </div>
      )}
    </dialog>
  );

  return (
    <>
      <button type="button" className="admin-rail-tool admin-command-launch" onClick={open}>
        <i className="bi bi-search" aria-hidden="true" />
        <span className="admin-nav-label">Search</span>
        <kbd className="admin-kbd admin-nav-label">⌘K</kbd>
      </button>
      {createPortal(dialog, document.body)}
    </>
  );
}
