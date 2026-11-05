import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { get, post, put } from "../../api/client";
import type { RulebookContent, RulebookVersion, Tender, ValidationIssue } from "../../api/types";
import { ErrorBanner, Loading, Notice, ReasonDialog, StatusBadge } from "../../components/ui";
import { useAuth } from "../../lib/auth";
import { formatDateTime, humanize, shortHash } from "../../lib/format";

function display(v: unknown): string {
  if (v === null || v === undefined) return "—";
  if (Array.isArray(v)) return v.map(display).join(", ");
  return String(v);
}

export function RulebookTab({ t }: { t: Tender }) {
  const { has } = useAuth();
  const qc = useQueryClient();
  const versions = useQuery({
    queryKey: ["rulebooks", t.id],
    queryFn: () => get<RulebookVersion[]>(`/tenders/${t.id}/rulebook/versions`),
  });
  const [selected, setSelected] = useState<string | null>(null);
  const [dialog, setDialog] = useState<null | "submit" | "approve" | "request-changes" | "pin">(null);
  useEffect(() => {
    if (!selected && versions.data?.length) {
      setSelected((versions.data.find((v) => v.is_pinned) ?? versions.data[0])?.id ?? null);
    }
  }, [versions.data, selected]);
  const rv = versions.data?.find((v) => v.id === selected);
  const editable = ["DRAFT", "OPEN_FOR_SUBMISSION"].includes(t.status);

  const create = useMutation({
    mutationFn: (basedOn: string | null) =>
      post<RulebookVersion>(`/tenders/${t.id}/rulebook/versions`, { based_on_id: basedOn }),
    onSuccess: (v) => {
      qc.invalidateQueries({ queryKey: ["rulebooks", t.id] });
      setSelected(v.id);
    },
  });

  return (
    <section>
      <div className="toolbar">
        <label className="field inline">
          <span>Version</span>
          <select value={selected ?? ""} onChange={(e) => setSelected(e.target.value)}>
            {versions.data?.map((v) => (
              <option key={v.id} value={v.id}>
                v{v.version_no} — {humanize(v.status)}
                {v.is_pinned ? " (pinned for evaluation)" : ""}
              </option>
            ))}
          </select>
        </label>
        {has("TENDER_ADMIN") && editable && (
          <>
            <button className="btn" onClick={() => create.mutate(rv?.id ?? null)} disabled={create.isPending}>
              New draft {rv ? `based on v${rv.version_no}` : ""}
            </button>
            {rv?.status === "DRAFT" && (
              <button className="btn btn-primary" onClick={() => setDialog("submit")}>
                Submit for approval
              </button>
            )}
            {rv?.status === "APPROVED" && !rv.is_pinned && (
              <button className="btn btn-primary" onClick={() => setDialog("pin")}>
                Pin for evaluation
              </button>
            )}
          </>
        )}
        {has("APPROVER") && rv?.status === "IN_REVIEW" && (
          <>
            <button className="btn btn-primary" onClick={() => setDialog("approve")}>
              Approve version
            </button>
            <button className="btn" onClick={() => setDialog("request-changes")}>
              Request changes
            </button>
          </>
        )}
      </div>
      <ErrorBanner error={versions.error ?? create.error} />
      {versions.isLoading && <Loading />}
      {versions.data?.length === 0 && <Notice>No rulebook versions yet. Create a draft to begin.</Notice>}
      {rv && <VersionView rv={rv} canEdit={has("TENDER_ADMIN") && rv.status === "DRAFT"} />}
      <ReasonDialog
        open={dialog !== null}
        title={
          {
            submit: "Submit rulebook for approval",
            approve: "Approve rulebook version",
            "request-changes": "Return rulebook for changes",
            pin: "Pin version for evaluation",
          }[dialog ?? "submit"]
        }
        description={
          dialog === "approve"
            ? "Approval freezes this version. Every bid will be evaluated against exactly this content. You cannot approve a version you authored or edited."
            : dialog === "pin"
              ? "All bids for this tender will be evaluated against the pinned version. It cannot change after submissions close."
              : undefined
        }
        confirmLabel={dialog === "approve" ? "Approve" : "Confirm"}
        minLength={3}
        onClose={() => setDialog(null)}
        onConfirm={async (reason) => {
          if (!rv) return;
          if (dialog === "pin") await post(`/tenders/${t.id}/rulebook/pin`, { version_id: rv.id, reason });
          else await post(`/rulebook-versions/${rv.id}/${dialog}`, { reason });
          await qc.invalidateQueries();
        }}
      />
    </section>
  );
}

function Issues({ issues }: { issues: ValidationIssue[] }) {
  if (issues.length === 0) return <Notice>No validation issues.</Notice>;
  return (
    <div className="card">
      <h3>Validation ({issues.filter((i) => i.severity === "BLOCKING").length} blocking)</h3>
      <ul className="issues">
        {issues.map((i, n) => (
          <li key={n}>
            <StatusBadge status={i.severity === "BLOCKING" ? "FAIL" : "PENDING_REVIEW"} label={i.severity} />{" "}
            <span className="mono small">{i.code}</span> {i.message} <span className="muted small">({i.path})</span>
          </li>
        ))}
      </ul>
    </div>
  );
}

function VersionView({ rv, canEdit }: { rv: RulebookVersion; canEdit: boolean }) {
  const [editing, setEditing] = useState(false);
  const c = rv.content;
  const fields = Object.fromEntries(c.fields.map((f) => [f.field_key, f]));
  return (
    <>
      <div className="meta-line">
        <StatusBadge status={rv.status} /> v{rv.version_no} · content hash{" "}
        <span className="mono small" title={rv.content_hash}>
          {shortHash(rv.content_hash)}
        </span>
        {rv.approved_at && <> · approved {formatDateTime(rv.approved_at)} — “{rv.approval_reason}”</>}
        {canEdit && (
          <button className="btn btn-small" onClick={() => setEditing((e) => !e)}>
            {editing ? "Close editor" : "Edit draft (JSON)"}
          </button>
        )}
      </div>
      <Issues issues={rv.issues} />
      {editing && canEdit && <JsonEditor rv={rv} onSaved={() => setEditing(false)} />}

      <h2>Criteria ({c.criteria.length})</h2>
      <div className="table-wrap">
        <table className="table sticky">
          <thead>
            <tr>
              <th scope="col">ID</th>
              <th scope="col">Criterion</th>
              <th scope="col">Category</th>
              <th scope="col">Mandatory</th>
              <th scope="col">Rule</th>
              <th scope="col">Applies if</th>
              <th scope="col">Failure consequence</th>
              <th scope="col">Tender source</th>
            </tr>
          </thead>
          <tbody>
            {c.criteria.map((cr) => (
              <tr key={cr.criterion_id}>
                <td className="mono small">{cr.criterion_id}</td>
                <td>
                  {cr.name}
                  {cr.interpretation !== "explicit" && (
                    <div className="muted small">Interpretation: {humanize(cr.interpretation)}</div>
                  )}
                </td>
                <td>{humanize(cr.category)}</td>
                <td>{cr.mandatory ? "Yes" : "No"}</td>
                <td className="small">
                  {cr.operator === "DOCUMENT_PRESENT" ? (
                    <>Document present: {c.document_requirements.find((d) => d.doc_class === cr.doc_class)?.name}</>
                  ) : cr.operator === "MANUAL_REVIEW_REQUIRED" ? (
                    "Officer judgement required"
                  ) : (
                    <>
                      {fields[cr.field_key ?? ""]?.label ?? cr.field_key} <strong>{cr.operator}</strong>{" "}
                      {cr.evaluation_date_basis ? humanize(cr.evaluation_date_basis) : display(cr.expected)}{" "}
                      {fields[cr.field_key ?? ""]?.unit ?? ""}
                    </>
                  )}
                </td>
                <td className="small">
                  {cr.applies_if
                    ? `${cr.applies_if.field_key} ${cr.applies_if.operator} ${display(cr.applies_if.value)} (if unknown: ${humanize(cr.applies_if.if_unknown)})`
                    : "Always"}
                </td>
                <td className="small">{humanize(cr.failure_consequence)}</td>
                <td className="small">
                  {cr.source_references.map((s, i) => (
                    <div key={i}>
                      {s.document_title}, p.{s.page}
                      {s.clause ? `, cl. ${s.clause}` : ""}
                      {s.quote && <div className="quote">“{s.quote}”</div>}
                    </div>
                  ))}
                  {cr.source_references.length === 0 && <StatusBadge status="MISSING" label="No source" />}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <div className="grid2">
        <div>
          <h2>Required documents</h2>
          <table className="table">
            <thead>
              <tr>
                <th scope="col">Document</th>
                <th scope="col">Class</th>
                <th scope="col">Mandatory</th>
                <th scope="col">Identification keywords</th>
              </tr>
            </thead>
            <tbody>
              {c.document_requirements.map((d) => (
                <tr key={d.doc_class}>
                  <td>{d.name}</td>
                  <td className="mono small">{d.doc_class}</td>
                  <td>{d.mandatory ? "Yes" : "If applicable"}</td>
                  <td className="small">{d.keywords.join("; ")}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <div>
          <h2>Extraction fields</h2>
          <table className="table">
            <thead>
              <tr>
                <th scope="col">Field</th>
                <th scope="col">Type / unit</th>
                <th scope="col">Label aliases (hints, not proof)</th>
                <th scope="col">Searched in</th>
              </tr>
            </thead>
            <tbody>
              {c.fields.map((f) => (
                <tr key={f.field_key}>
                  <td>
                    {f.label}
                    <div className="mono small muted">{f.field_key}</div>
                  </td>
                  <td>
                    {f.data_type}
                    {f.unit ? ` (${f.unit})` : ""}
                  </td>
                  <td className="small">{f.aliases.join("; ")}</td>
                  <td className="small mono">{(f.doc_classes ?? []).join(", ") || "all pages"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </>
  );
}

function JsonEditor({ rv, onSaved }: { rv: RulebookVersion; onSaved: () => void }) {
  const qc = useQueryClient();
  const [text, setText] = useState(() => JSON.stringify(rv.content, null, 2));
  const [parseError, setParseError] = useState<string | null>(null);
  const parse = (): RulebookContent | null => {
    try {
      setParseError(null);
      return JSON.parse(text) as RulebookContent;
    } catch (e) {
      setParseError(String(e));
      return null;
    }
  };
  const validate = useMutation({ mutationFn: (c: RulebookContent) => post<ValidationIssue[]>("/rulebook/validate", c) });
  const save = useMutation({
    mutationFn: (c: RulebookContent) =>
      put<RulebookVersion>(`/rulebook-versions/${rv.id}/content`, { content: c, row_version: rv.row_version }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["rulebooks", rv.tender_id] });
      onSaved();
    },
  });
  return (
    <div className="card">
      <h3>Edit draft v{rv.version_no}</h3>
      <p className="muted small">
        Numeric thresholds must be strings (e.g. &quot;50000000&quot;) to preserve exact decimal values. Scoring
        weights are not accepted unless defined by the tender (not supported in this MVP).
      </p>
      <textarea
        className="code"
        rows={24}
        spellCheck={false}
        value={text}
        onChange={(e) => setText(e.target.value)}
        aria-label="Rulebook JSON"
      />
      {parseError && <div className="alert alert-error">{parseError}</div>}
      <ErrorBanner error={validate.error ?? save.error} />
      {validate.data && <Issues issues={validate.data} />}
      <div className="toolbar">
        <button className="btn" onClick={() => { const c = parse(); if (c) validate.mutate(c); }}>
          Validate
        </button>
        <button className="btn btn-primary" onClick={() => { const c = parse(); if (c) save.mutate(c); }}>
          Save draft
        </button>
      </div>
    </div>
  );
}
