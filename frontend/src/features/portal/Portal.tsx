import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Link, useLocation, useNavigate, useParams } from "react-router-dom";
import { get, newIdempotencyKey, post } from "../../api/client";
import type { BidReceipt, PublicTender } from "../../api/types";
import { PublicShell } from "../../components/Shell";
import { ErrorBanner, KeyValue, Loading, Notice } from "../../components/ui";
import { formatDateTime } from "../../lib/format";

export function PortalHome() {
  const q = useQuery({ queryKey: ["public-tenders"], queryFn: () => get<PublicTender[]>("/public/tenders") });
  return (
    <PublicShell>
      <h1>Open tenders</h1>
      <p className="lead">
        Submit your technical bid as <strong>one combined PDF</strong> containing all required documents, and your
        price bid as a <strong>separate PDF</strong>. The price bid is encrypted on receipt and opened only after
        technical evaluation.
      </p>
      {q.isLoading && <Loading />}
      <ErrorBanner error={q.error} />
      {q.data && q.data.length === 0 && <Notice>No tenders are currently open for submission.</Notice>}
      <table className="table">
        <thead>
          <tr>
            <th scope="col">Tender no.</th>
            <th scope="col">Title</th>
            <th scope="col">Authority</th>
            <th scope="col">Submission deadline</th>
            <th scope="col">
              <span className="sr-only">Action</span>
            </th>
          </tr>
        </thead>
        <tbody>
          {q.data?.map((t) => (
            <tr key={t.id}>
              <td className="mono">{t.reference_no}</td>
              <td>{t.title}</td>
              <td>{t.authority}</td>
              <td>{formatDateTime(t.submission_deadline, t.timezone)}</td>
              <td>
                {t.accepting_submissions ? (
                  <Link className="btn btn-primary btn-small" to={`/portal/tenders/${t.id}`}>
                    Submit bid
                  </Link>
                ) : (
                  <span className="muted">Closed</span>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </PublicShell>
  );
}

const MAX_MB = 50;

export function SubmitBid() {
  const { tenderId = "" } = useParams();
  const navigate = useNavigate();
  const q = useQuery({
    queryKey: ["public-tender", tenderId],
    queryFn: () => get<PublicTender>(`/public/tenders/${tenderId}`),
  });
  // One idempotency key per form instance: double-clicks or retries cannot create two bids.
  const idemKey = useMemo(() => newIdempotencyKey(), []);
  const [technical, setTechnical] = useState<File | null>(null);
  const [commercial, setCommercial] = useState<File | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [busy, setBusy] = useState(false);

  if (q.isLoading) return <PublicShell><Loading /></PublicShell>;
  if (q.error || !q.data) return <PublicShell><ErrorBanner error={q.error} /></PublicShell>;
  const t = q.data;

  const tooBig = (f: File | null) => Boolean(f && f.size > MAX_MB * 1024 * 1024);

  return (
    <PublicShell>
      <p>
        <Link to="/portal">← All open tenders</Link>
      </p>
      <h1>Submit bid</h1>
      <KeyValue
        items={[
          ["Tender no.", <span className="mono">{t.reference_no}</span>],
          ["Title", t.title],
          ["Authority", t.authority],
          ["Deadline", formatDateTime(t.submission_deadline, t.timezone)],
        ]}
      />
      <section className="card">
        <h2>Documents required in the combined technical PDF</h2>
        <ul className="checklist">
          {t.required_documents.map((d) => (
            <li key={d.name}>
              {d.name} {d.mandatory ? <span className="tag">Mandatory</span> : <span className="tag">If applicable</span>}
            </li>
          ))}
        </ul>
        <Notice kind="warn">
          Do <strong>not</strong> include any price, rate or bid value in the technical PDF. Pages that appear to
          contain prices are automatically withheld and may be treated under the tender&apos;s price-disclosure clause.
          Text-based (not scanned) PDFs allow faster scrutiny; scanned pages require manual reading.
        </Notice>
      </section>

      <form
        className="card form"
        onSubmit={async (e) => {
          e.preventDefault();
          setError(null);
          const form = new FormData(e.currentTarget);
          if (!technical) return;
          form.set("technical_pdf", technical);
          if (commercial) form.set("commercial_pdf", commercial);
          form.set("declaration_accepted", form.get("declaration_accepted") ? "true" : "false");
          setBusy(true);
          try {
            const receipt = await post<BidReceipt>(`/public/tenders/${t.id}/bids`, form, {
              "Idempotency-Key": idemKey,
            });
            navigate("/portal/receipt", { state: receipt, replace: true });
          } catch (err) {
            setError(err);
          } finally {
            setBusy(false);
          }
        }}
      >
        <h2>Bidder details</h2>
        <div className="grid2">
          <label className="field">
            <span>Legal name of bidder *</span>
            <input name="bidder_legal_name" required minLength={2} maxLength={300} autoComplete="organization" />
          </label>
          <label className="field">
            <span>Contact email *</span>
            <input name="bidder_email" type="email" required maxLength={320} autoComplete="email" />
          </label>
          <label className="field">
            <span>Contact phone *</span>
            <input name="bidder_phone" required pattern="[0-9+\-() ]{6,20}" autoComplete="tel" />
          </label>
        </div>

        <h2>Technical bid</h2>
        <label className="field">
          <span>Combined technical PDF (all documents, max {MAX_MB} MB) *</span>
          <input
            type="file"
            accept="application/pdf,.pdf"
            required
            onChange={(e) => setTechnical(e.target.files?.[0] ?? null)}
          />
        </label>
        {tooBig(technical) && <Notice kind="warn">File exceeds {MAX_MB} MB.</Notice>}

        {t.commercial_envelope_required && (
          <>
            <h2>Sealed price bid</h2>
            <Notice kind="sealed">
              🔒 The price bid PDF and the quoted total are encrypted immediately on receipt. No officer can view them
              before the authorised commercial opening, and they are opened only if your bid is found technically
              responsive.
            </Notice>
            <div className="grid2">
              <label className="field">
                <span>Price bid PDF *</span>
                <input
                  type="file"
                  accept="application/pdf,.pdf"
                  required
                  onChange={(e) => setCommercial(e.target.files?.[0] ?? null)}
                />
              </label>
              <label className="field">
                <span>Total quoted amount (INR, incl. taxes) *</span>
                <input
                  name="quoted_total_amount"
                  required
                  inputMode="decimal"
                  pattern="[0-9,]+(\.[0-9]{1,2})?"
                  placeholder="e.g. 48500000.00"
                  autoComplete="off"
                />
              </label>
            </div>
          </>
        )}

        <label className="check">
          <input type="checkbox" name="declaration_accepted" required />
          <span>
            I declare that the information and documents submitted are true and complete, and I understand that the
            submission cannot be modified after the deadline.
          </span>
        </label>
        <ErrorBanner error={error} />
        <button
          className="btn btn-primary"
          type="submit"
          disabled={busy || !technical || tooBig(technical) || tooBig(commercial)}
        >
          {busy ? "Submitting…" : "Submit bid"}
        </button>
      </form>
    </PublicShell>
  );
}

export function Receipt() {
  const location = useLocation();
  const r = location.state as BidReceipt | null;
  if (!r)
    return (
      <PublicShell>
        <Notice>No receipt to display.</Notice>
        <Link to="/portal">Back to open tenders</Link>
      </PublicShell>
    );
  return (
    <PublicShell>
      <h1>Submission receipt</h1>
      <Notice>{r.notice}</Notice>
      <section className="card printable">
        <KeyValue
          items={[
            ["Bid reference", <strong className="mono">{r.bid_reference}</strong>],
            ["Tender", `${r.tender_reference} — ${r.tender_title}`],
            ["Bidder", r.bidder_legal_name],
            ["Received at (server time)", formatDateTime(r.received_at)],
            [
              "Technical PDF",
              <span>
                {r.technical.filename} · {r.technical.page_count} pages · SHA-256{" "}
                <span className="mono small">{r.technical.sha256}</span>
              </span>,
            ],
            [
              "Price bid",
              r.commercial ? (
                <span>
                  🔒 Sealed · SHA-256 <span className="mono small">{r.commercial.sha256}</span>
                </span>
              ) : (
                "Not applicable"
              ),
            ],
            ["Package hash", <span className="mono small">{r.package_sha256}</span>],
          ]}
        />
      </section>
      <p>
        <button className="btn" onClick={() => window.print()}>
          Print receipt
        </button>{" "}
        <Link to="/portal">Back to open tenders</Link>
      </p>
    </PublicShell>
  );
}
