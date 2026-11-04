import type { ReactNode } from "react";
import { Link, NavLink } from "react-router-dom";
import { useAuth } from "../lib/auth";
import { ROLE_LABELS } from "../lib/format";

function Emblem() {
  return (
    <div className="emblem" aria-hidden="true">
      <svg viewBox="0 0 32 32" width="34" height="34">
        <circle cx="16" cy="16" r="14.5" fill="none" stroke="currentColor" strokeWidth="1.5" />
        <path d="M17.5 5 L10 18 h5.5 L13.5 27 L22 13.5 h-5.5 Z" fill="currentColor" />
      </svg>
    </div>
  );
}

export function Header({ subtitle, right }: { subtitle: string; right?: ReactNode }) {
  const { environment } = useAuth();
  return (
    <header className="topbar">
      <Link to="/" className="brand">
        <Emblem />
        <span>
          <span className="brand-org">Demo Power Utility (Synthetic)</span>
          <span className="brand-title">Tender Scrutiny &amp; Evaluation Portal</span>
        </span>
      </Link>
      <span className="subtitle">{subtitle}</span>
      <span className={`env env-${environment}`} title="Deployment environment">
        {environment.toUpperCase()}
      </span>
      <div className="topbar-right">{right}</div>
    </header>
  );
}

export function OfficerShell({ children, context }: { children: ReactNode; context?: ReactNode }) {
  const { officer, logout } = useAuth();
  return (
    <div className="app">
      <a href="#main" className="skip-link">
        Skip to content
      </a>
      <Header
        subtitle="Officer workspace"
        right={
          officer && (
            <div className="user">
              <span>
                <strong>{officer.display_name}</strong>
                <span className="muted"> · {officer.roles.map((r) => ROLE_LABELS[r] ?? r).join(", ")}</span>
              </span>
              <button className="btn btn-small" onClick={logout}>
                Sign out
              </button>
            </div>
          )
        }
      />
      <div className="layout">
        <nav className="sidebar" aria-label="Primary">
          <NavLink to="/officer" end>
            Tenders
          </NavLink>
          {context}
        </nav>
        <main id="main" className="content" tabIndex={-1}>
          {children}
        </main>
      </div>
      <footer className="footer">
        AI and automated outputs are observations only. Eligibility, rejection and award decisions are made by
        authorised officers and recorded in the audit trail.
      </footer>
    </div>
  );
}

export function PublicShell({ children }: { children: ReactNode }) {
  return (
    <div className="app">
      <a href="#main" className="skip-link">
        Skip to content
      </a>
      <Header subtitle="Bidder submission portal" right={<Link to="/officer/login">Officer sign-in</Link>} />
      <main id="main" className="content content-narrow" tabIndex={-1}>
        {children}
      </main>
      <footer className="footer">
        Synthetic demonstration environment. Do not upload real bidder documents or personal data.
      </footer>
    </div>
  );
}
