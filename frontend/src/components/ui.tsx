import { useEffect, useRef, useState, type ReactNode } from "react";
import { ApiError, fetchBlobUrl } from "../api/client";
import { humanize } from "../lib/format";

// ------------------------------------------------------------------ status labels (text + glyph, never colour alone)

type Tone = "ok" | "bad" | "warn" | "info" | "neutral" | "sealed";

const STATUS_TONE: Record<string, [Tone, string]> = {
  PASS: ["ok", "✓"],
  FAIL: ["bad", "✕"],
  MISSING: ["warn", "∅"],
  UNREADABLE: ["warn", "?"],
  AMBIGUOUS: ["warn", "≈"],
  PENDING_REVIEW: ["info", "◷"],
  PENDING_OFFICER_DECISION: ["info", "◷"],
  NOT_APPLICABLE: ["neutral", "–"],
  NOT_EVALUATED: ["neutral", "–"],
  RESPONSIVE: ["ok", "✓"],
  NON_RESPONSIVE: ["bad", "✕"],
  READY: ["ok", "✓"],
  REVIEW_REQUIRED: ["info", "◷"],
  PROCESSING: ["neutral", "…"],
  RECEIVED: ["neutral", "…"],
  FAILED: ["bad", "!"],
  FOUND: ["ok", "✓"],
  NOT_FOUND: ["warn", "∅"],
  UNCERTAIN: ["info", "?"],
  EXTRACTED: ["neutral", "•"],
  APPROVED: ["ok", "✓"],
  DRAFT: ["neutral", "✎"],
  IN_REVIEW: ["info", "◷"],
  SUPERSEDED: ["neutral", "–"],
  OPEN: ["info", "◷"],
  RESOLVED: ["ok", "✓"],
  SEALED: ["sealed", "🔒"],
  WITHHELD_COMMERCIAL: ["sealed", "🔒"],
  NO_TEXT_LAYER: ["warn", "?"],
  TEXT_LAYER: ["neutral", "•"],
};

export function StatusBadge({ status, label }: { status: string; label?: string }) {
  const [tone, glyph] = STATUS_TONE[status] ?? ["neutral", "•"];
  return (
    <span className={`badge badge-${tone}`}>
      <span aria-hidden="true">{glyph}</span> {label ?? humanize(status)}
    </span>
  );
}

/** Distinguishes automated observations from officer actions, as required by CLAUDE.md. */
export function ProvenanceTag({ kind }: { kind: "auto" | "officer" | "rule" | "decision"; children?: ReactNode }) {
  const text = {
    auto: "Automated extraction",
    officer: "Officer verified",
    rule: "Rule evaluated",
    decision: "Officer approved",
  }[kind];
  return <span className={`prov prov-${kind}`}>{text}</span>;
}

// ------------------------------------------------------------------ feedback

export function ErrorBanner({ error }: { error: unknown }) {
  if (!error) return null;
  const e = error instanceof ApiError ? error : null;
  return (
    <div className="alert alert-error" role="alert">
      <strong>{e ? e.code : "Error"}:</strong> {e ? e.message : String(error)}
      {e && Array.isArray(e.details) && e.details.length > 0 && (
        <ul>
          {(e.details as { message?: string; msg?: string }[]).slice(0, 10).map((d, i) => (
            <li key={i}>{d.message ?? d.msg ?? JSON.stringify(d)}</li>
          ))}
        </ul>
      )}
    </div>
  );
}

export function Notice({ kind = "info", children }: { kind?: "info" | "warn" | "sealed"; children: ReactNode }) {
  return (
    <div className={`alert alert-${kind}`} role="status">
      {children}
    </div>
  );
}

export function Loading({ what = "Loading" }: { what?: string }) {
  return (
    <p className="muted" role="status">
      {what}…
    </p>
  );
}

// ------------------------------------------------------------------ reason dialog for audited actions

export function ReasonDialog({
  open,
  title,
  description,
  confirmLabel,
  minLength = 5,
  danger,
  onConfirm,
  onClose,
  children,
}: {
  open: boolean;
  title: string;
  description?: ReactNode;
  confirmLabel: string;
  minLength?: number;
  danger?: boolean;
  onConfirm: (reason: string) => Promise<void>;
  onClose: () => void;
  children?: ReactNode;
}) {
  const ref = useRef<HTMLDialogElement>(null);
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);

  useEffect(() => {
    const d = ref.current;
    if (!d) return;
    if (open && !d.open) {
      setReason("");
      setError(null);
      d.showModal();
    } else if (!open && d.open) d.close();
  }, [open]);

  return (
    <dialog ref={ref} className="dialog" onClose={onClose} aria-labelledby="dlg-title">
      <form
        method="dialog"
        onSubmit={async (e) => {
          e.preventDefault();
          setBusy(true);
          setError(null);
          try {
            await onConfirm(reason.trim());
            onClose();
          } catch (err) {
            setError(err);
          } finally {
            setBusy(false);
          }
        }}
      >
        <h2 id="dlg-title">{title}</h2>
        {description && <div className="dialog-desc">{description}</div>}
        {children}
        <label className="field">
          <span>Reason (recorded in the audit trail)</span>
          <textarea
            required
            minLength={minLength}
            rows={3}
            value={reason}
            onChange={(e) => setReason(e.target.value)}
          />
        </label>
        <ErrorBanner error={error} />
        <div className="dialog-actions">
          <button type="button" className="btn" onClick={onClose} disabled={busy}>
            Cancel
          </button>
          <button
            type="submit"
            className={`btn ${danger ? "btn-danger" : "btn-primary"}`}
            disabled={busy || reason.trim().length < minLength}
          >
            {busy ? "Working…" : confirmLabel}
          </button>
        </div>
      </form>
    </dialog>
  );
}

// ------------------------------------------------------------------ authorised image with evidence highlight

export function AuthImage({ path, alt }: { path: string; alt: string }) {
  const [url, setUrl] = useState<string | null>(null);
  const [error, setError] = useState<unknown>(null);
  useEffect(() => {
    let revoked: string | null = null;
    let cancelled = false;
    setUrl(null);
    setError(null);
    fetchBlobUrl(path)
      .then((u) => {
        if (cancelled) URL.revokeObjectURL(u);
        else {
          revoked = u;
          setUrl(u);
        }
      })
      .catch((e) => !cancelled && setError(e));
    return () => {
      cancelled = true;
      if (revoked) URL.revokeObjectURL(revoked);
    };
  }, [path]);
  if (error) {
    const sealed = error instanceof ApiError && error.code === "COMMERCIAL_SEALED";
    return sealed ? (
      <div className="page-withheld" role="img" aria-label="Page withheld">
        <StatusBadge status="WITHHELD_COMMERCIAL" label="Page withheld — possible price information" />
        <p>Content is not displayed to any officer until an approver releases it with a recorded reason.</p>
      </div>
    ) : (
      <ErrorBanner error={error} />
    );
  }
  if (!url) return <Loading what="Rendering page" />;
  return <img src={url} alt={alt} className="page-img" draggable={false} />;
}

export function EvidencePage({
  path,
  pageNo,
  width,
  height,
  highlight,
}: {
  path: string;
  pageNo: number;
  width: number;
  height: number;
  highlight: number[] | null;
}) {
  return (
    <div className="evidence-page">
      <AuthImage path={path} alt={`Submitted document page ${pageNo}`} />
      {highlight && highlight.length === 4 && (
        <div
          className="evidence-box"
          aria-label="Highlighted evidence region"
          style={{
            left: `${((highlight[0] ?? 0) / width) * 100}%`,
            top: `${((highlight[1] ?? 0) / height) * 100}%`,
            width: `${(((highlight[2] ?? 0) - (highlight[0] ?? 0)) / width) * 100}%`,
            height: `${(((highlight[3] ?? 0) - (highlight[1] ?? 0)) / height) * 100}%`,
          }}
        />
      )}
    </div>
  );
}

export function KeyValue({ items }: { items: [string, ReactNode][] }) {
  return (
    <dl className="kv">
      {items.map(([k, v]) => (
        <div key={k}>
          <dt>{k}</dt>
          <dd>{v}</dd>
        </div>
      ))}
    </dl>
  );
}
