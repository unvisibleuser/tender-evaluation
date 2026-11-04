import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Navigate, useNavigate } from "react-router-dom";
import { get } from "../../api/client";
import type { Officer } from "../../api/types";
import { Header } from "../../components/Shell";
import { ErrorBanner, Loading, Notice } from "../../components/ui";
import { useAuth } from "../../lib/auth";
import { ROLE_LABELS } from "../../lib/format";

export function Login() {
  const { officer, login } = useAuth();
  const navigate = useNavigate();
  const [error, setError] = useState<unknown>(null);
  const q = useQuery({ queryKey: ["demo-officers"], queryFn: () => get<Officer[]>("/auth/demo-officers") });
  if (officer) return <Navigate to="/officer" replace />;
  return (
    <div className="app">
      <Header subtitle="Officer sign-in" />
      <main id="main" className="content content-narrow">
        <h1>Officer sign-in</h1>
        <Notice kind="warn">
          <strong>Demo identity mode.</strong> Select a synthetic officer account. Production deployments must use
          the authority&apos;s identity provider with multi-factor authentication; this mode is refused by the server
          in production.
        </Notice>
        {q.isLoading && <Loading />}
        <ErrorBanner error={q.error ?? error} />
        <table className="table">
          <thead>
            <tr>
              <th scope="col">Officer</th>
              <th scope="col">Designation</th>
              <th scope="col">Role</th>
              <th scope="col">
                <span className="sr-only">Sign in</span>
              </th>
            </tr>
          </thead>
          <tbody>
            {q.data?.map((o) => (
              <tr key={o.id}>
                <td>
                  <strong>{o.display_name}</strong> <span className="muted mono">({o.username})</span>
                </td>
                <td>{o.designation}</td>
                <td>{o.roles.map((r) => ROLE_LABELS[r] ?? r).join(", ")}</td>
                <td>
                  <button
                    className="btn btn-primary btn-small"
                    onClick={async () => {
                      setError(null);
                      try {
                        await login(o.username);
                        navigate("/officer");
                      } catch (e) {
                        setError(e);
                      }
                    }}
                  >
                    Sign in
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </main>
    </div>
  );
}
