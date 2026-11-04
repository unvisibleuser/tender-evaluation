import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { get, post } from "../../api/client";
import type { BidResults, EvaluationRun, RunSummary, Tender } from "../../api/types";
import { ErrorBanner, Notice, ProvenanceTag, ReasonDialog, StatusBadge } from "../../components/ui";
import { useAuth } from "../../lib/auth";
import { formatDateTime, shortHash } from "../../lib/format";
import { SealedTechnical } from "./Workspace";

const OK = new Set(["PASS", "NOT_APPLICABLE"]);

export function EvaluationTab({ t }: { t: Tender }) {
  const { has } = useAuth();
  const qc = useQueryClient();
  const runs = useQuery({
    queryKey: ["runs", t.id],
    queryFn: () => get<RunSummary[]>(`/tenders/${t.id}/evaluation-runs`),
    enabled: !["DRAFT", "OPEN_FOR_SUBMISSION"].includes(t.status),
  });
  const [runId, setRunId] = useState<string | null>(null);
  useEffect(() => {
    if (runs.data?.[0] && (!runId || !runs.data.some((r) => r.id === runId))) setRunId(runs.data[0].id);
  }, [runs.data, runId]);
  const run = useQuery({
    queryKey: ["run", runId],
    queryFn: () => get<EvaluationRun>(`/evaluation-runs/${runId}`),
    enabled: Boolean(runId),
  });
  const start = useMutation({
    mutationFn: () => post<EvaluationRun>(`/tenders/${t.id}/evaluation-runs`),
    onSuccess: (r) => {
      qc.invalidateQueries({ queryKey: ["runs", t.id] });
      setRunId(r.id);
    },
  });
  const [deciding, setDeciding] = useState<BidResults | null>(null);
  const [cell, setCell] = useState<{ bid: string; crit: string } | null>(null);

  return (
    <SealedTechnical t={t}>
      {t.status === "SUBMISSION_CLOSED" && (
        <Notice>Start the technical evaluation stage (Overview tab) to run deterministic evaluation.</Notice>
      )}
      <div className="toolbar">
        {has("TECHNICAL_EVALUATOR") && t.status === "TECHNICAL_EVALUATION" && (
          <button className="btn btn-primary" onClick={() => start.mutate()} disabled={start.isPending}>
            Run deterministic evaluation (all bids)
          </button>
        )}
        {runs.data && runs.data.length > 0 && (
          <label className="field inline">
            <span>Run</span>
            <select value={runId ?? ""} onChange={(e) => setRunId(e.target.value)}>
              {runs.data.map((r, i) => (
                <option key={r.id} value={r.id}>
                  {formatDateTime(r.created_at)} · {r.started_by_label} · {shortHash(r.result_hash)}
                  {i === 0 ? " (latest)" : ""}
                </option>
              ))}
            </select>
          </label>
        )}
      </div>
      <ErrorBanner error={start.error ?? run.error} />
      {run.data && (
        <>
          <div className="meta-line">
            <ProvenanceTag kind="rule" /> Rulebook hash <span className="mono small">{shortHash(run.data.rulebook_content_hash)}</span>
            · engine v{run.data.engine_version} · input <span className="mono small">{shortHash(run.data.input_hash)}</span>
            · result <span className="mono small">{shortHash(run.data.result_hash)}</span>
            · {run.data.bid_count} bids evaluated against the same pinned rulebook
          </div>
          <Notice>
            Rule outcomes are observations from the approved rulebook. <strong>MISSING, UNREADABLE, AMBIGUOUS and
            PENDING</strong> are not failures. A bid&apos;s technical outcome is set only by an approver&apos;s recorded
            decision.
          </Notice>
          <div className="table-wrap">
            <table className="table matrix sticky">
              <thead>
                <tr>
                  <th scope="col">Criterion</th>
                  {run.data.bids.map((b) => (
                    <th scope="col" key={b.bid_id}>
                      <Link to={`/officer/bids/${b.bid_id}`}>{b.bidder_legal_name}</Link>
                      <div className="mono small muted">{b.bid_reference}</div>
                      {b.stale && <StatusBadge status="PENDING_REVIEW" label="Evidence changed — re-run" />}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {run.data.criteria.map((c) => (
                  <tr key={c.criterion_id}>
                    <th scope="row">
                      <span className="mono small">{c.criterion_id}</span>
                      <div>{c.name}</div>
                      <div className="muted small">
                        {c.mandatory ? "Mandatory" : "Optional"} · {c.source}
                      </div>
                    </th>
                    {run.data.bids.map((b) => {
                      const r = b.results.find((x) => x.criterion_id === c.criterion_id);
                      const open = cell?.bid === b.bid_id && cell.crit === c.criterion_id;
                      return (
                        <td key={b.bid_id}>
                          {r && (
                            <button
                              className="cellbtn"
                              aria-expanded={open}
                              onClick={() => setCell(open ? null : { bid: b.bid_id, crit: c.criterion_id })}
                            >
                              <StatusBadge status={r.outcome} />
                              {r.actual && <div className="small mono">{r.actual}</div>}
                            </button>
                          )}
                          {r && open && <div className="explain small">{r.explanation}</div>}
                        </td>
                      );
                    })}
                  </tr>
                ))}
                <tr>
                  <th scope="row">Officer decision</th>
                  {run.data.bids.map((b) => (
                    <td key={b.bid_id}>
                      {b.decision ? (
                        <div>
                          <ProvenanceTag kind="decision" /> <StatusBadge status={b.decision.decision} />
                          <div className="small">{b.decision.reason}</div>
                          <div className="muted small">
                            {b.decision.decided_by_label}, {formatDateTime(b.decision.decided_at)}
                          </div>
                          {b.decision.overridden_criteria.length > 0 && (
                            <div className="small">Override acknowledged: {b.decision.overridden_criteria.join(", ")}</div>
                          )}
                        </div>
                      ) : (
                        <StatusBadge status="PENDING_OFFICER_DECISION" />
                      )}
                      {has("APPROVER") && t.status === "TECHNICAL_EVALUATION" && run.data?.is_latest && (
                        <button className="btn btn-small" onClick={() => setDeciding(b)} disabled={b.stale}>
                          {b.decision ? "Revise decision" : "Record decision"}
                        </button>
                      )}
                    </td>
                  ))}
                </tr>
              </tbody>
            </table>
          </div>
        </>
      )}
      {runs.data?.length === 0 && t.status === "TECHNICAL_EVALUATION" && <Notice>No evaluation runs yet.</Notice>}
      {deciding && run.data && (
        <DecisionDialog bid={deciding} runId={run.data.id} onClose={() => setDeciding(null)} />
      )}
    </SealedTechnical>
  );
}

function DecisionDialog({ bid, runId, onClose }: { bid: BidResults; runId: string; onClose: () => void }) {
  const qc = useQueryClient();
  const [decision, setDecision] = useState<"RESPONSIVE" | "NON_RESPONSIVE">("RESPONSIVE");
  const notOk = bid.results.filter((r) => r.mandatory && !OK.has(r.outcome));
  const [cited, setCited] = useState<string[]>(notOk.filter((r) => r.outcome === "FAIL").map((r) => r.criterion_id));
  const [ack, setAck] = useState(false);
  return (
    <ReasonDialog
      open
      title={`Technical decision — ${bid.bidder_legal_name}`}
      description={<span>This is an officer decision and will be recorded with your identity in the audit trail.</span>}
      confirmLabel="Record decision"
      minLength={10}
      onClose={onClose}
      onConfirm={async (reason) => {
        await post(`/bids/${bid.bid_id}/technical-decision`, {
          decision,
          evaluation_run_id: runId,
          reason,
          cited_criteria: cited,
          override_acknowledged: ack,
        });
        await qc.invalidateQueries();
      }}
    >
      <fieldset className="field">
        <legend>Decision</legend>
        {(["RESPONSIVE", "NON_RESPONSIVE"] as const).map((d) => (
          <label key={d} className="check">
            <input type="radio" name="decision" checked={decision === d} onChange={() => setDecision(d)} />
            <span>{d === "RESPONSIVE" ? "Technically responsive" : "Not technically responsive"}</span>
          </label>
        ))}
      </fieldset>
      <fieldset className="field">
        <legend>Criteria cited {decision === "NON_RESPONSIVE" ? "(required)" : "(optional)"}</legend>
        <div className="cite-list">
          {bid.results.map((r) => (
            <label key={r.criterion_id} className="check small">
              <input
                type="checkbox"
                checked={cited.includes(r.criterion_id)}
                onChange={(e) =>
                  setCited((c) => (e.target.checked ? [...c, r.criterion_id] : c.filter((x) => x !== r.criterion_id)))
                }
              />
              <span>
                <span className="mono">{r.criterion_id}</span> <StatusBadge status={r.outcome} />
              </span>
            </label>
          ))}
        </div>
      </fieldset>
      {decision === "RESPONSIVE" && notOk.length > 0 && (
        <label className="check alert alert-warn">
          <input type="checkbox" checked={ack} onChange={(e) => setAck(e.target.checked)} />
          <span>
            I acknowledge that mandatory criteria {notOk.map((r) => r.criterion_id).join(", ")} are not PASS and I am
            overriding them with the reasons below (e.g. committee examination of type-test reports).
          </span>
        </label>
      )}
    </ReasonDialog>
  );
}
