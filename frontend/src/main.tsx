import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { BrowserRouter, Link, Navigate, Route, Routes } from "react-router-dom";
import { ApiError } from "./api/client";
import { Header } from "./components/Shell";
import { Loading } from "./components/ui";
import { BidScrutiny } from "./features/officer/BidScrutiny";
import { Login } from "./features/officer/Login";
import { TenderList } from "./features/officer/Tenders";
import { TenderWorkspace } from "./features/officer/Workspace";
import { PortalHome, Receipt, SubmitBid } from "./features/portal/Portal";
import { AuthProvider, useAuth } from "./lib/auth";
import "./styles/app.css";

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      retry: (count, error) => !(error instanceof ApiError && error.status < 500) && count < 2,
      refetchOnWindowFocus: false,
      staleTime: 5_000,
    },
  },
});

function RequireOfficer({ children }: { children: React.ReactNode }) {
  const { officer, loading } = useAuth();
  if (loading) return <Loading what="Checking session" />;
  if (!officer) return <Navigate to="/officer/login" replace />;
  return <>{children}</>;
}

function Landing() {
  return (
    <div className="app">
      <Header subtitle="Welcome" />
      <main id="main" className="content content-narrow">
        <h1>Tender Scrutiny &amp; Evaluation Portal</h1>
        <p className="lead">
          Electricity-sector procurement scrutiny with deterministic, evidence-linked evaluation. Automated outputs
          are observations only; authorised officers make every decision.
        </p>
        <div className="grid2">
          <section className="card">
            <h2>Bidders</h2>
            <p>View open tenders and submit your combined technical PDF and sealed price bid.</p>
            <Link className="btn btn-primary" to="/portal">
              Go to bidder submission portal
            </Link>
          </section>
          <section className="card">
            <h2>Officers</h2>
            <p>Tender administration, scrutiny, evaluation, commercial opening and audit.</p>
            <Link className="btn" to="/officer/login">
              Officer sign-in
            </Link>
          </section>
        </div>
      </main>
    </div>
  );
}

function App() {
  return (
    <Routes>
      <Route path="/" element={<Landing />} />
      <Route path="/portal" element={<PortalHome />} />
      <Route path="/portal/tenders/:tenderId" element={<SubmitBid />} />
      <Route path="/portal/receipt" element={<Receipt />} />
      <Route path="/officer/login" element={<Login />} />
      <Route path="/officer" element={<RequireOfficer><TenderList /></RequireOfficer>} />
      <Route path="/officer/tenders/:tenderId" element={<RequireOfficer><TenderWorkspace /></RequireOfficer>} />
      <Route path="/officer/tenders/:tenderId/:tab" element={<RequireOfficer><TenderWorkspace /></RequireOfficer>} />
      <Route path="/officer/bids/:bidId" element={<RequireOfficer><BidScrutiny /></RequireOfficer>} />
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  );
}

const root = document.getElementById("root");
if (!root) throw new Error("root element missing");
createRoot(root).render(
  <StrictMode>
    <QueryClientProvider client={queryClient}>
      <AuthProvider>
        <BrowserRouter>
          <App />
        </BrowserRouter>
      </AuthProvider>
    </QueryClientProvider>
  </StrictMode>,
);
