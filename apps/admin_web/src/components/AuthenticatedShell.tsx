import { useEffect, useId, useRef, useState } from "react";
import { NavLink, Outlet } from "react-router-dom";
import { ADMIN_NAV_GROUPS } from "../lib/adminNav";
import { useAuth, type AuthUser } from "./AuthProvider";

function NavGroups({ onNavigate }: { readonly onNavigate?: () => void }) {
  return (
    <>
      {ADMIN_NAV_GROUPS.map((group) => (
        <div key={group[0].to} className="admin-nav-group">
          {group.map((item) => (
            <NavLink
              key={item.to}
              to={item.to}
              end={item.end}
              className={({ isActive }) => `admin-nav-link${isActive ? " active" : ""}`}
              title={item.label}
              onClick={onNavigate}
            >
              <i className={`bi ${item.icon}`} aria-hidden="true" />
              <span className="admin-nav-label">{item.label}</span>
            </NavLink>
          ))}
        </div>
      ))}
    </>
  );
}

function RailBrand({ className = "" }: { readonly className?: string }) {
  return (
    <div className={`admin-brand${className ? ` ${className}` : ""}`}>
      <span className="admin-brand-mark" aria-hidden="true">LX</span>
      <span className="admin-nav-label">Admin</span>
    </div>
  );
}

function RailFooter({ user, onLogout }: { readonly user: AuthUser | null; readonly onLogout: () => void }) {
  return (
    <div className="admin-rail-footer">
      {user?.email ? <div className="admin-rail-user" title={user.email}>{user.email}</div> : null}
      <button type="button" className="admin-rail-tool" onClick={onLogout}>
        <i className="bi bi-box-arrow-right" aria-hidden="true" />
        <span className="admin-nav-label">Sign out</span>
      </button>
    </div>
  );
}

export function AuthenticatedShell() {
  const { logout, user } = useAuth();
  const [isNavOpen, setIsNavOpen] = useState(false);
  const navId = useId();
  const togglerRef = useRef<HTMLButtonElement>(null);
  const closeRef = useRef<HTMLButtonElement>(null);

  const closeNav = () => {
    setIsNavOpen(false);
    togglerRef.current?.focus();
  };

  useEffect(() => {
    if (!isNavOpen) return;
    closeRef.current?.focus();
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        setIsNavOpen(false);
        togglerRef.current?.focus();
      }
    };
    const media = window.matchMedia("(min-width: 768px)");
    const onViewportChange = () => {
      if (media.matches) setIsNavOpen(false);
    };
    const scrollY = window.scrollY;
    document.body.classList.add("admin-nav-open");
    document.body.style.top = `-${scrollY}px`;
    document.addEventListener("keydown", onKeyDown);
    media.addEventListener("change", onViewportChange);
    return () => {
      document.body.classList.remove("admin-nav-open");
      document.body.style.top = "";
      window.scrollTo(0, scrollY);
      document.removeEventListener("keydown", onKeyDown);
      media.removeEventListener("change", onViewportChange);
    };
  }, [isNavOpen]);

  return (
    <div className="admin-shell">
      <header className="admin-topbar">
          <button
            ref={togglerRef}
            type="button"
            className="btn btn-outline-secondary btn-sm"
            aria-label="Open navigation menu"
            aria-controls={navId}
            aria-expanded={isNavOpen}
            onClick={() => setIsNavOpen(true)}
          >
            <i className="bi bi-list" aria-hidden="true" />
          </button>
          <span className="admin-topbar-brand">LX Admin</span>
        </header>
        {isNavOpen ? (
          <button
            type="button"
            className="admin-nav-backdrop d-md-none"
            aria-label="Close navigation menu"
            onClick={closeNav}
          />
        ) : null}
        <aside
          id={navId}
          className={`admin-mobile-nav d-md-none ${isNavOpen ? "is-open" : ""}`}
          role="dialog"
          aria-modal={isNavOpen}
          aria-label="Admin navigation"
          aria-hidden={!isNavOpen}
          inert={!isNavOpen}
        >
          <div className="d-flex align-items-center justify-content-between mb-3">
            <RailBrand className="p-0" />
            <button
              ref={closeRef}
              type="button"
              className="btn-close"
              aria-label="Close navigation menu"
              onClick={closeNav}
            />
          </div>
          {user?.email ? <p className="small text-muted">{user.email}</p> : null}
          <nav className="d-flex flex-column gap-1" aria-label="Admin pages">
            <NavGroups onNavigate={closeNav} />
          </nav>
          <div className="mt-3">
            <button type="button" className="btn btn-outline-secondary w-100" onClick={() => logout()}>
              Sign out
            </button>
          </div>
        </aside>
        <aside className="admin-sidebar">
          <div className="admin-rail-primary">
            <RailBrand />
            <nav className="admin-rail-scroll" aria-label="Admin pages">
              <NavGroups />
            </nav>
            <RailFooter user={user} onLogout={() => logout()} />
          </div>
        </aside>
        <main className="admin-main">
          <div className="admin-content">
            <Outlet />
          </div>
        </main>
    </div>
  );
}
