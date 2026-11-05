import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link, useParams, useSearchParams } from "react-router-dom";
import { get, post } from "../../api/client";
import type { BidDetail, ExtractedField, Paged, ReviewTask } from "../../api/types";
import { OfficerShell } from "../../components/Shell";
import {
  ErrorBanner,
  EvidencePage,
  KeyValue,
  Loading,
  Notice,
  ProvenanceTag,
  ReasonDialog,
  StatusBadge,
} from "../../components/ui";
import { useAuth } from "../../lib/auth";
import { formatDateTime, humanize, shortHash } from "../../lib/format";
import { PageNav } from "./Workspace";

export function BidScrutiny() {
  const { bidId = "" } = useParams();
  const [params] = useSearchParams();
  const { has } = useAuth();
  const q = useQuery({ queryKey: ["bid", bidId], queryFn: () => get<BidDetail>(`/bids/${bidId}`) });
  const [page, setPage] = useState(1);
  const [fieldKey, setFieldKey] = useState<string | null>(params.get("field"));
  const [dialog, setDialog] = useState<null | "release" | "classify">(null);

  useEffect(() => {
    const p = Number(params.get("page"));
    if (p) setPage(p);
  }, [params]);
  const d = q.data;
  const field = d?.fields.find((f) => f.field_key === fieldKey) ?? null;
  useEffect(() => {
    if (field?.page_no) setPage(field.page_no);
  }, [field?.id, field?.page_no]);

  if (q.isLoading) return <OfficerShell><Loading /></OfficerShell>;
  if (!d) return <OfficerShell><ErrorBanner error={q.error} /></OfficerShell>;
  const current = d.pages.find((p) => p.page_no === page);
  const highlight = field && field.page_no === page ? field.bbox : null;

  return (
    <OfficerShell context={<BidContext detail={d} />}>
      <div className="tender-head">
        <div>
          <div className="mono muted">{d.bid.bid_reference}</div>
          <h1>{d.bid.bidder_legal_name}</h1>
          <div className="muted small">
            Received {formatDateTime(d.bid.submitted_at)} · {d.technical_filename} · SHA-256{" "}
            <span className="mono" title={d.technical_sha256 ?? ""}>
              {shortHash(d.technical_sha256)}
            </span>
          </div>
        </div>
        <div className="stack-h">
          <StatusBadge status={d.bid.processing_status} />
          <StatusBadge status={d.bid.technical_outcome} />
        </div>
      </div>
      <ErrorBanner error={q.error} />
      <div className="scrutiny">
        <aside className="pane pages" aria-label="Pages">
          <h2>Pages</h2>
          <ol>
            {d.pages.map((p) => (
              <li key={p.page_no}>
                <button className={`pagebtn ${p.page_no === page ? "active" : ""}`} onClick={() => setPage(p.page_no)}>
                  <span className="mono">p.{p.page_no}</span>{" "}
                  {p.text_status !== "TEXT_LAYER" ? (
                    <StatusBadge status={p.text_status} label={p.text_status === "NO_TEXT_LAYER" ? "Scanned" : "Withheld"} />
                  ) : (
                    <span className="small">{p.doc_class ? humanize(p.doc_class) : <em>Unclassified</em>}</span>
                  )}
                  {p.classification_method === "OFFICER" && <span className="small muted"> (officer)</span>}
                  {p.classification_method === "CONTINUATION" && <span className="small muted"> (cont.)</span>}
                </button>
              </li>
            ))}
          </ol>
          <h2>Documents</h2>
          <ul className="doclist">
            {d.documents.map((doc) => (
              <li key={doc.doc_class}>
                <StatusBadge status={doc.presence} label={doc.presence === "UNCERTAIN" ? "Uncertain" : undefined} />{" "}
                {doc.name}
                {doc.pages.length > 0 && <span className="muted small"> p.{doc.pages.join(", ")}</span>}
                {!doc.mandatory && <span className="muted small"> (if applicable)</span>}
              </li>
            ))}
          </ul>
        </aside>

        <section className="pane viewer" aria-label="Document viewer">
          <PageNav page={page} pages={d.pages.length} onChange={setPage} />
          {current && (
            <>
              <div className="small muted">
                Classification: {current.doc_class ? humanize(current.doc_class) : "none"} (
                {humanize(current.classification_method)}
                {current.classification_confidence !== null ? `, ${current.classification_confidence.toFixed(2)}` : ""}
                {current.matched_keywords.length ? `; matched: ${current.matched_keywords.join(", ")}` : ""})
                {has("TECHNICAL_EVALUATOR") && current.text_status !== "WITHHELD_COMMERCIAL" && (
                  <button className="btn btn-small" onClick={() => setDialog("classify")}>
                    Reclassify page
                  </button>
                )}
              </div>
              {current.text_status === "WITHHELD_COMMERCIAL" && (
                <Notice kind="sealed">
                  Indicators: {current.leakage_indicators.join(", ")}.{" "}
                  {has("APPROVER") ? (
                    <button className="btn btn-small btn-danger" onClick={() => setDialog("release")}>
                      Release page (accept exposure risk)
                    </button>
                  ) : (
                    "Only an approver can release this page."
                  )}
                </Notice>
              )}
              {current.text_status === "NO_TEXT_LAYER" && (
                <Notice kind="warn">
                  Scanned page without a text layer. Values on this page must be read and entered by an officer.
                </Notice>
              )}
              <EvidencePage
                path={`/bids/${bidId}/pages/${page}/image`}
                pageNo={page}
                width={current.width}
                height={current.height}
                highlight={highlight}
              />
            </>
          )}
        </section>

        <section className="pane fields" aria-label="Extracted fields">
          <h2>Extracted fields</h2>
          <table className="table compact">
            <thead>
              <tr>
                <th scope="col">Field</th>
                <th scope="col">Value</th>
                <th scope="col">Status</th>
              </tr>
            </thead>
            <tbody>
              {d.fields.map((f) => (
                <tr
                  key={f.id}
                  className={f.field_key === fieldKey ? "selected" : ""}
                  onClick={() => setFieldKey(f.field_key)}
                >
                  <td>
                    <button className="linklike" onClick={() => setFieldKey(f.field_key)}>
                      {f.label}
                    </button>
                  </td>
                  <td className="mono small">
                    {f.normalized_value ?? "—"} {f.normalized_value && f.unit ? f.unit : ""}
                  </td>
                  <td>
                    <StatusBadge status={f.review_state === "PENDING_REVIEW" ? "PENDING_REVIEW" : f.status} />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          {field && <FieldPanel bidId={bidId} field={field} onJump={setPage} />}
        </section>
      </div>
      {current && (
        <>
          <ReasonDialog
            open={dialog === "release"}
            title={`Release withheld page ${page}`}
            description="Releasing makes the page content (which may contain prices) visible to officers before commercial opening. This acceptance of exposure risk is recorded against your identity."
            confirmLabel="Release page"
            danger
            minLength={10}
            onClose={() => setDialog(null)}
            onConfirm={async (reason) => {
              await post(`/bids/${bidId}/pages/${page}/release`, { reason });
              await q.refetch();
            }}
          />
          <ClassifyDialog
            open={dialog === "classify"}
            bidId={bidId}
            page={page}
            current={current.doc_class}
            onClose={() => setDialog(null)}
          />
        </>
      )}
    </OfficerShell>
  );
}

function BidContext({ detail }: { detail: BidDetail }) {
  const tid = detail.bid.tender_id;
  return (
    <div className="subnav">
      <div className="subnav-title">Bid scrutiny</div>
      <Link to={`/officer/tenders/${tid}/bids`}>← Bid submissions</Link>
      <Link to={`/officer/tenders/${tid}/review`}>Review queue</Link>
      <Link to={`/officer/tenders/${tid}/evaluation`}>Technical evaluation</Link>
      <BidTasks tenderId={tid} bidId={detail.bid.id} />
    </div>
  );
}

function BidTasks({ tenderId, bidId }: { tenderId: string; bidId: string }) {
  const { has } = useAuth();
  const qc = useQueryClient();
  const q = useQuery({
    queryKey: ["review", tenderId, "OPEN"],
    queryFn: () => get<Paged<ReviewTask>>(`/tenders/${tenderId}/review-tasks?status=OPEN&limit=500`),
  });
  const [ack, setAck] = useState<ReviewTask | null>(null);
  const mine = q.data?.items.filter((t) => t.bid_id === bidId) ?? [];
  return (
    <div className="bidtasks">
      <div className="subnav-title">Open review tasks ({mine.length})</div>
      {mine.map((t) => (
        <div key={t.id} className="small task">
          <strong>{humanize(t.reason)}</strong> {t.field_key ?? (t.page_no ? `p.${t.page_no}` : "")}
          {!t.field_key && has(t.reason === "POSSIBLE_COMMERCIAL_LEAKAGE" ? "APPROVER" : "TECHNICAL_EVALUATOR") && (
            <button className="btn btn-small" onClick={() => setAck(t)}>
              {t.reason === "POSSIBLE_COMMERCIAL_LEAKAGE" ? "Keep withheld" : "Acknowledge"}
            </button>
          )}
        </div>
      ))}
      <ReasonDialog
        open={Boolean(ack)}
        title="Resolve review task"
        description={ack?.detail}
        confirmLabel="Resolve"
        onClose={() => setAck(null)}
        onConfirm={async (resolution) => {
          await post(`/review-tasks/${ack?.id}/acknowledge`, { resolution });
          await qc.invalidateQueries();
        }}
      />
    </div>
  );
}

function ClassifyDialog({
  open,
  bidId,
  page,
  current,
  onClose,
}: {
  open: boolean;
  bidId: string;
  page: number;
  current: string | null;
  onClose: () => void;
}) {
  const qc = useQueryClient();
  const bid = qc.getQueryData<BidDetail>(["bid", bidId]);
  const [docClass, setDocClass] = useState<string>(current ?? "");
  useEffect(() => setDocClass(current ?? ""), [current, open]);
  return (
    <ReasonDialog
      open={open}
      title={`Reclassify page ${page}`}
      confirmLabel="Save classification"
      onClose={onClose}
      onConfirm={async (reason) => {
        const out = await post<BidDetail>(`/bids/${bidId}/pages/${page}/classification`, {
          doc_class: docClass || null,
          reason,
        });
        qc.setQueryData(["bid", bidId], out);
      }}
    >
      <label className="field">
        <span>Document class</span>
        <select value={docClass} onChange={(e) => setDocClass(e.target.value)}>
          <option value="">Unclassified / other</option>
          {bid?.documents.map((d) => (
            <option key={d.doc_class} value={d.doc_class}>
              {d.name}
            </option>
          ))}
        </select>
      </label>
    </ReasonDialog>
  );
}

function FieldPanel({ bidId, field, onJump }: { bidId: string; field: ExtractedField; onJump: (p: number) => void }) {
  const { has } = useAuth();
  const qc = useQueryClient();
  const [showHistory, setShowHistory] = useState(false);
  const history = useQuery({
    queryKey: ["history", bidId, field.field_key, field.id],
    queryFn: () => get<ExtractedField[]>(`/bids/${bidId}/fields/${field.field_key}/history`),
    enabled: showHistory,
  });
  const [action, setAction] = useState<"VERIFY" | "CORRECT" | "CONFIRM_MISSING" | "MARK_UNREADABLE">("CORRECT");
  const [value, setValue] = useState("");
  const [pageNo, setPageNo] = useState<string>(field.page_no ? String(field.page_no) : "");
  const [reason, setReason] = useState("");
  useEffect(() => {
    setValue("");
    setReason("");
    setPageNo(field.page_no ? String(field.page_no) : "");
    setAction(field.status === "EXTRACTED" && field.review_state === "PENDING_REVIEW" ? "VERIFY" : "CORRECT");
  }, [field.id, field.page_no, field.status, field.review_state]);
  const save = useMutation({
    mutationFn: () =>
      post<BidDetail>(`/bids/${bidId}/fields/${field.field_key}/revisions`, {
        action,
        value: action === "CORRECT" ? value : null,
        page_no: pageNo ? Number(pageNo) : null,
        reason,
      }),
    onSuccess: (out) => {
      qc.setQueryData(["bid", bidId], out);
      qc.invalidateQueries({ queryKey: ["review"] });
    },
  });
  const officer = field.review_state === "OFFICER_VERIFIED" || field.review_state === "OFFICER_CORRECTED";
  return (
    <div className="card field-panel">
      <h3>
        {field.label} <span className="mono small muted">{field.field_key}</span>
      </h3>
      <p>
        <ProvenanceTag kind={officer ? "officer" : "auto"} /> <span className="small">{field.provenance}</span>
      </p>
      <KeyValue
        items={[
          ["Status", <StatusBadge status={field.status} />],
          ["Raw text (exact)", field.raw_value ? <span className="mono">“{field.raw_value}”</span> : "—"],
          ["Source line", field.source_line ? <span className="mono small">{field.source_line}</span> : "—"],
          ["Normalized", field.normalized_value ? `${field.normalized_value} ${field.unit ?? ""}` : "—"],
          [
            "Evidence",
            field.page_no ? (
              <button className="linklike" onClick={() => onJump(field.page_no ?? 1)}>
                Page {field.page_no}
                {field.bbox ? " (region highlighted)" : ""}
              </button>
            ) : (
              "—"
            ),
          ],
          ["Method / confidence", `${field.method}${field.confidence !== null ? ` · ${field.confidence.toFixed(2)}` : ""}`],
          ["Flags", field.flags.length ? field.flags.join(", ") : "—"],
          ["Revision", `#${field.revision_no} by ${field.created_by_label}, ${formatDateTime(field.created_at)}`],
        ]}
      />
      {field.reason && <p className="small">Officer reason: {field.reason}</p>}
      {field.candidates.length > 1 && (
        <div>
          <h4>All candidate readings (not reconciled automatically)</h4>
          <ul className="small">
            {field.candidates.map((c, i) => (
              <li key={i}>
                <button className="linklike" onClick={() => onJump(c.page_no)}>
                  p.{c.page_no}
                </button>{" "}
                “{c.raw_value}” → {c.normalized ?? "unparseable"} {c.flags.length ? `[${c.flags.join(", ")}]` : ""}
              </li>
            ))}
          </ul>
        </div>
      )}
      {has("TECHNICAL_EVALUATOR") && (
        <form
          className="form"
          onSubmit={(e) => {
            e.preventDefault();
            save.mutate();
          }}
        >
          <h4>Officer review</h4>
          <label className="field">
            <span>Action</span>
            <select value={action} onChange={(e) => setAction(e.target.value as typeof action)}>
              <option value="VERIFY" disabled={field.status !== "EXTRACTED"}>
                Verify extracted value
              </option>
              <option value="CORRECT">Enter / correct value from document</option>
              <option value="CONFIRM_MISSING">Confirm not present in submission</option>
              <option value="MARK_UNREADABLE">Mark illegible / unreadable</option>
            </select>
          </label>
          {action === "CORRECT" && (
            <label className="field">
              <span>Value exactly as written in the document</span>
              <input value={value} onChange={(e) => setValue(e.target.value)} required />
            </label>
          )}
          {(action === "CORRECT" || action === "MARK_UNREADABLE") && (
            <label className="field">
              <span>Evidence page number</span>
              <input
                type="number"
                min={1}
                value={pageNo}
                onChange={(e) => setPageNo(e.target.value)}
                required={action === "CORRECT"}
              />
            </label>
          )}
          <label className="field">
            <span>Reason (audited)</span>
            <textarea rows={2} minLength={5} required value={reason} onChange={(e) => setReason(e.target.value)} />
          </label>
          <ErrorBanner error={save.error} />
          <button className="btn btn-primary" disabled={save.isPending || reason.trim().length < 5}>
            Save new revision
          </button>
          <p className="muted small">The previous revision and the original automated extraction are preserved.</p>
        </form>
      )}
      <button className="linklike small" onClick={() => setShowHistory((s) => !s)}>
        {showHistory ? "Hide" : "Show"} revision history
      </button>
      {showHistory && history.data && (
        <ol className="history small">
          {history.data.map((h) => (
            <li key={h.id}>
              #{h.revision_no} {h.status} {h.normalized_value ?? ""} — {h.provenance} — {h.created_by_label},{" "}
              {formatDateTime(h.created_at)}
              {h.reason ? ` — “${h.reason}”` : ""}
            </li>
          ))}
        </ol>
      )}
    </div>
  );
}

