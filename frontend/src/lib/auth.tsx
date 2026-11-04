import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { get, post, setUnauthorizedHandler, tokenStore } from "../api/client";
import type { LoginOut, Officer, Role } from "../api/types";

interface AuthState {
  officer: Officer | null;
  environment: string;
  loading: boolean;
  login: (username: string) => Promise<void>;
  logout: () => void;
  has: (...roles: Role[]) => boolean;
}

const AuthContext = createContext<AuthState | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const qc = useQueryClient();
  const [officer, setOfficer] = useState<Officer | null>(null);
  const [environment, setEnvironment] = useState("demo");
  const [loading, setLoading] = useState(Boolean(tokenStore.get()));

  const logout = useCallback(() => {
    tokenStore.clear();
    setOfficer(null);
    qc.clear(); // never leave another role's data in the client cache
  }, [qc]);

  useEffect(() => {
    setUnauthorizedHandler(logout);
    if (!tokenStore.get()) return;
    get<Officer>("/auth/me")
      .then(setOfficer)
      .catch(() => logout())
      .finally(() => setLoading(false));
  }, [logout]);

  const login = useCallback(
    async (username: string) => {
      qc.clear();
      const out = await post<LoginOut>("/auth/dev-login", { username });
      tokenStore.set(out.token);
      setEnvironment(out.environment);
      setOfficer(out.officer);
    },
    [qc],
  );

  const value = useMemo<AuthState>(
    () => ({
      officer,
      environment,
      loading,
      login,
      logout,
      has: (...roles: Role[]) => Boolean(officer && officer.roles.some((r) => roles.includes(r))),
    }),
    [officer, environment, loading, login, logout],
  );
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthState {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth outside AuthProvider");
  return ctx;
}
