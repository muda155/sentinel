"use client";
import { createContext, useContext, useState, useCallback, useMemo, useEffect, type ReactNode } from "react";

type User = { username: string; role: "admin" | "analyst" };

type AuthCtx = {
  token: string | null;
  user: User | null;
  hydrated: boolean;
  login: (username: string, password: string) => Promise<void>;
  logout: () => void;
};

const AuthContext = createContext<AuthCtx>({
  token: null,
  user: null,
  hydrated: false,
  login: async () => {},
  logout: () => {},
});

function decodePayload(token: string): User | null {
  try {
    const body = token.split(".")[1];
    const json = JSON.parse(atob(body));
    return { username: json.sub, role: json.role };
  } catch {
    return null;
  }
}

const BASE = process.env.NEXT_PUBLIC_API_BASE ?? "http://localhost:8000";

export function AuthProvider({ children }: { children: ReactNode }) {
  const [token, setToken] = useState<string | null>(null);
  const [hydrated, setHydrated] = useState(false);
  useEffect(() => {
    setToken(localStorage.getItem("sentinel_token"));
    setHydrated(true);
  }, []);
  const user = useMemo(() => (token ? decodePayload(token) : null), [token]);

  const login = useCallback(async (username: string, password: string) => {
    const res = await fetch(`${BASE}/auth/login`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ username, password }),
    });
    if (!res.ok) throw new Error("invalid credentials");
    const data = await res.json();
    localStorage.setItem("sentinel_token", data.access_token);
    setToken(data.access_token);
  }, []);

  const logout = useCallback(() => {
    localStorage.removeItem("sentinel_token");
    setToken(null);
  }, []);

  return (
    <AuthContext.Provider value={{ token, user, hydrated, login, logout }}>
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth() {
  const ctx = useContext(AuthContext);
  return { ...ctx, isAdmin: ctx.user?.role === "admin" };
}
