import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link, useNavigate } from "react-router-dom";
import { get, post } from "../../api/client";
import type { Tender } from "../../api/types";
import { OfficerShell } from "../../components/Shell";
import { ErrorBanner, Loading, StatusBadge } from "../../components/ui";
import { useAuth } from "../../lib/auth";
import { formatDateTime } from "../../lib/format";

export function TenderList() {
  const { has } = useAuth();
  const [creating, setCreating] = useState(false);
  const q = useQuery({ queryKey: ["tenders"], queryFn: () => get<Tender[]>("/tenders") });
  return (
    <OfficerShell>
      <div className="page-head">
        <h1>Tenders</h1>
        {has("TENDER_ADMIN") && (
          <button className="btn btn-primary" onClick={() => setCreating((v) => !v)}>
            {creating ? "Close form" : "New tender"}
          </button>
        )}
      </div>
      {creating && <CreateTender onDone={() => setCreating(false)} />}
      {q.isLoading && <Loading />}
      <ErrorBanner error={q.error} />
      <table className="table">
        <thead>
          <tr>
            <th scope="col">Tender no.</th>
            <th scope="col">Title</th>
            <th scope="col">Stage</th>
            <th scope="col">Deadline</th>
            <th scope="col">Rulebook</th>
            <th scope="col">Bids</th>
          </tr>
        </thead>
        <tbody>
          {q.data?.map((t) => (
            <tr key={t.id}>
              <td className="mono">
                <Link to={`/officer/tenders/${t.id}`}>{t.reference_no}</Link>
              </td>
              <td>{t.title}</td>
              <td>
                <StatusBadge status={t.status} />
              </td>
              <td>{formatDateTime(t.submission_deadline, t.timezone)}</td>
              <td>{t.pinned_rulebook_version_no ? `v${t.pinned_rulebook_version_no} (approved)` : "Not pinned"}</td>
              <td>{t.bid_count}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </OfficerShell>
  );
}

function CreateTender({ onDone }: { onDone: () => void }) {
  const qc = useQueryClient();
  const navigate = useNavigate();
  const m = useMutation({
    mutationFn: (body: Record<string, unknown>) => post<Tender>("/tenders", body),
    onSuccess: (t) => {
      qc.invalidateQueries({ queryKey: ["tenders"] });
      onDone();
      navigate(`/officer/tenders/${t.id}`);
    },
  });
  return (
    <form
      className="card form"
      onSubmit={(e) => {
        e.preventDefault();
        const f = new FormData(e.currentTarget);
        // datetime-local is interpreted as IST and sent with an explicit offset
        const local = String(f.get("deadline"));
        m.mutate({
          reference_no: f.get("reference_no"),
          title: f.get("title"),
          authority: f.get("authority"),
          description: f.get("description"),
          submission_deadline: `${local}:00+05:30`,
          timezone: "Asia/Kolkata",
          commercial_envelope_required: true,
          commercial_evaluation_method: f.get("method") || null,
          opening_quorum: Number(f.get("quorum")),
        });
      }}
    >
      <h2>New tender</h2>
      <div className="grid2">
        <label className="field">
          <span>Tender reference no. *</span>
          <input name="reference_no" required minLength={3} />
        </label>
        <label className="field">
          <span>Procuring authority *</span>
          <input name="authority" required />
        </label>
        <label className="field span2">
          <span>Title *</span>
          <input name="title" required minLength={3} />
        </label>
        <label className="field span2">
          <span>Description</span>
          <textarea name="description" rows={2} />
        </label>
        <label className="field">
          <span>Submission deadline (IST) *</span>
          <input name="deadline" type="datetime-local" required />
        </label>
        <label className="field">
          <span>Commercial evaluation method (as stated in tender)</span>
          <select name="method" defaultValue="">
            <option value="">Not configured — requires officer configuration</option>
            <option value="LOWEST_QUOTED_TOTAL">Lowest quoted total (L1)</option>
          </select>
        </label>
        <label className="field">
          <span>Commercial opening quorum (distinct officers)</span>
          <input name="quorum" type="number" min={1} max={5} defaultValue={2} />
        </label>
      </div>
      <ErrorBanner error={m.error} />
      <button className="btn btn-primary" disabled={m.isPending}>
        Create tender (draft)
      </button>
    </form>
  );
}
