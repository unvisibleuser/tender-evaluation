import { useState, type ReactNode } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link, NavLink, useParams } from "react-router-dom";
import { get, post } from "../../api/client";
import type { AuditEvent, BidSummary, Paged, ReviewTask, Tender, TenderDocument, TenderStatus } from "../../api/types";
import { OfficerShell } from "../../components/Shell";
import { AuthImage, ErrorBanner, KeyValue, Loading, Notice, ReasonDialog, StatusBadge } from "../../components/ui";
import { useAuth } from "../../lib/auth";
import { formatDateTime, humanize, shortHash } from "../../lib/format";
import { CommercialTab } from "./Commercial";
import { EvaluationTab } from "./Evaluation";
import { RulebookTab } from "./Rulebook";

const STAGES: TenderStatus[] = [
  "DRAFT",
  "OPEN_FOR_SUBMISSION",
  "SUBMISSION_CLOSED",
  "TECHNICAL_EVALUATION",
  "TECHNICAL_COMPLETED",
  "COMMERCIAL_OPENED",
  "COMMERCIAL_EVALUATED",
];
export const TECH_UNSEALED: TenderStatus[] = STAGES.slice(2);

const TABS: [string, string][] = [
  ["overview", "Overview"],
  ["documents", "Tender documents"],
  ["rulebook", "Rulebook & criteria"],
  ["bids", "Bid submissions"],
  ["review", "Review queue"],
  ["evaluation", "Technical evaluation"],
  ["commercial", "Commercial"],
  ["audit", "Audit trail"],
];

export function useTender(id: string) {
  return useQuery({ queryKey: ["tender", id], queryFn: () => get<Tender>(`/tenders/${id}`) });
}

export function TenderWorkspace() {
  const { tenderId = "", tab = "overview" } = useParams();
  const q = useTender(tenderId);
  const t = q.data;
  const context = t && (
    <div className="subnav" aria-label="Tender sections">
      <div className="subnav-title mono">{t.reference_no}</div>
      {TABS.map(([key, label]) => (
        <NavLink key={key} to={`/officer/tenders/${tenderId}/${key}`} className={key === tab ? "active" : ""}>
          {label}
          {key === "commercial" && !["COMMERCIAL_OPENED", "COMMERCIAL_EVALUATED"].includes(t.status) && (
            <span aria-label="locked"> 🔒</span>
          )}
        </NavLink>
      ))}
    </div>
  );
  return (
    <OfficerShell context={context}>
      {q.isLoading && <Loading />}
      <ErrorBanner error={q.error} />
      {t && (
        <>
          <div className="tender-head">
            <div>
              <div className="mono muted">{t.reference_no}</div>
              <h1>{t.title}</h1>
              <div className="muted">
                {t.authority} · Deadline {formatDateTime(t.submission_deadline, t.timezone)} · Rulebook{" "}
                {t.pinned_rulebook_version_no ? `v${t.pinned_rulebook_version_no}` : "not pinned"}
              </div>
            </div>
            <StatusBadge status={t.status} />
          </div>
          <ol className="stages" aria-label="Tender stage">
            {STAGES.map((s) => (
              <li
                key={s}
                className={s === t.status ? "current" : STAGES.indexOf(s) < STAGES.indexOf(t.status) ? "done" : ""}
                aria-current={s === t.status ? "step" : undefined}
              >
                {humanize(s)}
              </li>
            ))}
          </ol>
          {tab === "overview" && <Overview t={t} />}
          {tab === "documents" && <Documents t={t} />}
          {tab === "rulebook" && <RulebookTab t={t} />}
          {tab === "bids" && <Bids t={t} />}
          {tab === "review" && <Review t={t} />}
          {tab === "evaluation" && <EvaluationTab t={t} />}
          {tab === "commercial" && <CommercialTab t={t} />}
          {tab === "audit" && <Audit t={t} />}
        </>
      )}
    </OfficerShell>
  );
}

const ACTION_TEXT: Record<string, [string, string, boolean]> = {
  publish: ["Publish for submissions", "Opens the bidder portal for this tender using the pinned rulebook.", false],
  close: [
    "Close submissions",
    "Locks all submissions and starts document processing. Before the deadline this is permitted only in demo mode.",
    false,
  ],
  "start-technical": ["Start technical evaluation", "Begins technical scrutiny with the pinned rulebook.", false],
  "complete-technical": [
    "Complete technical evaluation",
    "Requires an officer decision for every bid. Commercial opening becomes possible afterwards.",
    false,
  ],
  cancel: ["Cancel tender", "Irreversible. The tender will be cancelled at its current stage.", true],
};

function Overview({ t }: { t: Tender }) {
  const qc = useQueryClient();
  const [action, setAction] = useState<string | null>(null);
  const spec = action ? ACTION_TEXT[action] : undefined;
  return (
    <section>
      <div className="grid2">
        <div className="card">
          <h2>Tender details</h2>
          <KeyValue
            items={[
              ["Authority", t.authority],
              ["Description", t.description || "—"],
              ["Submission deadline", formatDateTime(t.submission_deadline, t.timezone)],
              ["Bids received", String(t.bid_count)],
              ["Price bid envelope", t.commercial_envelope_required ? "Required (sealed)" : "Not used"],
              [
                "Commercial method",
                t.commercial_evaluation_method ? humanize(t.commercial_evaluation_method) : "REQUIRES OFFICER CONFIGURATION",
              ],
              ["Combined technical-commercial ranking", "Not configured (no tender-published formula)"],
              ["Opening quorum", `${t.opening_quorum} distinct officer(s)`],
            ]}
          />
        </div>
        <div className="card">
          <h2>Stage actions</h2>
          {t.allowed_actions.length === 0 && <p className="muted">No stage actions available for your role.</p>}
          <div className="stack">
            {t.allowed_actions.map((a) => (
              <button
                key={a}
                className={`btn ${ACTION_TEXT[a]?.[2] ? "btn-danger" : "btn-primary"}`}
                onClick={() => setAction(a)}
              >
                {ACTION_TEXT[a]?.[0] ?? humanize(a)}
              </button>
            ))}
          </div>
        </div>
      </div>
      <ReasonDialog
        open={Boolean(action)}
        title={spec?.[0] ?? ""}
        description={spec?.[1]}
        confirmLabel={spec?.[0] ?? "Confirm"}
        danger={spec?.[2]}
        minLength={action === "cancel" || action === "close" ? 10 : 3}
        onClose={() => setAction(null)}
        onConfirm={async (reason) => {
          await post(`/tenders/${t.id}/actions/${action}`, { reason });
          await qc.invalidateQueries();
        }}
      />
    </section>
  );
}

function Documents({ t }: { t: Tender }) {
  const { has } = useAuth();
  const qc = useQueryClient();
  const [view, setView] = useState<{ id: string; page: number; pages: number } | null>(null);
  const q = useQuery({ queryKey: ["docs", t.id], queryFn: () => get<TenderDocument[]>(`/tenders/${t.id}/documents`) });
  const upload = useMutation({
    mutationFn: (f: FormData) => post<TenderDocument>(`/tenders/${t.id}/documents`, f),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["docs", t.id] }),
  });
  return (
    <section className="split">
      <div>
        <table className="table">
          <thead>
            <tr>
              <th scope="col">Document</th>
              <th scope="col">Pages</th>
              <th scope="col">SHA-256</th>
              <th scope="col">Uploaded</th>
            </tr>
          </thead>
          <tbody>
            {q.data?.map((d) => (
              <tr key={d.id}>
                <td>
                  <button className="linklike" onClick={() => setView({ id: d.id, page: 1, pages: d.page_count })}>
                    {d.title}
                  </button>
                </td>
                <td>{d.page_count}</td>
                <td className="mono small" title={d.sha256}>
                  {shortHash(d.sha256)}
                </td>
                <td>{formatDateTime(d.uploaded_at)}</td>
              </tr>
            ))}
          </tbody>
        </table>
        {has("TENDER_ADMIN") && (
          <form
            className="card form"
            onSubmit={(e) => {
              e.preventDefault();
              upload.mutate(new FormData(e.currentTarget));
              e.currentTarget.reset();
            }}
          >
            <h2>Upload tender document</h2>
            <label className="field">
              <span>Title</span>
              <input name="title" required />
            </label>
            <label className="field">
              <span>PDF file</span>
              <input name="file" type="file" accept="application/pdf" required />
            </label>
            <ErrorBanner error={upload.error} />
            <button className="btn btn-primary" disabled={upload.isPending}>
              Upload
            </button>
          </form>
        )}
      </div>
      <div>
        {view ? (
          <div className="card">
            <PageNav page={view.page} pages={view.pages} onChange={(p) => setView({ ...view, page: p })} />
            <AuthImage path={`/tender-documents/${view.id}/pages/${view.page}/image`} alt={`Tender page ${view.page}`} />
          </div>
        ) : (
          <Notice>Select a document to view it.</Notice>
        )}
      </div>
    </section>
  );
}

export function PageNav({ page, pages, onChange }: { page: number; pages: number; onChange: (p: number) => void }) {
  return (
    <div className="pagenav">
      <button className="btn btn-small" disabled={page <= 1} onClick={() => onChange(page - 1)}>
        ← Prev
      </button>
      <span>
        Page {page} of {pages}
      </span>
      <button className="btn btn-small" disabled={page >= pages} onClick={() => onChange(page + 1)}>
        Next →
      </button>
    </div>
  );
}

export function SealedTechnical({ t, children }: { t: Tender; children: ReactNode }) {
  if (!TECH_UNSEALED.includes(t.status))
    return (
      <Notice kind="sealed">
        🔒 Bid contents are sealed until submissions close. {t.bid_count} submission(s) received so far.
      </Notice>
    );
  return <>{children}</>;
}

function Bids({ t }: { t: Tender }) {
  const [search, setSearch] = useState("");
  const [offset, setOffset] = useState(0);
  const limit = 25;
  const q = useQuery({
    queryKey: ["bids", t.id, search, offset],
    queryFn: () =>
      get<Paged<BidSummary>>(
        `/tenders/${t.id}/bids?limit=${limit}&offset=${offset}${search ? `&q=${encodeURIComponent(search)}` : ""}`,
      ),
    enabled: TECH_UNSEALED.includes(t.status),
    refetchInterval: (query) =>
      query.state.data?.items.some((b) => ["RECEIVED", "PROCESSING"].includes(b.processing_status)) ? 2000 : false,
  });
  return (
    <SealedTechnical t={t}>
      <div className="toolbar">
        <label className="field inline">
          <span>Search bidder / reference</span>
          <input
            value={search}
            onChange={(e) => {
              setSearch(e.target.value);
              setOffset(0);
            }}
          />
        </label>
      </div>
      <ErrorBanner error={q.error} />
      <table className="table sticky">
        <thead>
          <tr>
            <th scope="col">Bid reference</th>
            <th scope="col">Bidder</th>
            <th scope="col">Received</th>
            <th scope="col">Pages</th>
            <th scope="col">Processing</th>
            <th scope="col">Open reviews</th>
            <th scope="col">Withheld / unreadable</th>
            <th scope="col">Technical outcome (officer)</th>
          </tr>
        </thead>
        <tbody>
          {q.data?.items.map((b) => (
            <tr key={b.id}>
              <td className="mono">
                <Link to={`/officer/bids/${b.id}`}>{b.bid_reference}</Link>
              </td>
              <td>{b.bidder_legal_name}</td>
              <td>{formatDateTime(b.submitted_at)}</td>
              <td>{b.page_count}</td>
              <td>
                <StatusBadge status={b.processing_status} />
                {b.processing_error && <span className="muted small"> {b.processing_error}</span>}
              </td>
              <td>{b.open_review_tasks}</td>
              <td>
                {b.withheld_pages} / {b.unreadable_pages}
              </td>
              <td>
                <StatusBadge status={b.technical_outcome} />
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      {q.data && (
        <div className="pagenav">
          <button className="btn btn-small" disabled={offset === 0} onClick={() => setOffset(offset - limit)}>
            ← Prev
          </button>
          <span>
            {q.data.total === 0 ? 0 : offset + 1}–{Math.min(offset + limit, q.data.total)} of {q.data.total}
          </span>
          <button
            className="btn btn-small"
            disabled={offset + limit >= q.data.total}
            onClick={() => setOffset(offset + limit)}
          >
            Next →
          </button>
        </div>
      )}
    </SealedTechnical>
  );
}

function Review({ t }: { t: Tender }) {
  const [status, setStatus] = useState<"OPEN" | "RESOLVED">("OPEN");
  const q = useQuery({
    queryKey: ["review", t.id, status],
    queryFn: () => get<Paged<ReviewTask>>(`/tenders/${t.id}/review-tasks?status=${status}&limit=500`),
    enabled: TECH_UNSEALED.includes(t.status),
  });
  return (
    <SealedTechnical t={t}>
      <div className="toolbar" role="group" aria-label="Filter">
        {(["OPEN", "RESOLVED"] as const).map((s) => (
          <button key={s} className={`btn btn-small ${status === s ? "btn-primary" : ""}`} onClick={() => setStatus(s)}>
            {humanize(s)}
          </button>
        ))}
      </div>
      <ErrorBanner error={q.error} />
      <table className="table">
        <thead>
          <tr>
            <th scope="col">Bid</th>
            <th scope="col">Reason</th>
            <th scope="col">Field / page</th>
            <th scope="col">Detail</th>
            <th scope="col">Status</th>
          </tr>
        </thead>
        <tbody>
          {q.data?.items.map((r) => (
            <tr key={r.id}>
              <td>
                <Link to={`/officer/bids/${r.bid_id}${r.field_key ? `?field=${r.field_key}` : r.page_no ? `?page=${r.page_no}` : ""}`}>
                  {r.bid_reference}
                </Link>
                <div className="muted small">{r.bidder_legal_name}</div>
              </td>
              <td>
                <StatusBadge status={r.reason === "POSSIBLE_COMMERCIAL_LEAKAGE" ? "SEALED" : "PENDING_REVIEW"} label={humanize(r.reason)} />
              </td>
              <td className="mono">{r.field_key ?? (r.page_no ? `page ${r.page_no}` : "—")}</td>
              <td>
                {r.detail}
                {r.resolution && <div className="muted small">Resolution: {r.resolution}</div>}
              </td>
              <td>
                <StatusBadge status={r.status} />
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      {q.data?.items.length === 0 && <Notice>No {status.toLowerCase()} review tasks.</Notice>}
    </SealedTechnical>
  );
}

function Audit({ t }: { t: Tender }) {
  const { has } = useAuth();
  const q = useQuery({
    queryKey: ["audit", t.id],
    queryFn: () => get<Paged<AuditEvent>>(`/tenders/${t.id}/audit-events?limit=500`),
  });
  const verify = useMutation({ mutationFn: () => get<{ ok: boolean; events_checked: number }>("/audit/verify") });
  return (
    <section>
      {has("AUDITOR", "TENDER_ADMIN") && (
        <div className="toolbar">
          <button className="btn" onClick={() => verify.mutate()}>
            Verify audit hash chain
          </button>
          {verify.data && (
            <StatusBadge
              status={verify.data.ok ? "PASS" : "FAIL"}
              label={verify.data.ok ? `Chain intact (${verify.data.events_checked} events)` : "Chain BROKEN"}
            />
          )}
          <ErrorBanner error={verify.error} />
        </div>
      )}
      <ErrorBanner error={q.error} />
      <table className="table audit">
        <thead>
          <tr>
            <th scope="col">Time</th>
            <th scope="col">Actor</th>
            <th scope="col">Action</th>
            <th scope="col">Reason</th>
            <th scope="col">Change</th>
            <th scope="col">Hash</th>
          </tr>
        </thead>
        <tbody>
          {q.data?.items.map((e) => (
            <tr key={e.id}>
              <td className="nowrap">{formatDateTime(e.created_at)}</td>
              <td>
                {e.actor_label}
                <div className="muted small">{e.actor_kind}</div>
              </td>
              <td className="mono small">{e.action}</td>
              <td>{e.reason ?? "—"}</td>
              <td className="mono small change">
                {e.before && <div>before: {JSON.stringify(e.before)}</div>}
                {e.after && <div>after: {JSON.stringify(e.after)}</div>}
              </td>
              <td className="mono small" title={e.hash}>
                {shortHash(e.hash)}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </section>
  );
}
