import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ApiError, fetchBlobUrl, get, post } from "../../api/client";
import type { CommercialStatus, Offer, Ranking, Tender } from "../../api/types";
import { ErrorBanner, KeyValue, Notice, ProvenanceTag, ReasonDialog, StatusBadge } from "../../components/ui";
import { useAuth } from "../../lib/auth";
import { formatDateTime, formatInr } from "../../lib/format";

const OPENED = ["COMMERCIAL_OPENED", "COMMERCIAL_EVALUATED"];

export function CommercialTab({ t }: { t: Tender }) {
  const { has } = useAuth();
  // Technical roles never request commercial endpoints at all (server also refuses with 403).
  if (!has("COMMERCIAL_OFFICER", "AUDITOR"))
    return (
      <Notice kind="sealed">
        🔒 Commercial information is restricted to commercial opening officers and auditors. Your role has no access
        to price bids at any stage.
      </Notice>
    );
  return <CommercialInner t={t} />;
}

function CommercialInner({ t }: { t: Tender }) {
  const { has } = useAuth();
  const qc = useQueryClient();
  const opened = OPENED.includes(t.status);
  const status = useQuery({
    queryKey: ["commercial-status", t.id],
    queryFn: () => get<CommercialStatus>(`/tenders/${t.id}/commercial/status`),
  });
  const offers = useQuery({
    queryKey: ["offers", t.id],
    queryFn: () => get<Offer[]>(`/tenders/${t.id}/commercial/offers`),
    enabled: opened,
    gcTime: 0, // do not keep price data in the client cache after leaving the view
  });
  const ranking = useQuery({
    queryKey: ["ranking", t.id],
    queryFn: () => get<Ranking | null>(`/tenders/${t.id}/commercial/ranking`),
    enabled: opened,
    gcTime: 0,
  });
  const evaluate = useMutation({
    mutationFn: () => post<Ranking>(`/tenders/${t.id}/commercial/evaluation`),
    onSuccess: () => qc.invalidateQueries(),
  });
  const [dialog, setDialog] = useState<null | "authorize" | "open">(null);
  const s = status.data;

  return (
    <section>
      <ErrorBanner error={status.error} />
      {s && (
        <div className="grid2">
          <div className="card">
            <h2>
              Commercial envelopes <StatusBadge status={s.sealed ? "SEALED" : "RESOLVED"} label={s.sealed ? "Sealed" : "Opened"} />
            </h2>
            <KeyValue
              items={[
                ["Envelopes received", String(s.envelopes_received)],
                ["Bids eligible (officer-recorded RESPONSIVE)", String(s.eligible_bids)],
                ["Opening quorum", `${s.authorizations.length} of ${s.quorum} distinct officers authorised`],
                ["Opened", s.opened_at ? `${formatDateTime(s.opened_at)} by ${s.opened_by}` : "Not opened"],
                ["Evaluation method", s.evaluation_method ?? "REQUIRES OFFICER CONFIGURATION"],
              ]}
            />
            {s.sealed && t.status !== "TECHNICAL_COMPLETED" && (
              <Notice kind="sealed">
                Opening becomes available only after technical evaluation is completed for all bids.
              </Notice>
            )}
          </div>
          <div className="card">
            <h2>Opening authorisations (dual control)</h2>
            <ul>
              {s.authorizations.map((a) => (
                <li key={a.officer_id}>
                  <strong>{a.officer_label}</strong> — {formatDateTime(a.created_at)} — “{a.reason}”
                </li>
              ))}
              {s.authorizations.length === 0 && <li className="muted">None yet</li>}
            </ul>
            <div className="toolbar">
              {s.can_authorize && (
                <button className="btn btn-primary" onClick={() => setDialog("authorize")}>
                  Authorise opening
                </button>
              )}
              {s.can_open && (
                <button className="btn btn-danger" onClick={() => setDialog("open")}>
                  Open commercial envelopes
                </button>
              )}
            </div>
          </div>
        </div>
      )}

      {opened && (
        <>
          <h2>Opened offers</h2>
          <Notice>
            Only envelopes of bids recorded as technically responsive were decrypted. Other envelopes remain sealed.
          </Notice>
          <ErrorBanner error={offers.error} />
          <table className="table">
            <thead>
              <tr>
                <th scope="col">Bid reference</th>
                <th scope="col">Bidder</th>
                <th scope="col" className="num">
                  Quoted total
                </th>
                <th scope="col">Source</th>
                <th scope="col">Price bid PDF</th>
              </tr>
            </thead>
            <tbody>
              {offers.data?.map((o) => (
                <tr key={o.bid_id}>
                  <td className="mono">{o.bid_reference}</td>
                  <td>{o.bidder_legal_name}</td>
                  <td className="num mono">{formatInr(o.quoted_total)}</td>
                  <td className="small">Bidder-declared total</td>
                  <td>
                    <PdfButton path={`/tenders/${t.id}/commercial/bids/${o.bid_id}/document`} />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>

          <h2>Commercial ranking</h2>
          {has("COMMERCIAL_OFFICER") && t.status === "COMMERCIAL_OPENED" && (
            <button className="btn btn-primary" onClick={() => evaluate.mutate()} disabled={evaluate.isPending}>
              Compute ranking by tender-configured method
            </button>
          )}
          <ErrorBanner error={evaluate.error ?? ranking.error} />
          {ranking.data && (
            <>
              <p>
                <ProvenanceTag kind="rule" /> Method: <strong>{ranking.data.method_label}</strong> · computed{" "}
                {formatDateTime(ranking.data.created_at)}
              </p>
              <table className="table">
                <thead>
                  <tr>
                    <th scope="col">Rank (by published method)</th>
                    <th scope="col">Bid reference</th>
                    <th scope="col">Bidder</th>
                    <th scope="col" className="num">
                      Quoted total
                    </th>
                  </tr>
                </thead>
                <tbody>
                  {ranking.data.rows.map((r) => (
                    <tr key={r.bid_id}>
                      <td>
                        Rank {r.rank} {r.tie && <StatusBadge status="AMBIGUOUS" label="Tie — officer resolution" />}
                      </td>
                      <td className="mono">{r.bid_reference}</td>
                      <td>{r.bidder_legal_name}</td>
                      <td className="num mono">{formatInr(r.quoted_total)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
              {ranking.data.notes.map((n) => (
                <Notice key={n}>{n}</Notice>
              ))}
            </>
          )}
        </>
      )}

      <ReasonDialog
        open={dialog !== null}
        title={dialog === "open" ? "Open commercial envelopes" : "Authorise commercial opening"}
        description={
          dialog === "open"
            ? "Irreversible. Decrypts the price bids of technically responsive bidders only. The event, authorisers and verified hashes are recorded."
            : "Your authorisation is one of the distinct officer approvals required before opening."
        }
        confirmLabel={dialog === "open" ? "Open envelopes" : "Authorise"}
        danger={dialog === "open"}
        minLength={3}
        onClose={() => setDialog(null)}
        onConfirm={async (reason) => {
          await post(`/tenders/${t.id}/commercial/${dialog === "open" ? "open" : "authorizations"}`, { reason });
          await qc.invalidateQueries();
        }}
      />
    </section>
  );
}

function PdfButton({ path }: { path: string }) {
  const [error, setError] = useState<ApiError | null>(null);
  return (
    <>
      <button
        className="btn btn-small"
        onClick={async () => {
          setError(null);
          try {
            const url = await fetchBlobUrl(path);
            window.open(url, "_blank", "noopener");
            setTimeout(() => URL.revokeObjectURL(url), 60_000);
          } catch (e) {
            setError(e as ApiError);
          }
        }}
      >
        View PDF
      </button>
      {error && <span className="small"> {error.code}</span>}
    </>
  );
}
