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

export class LoginError extends Error {
  constructor(public readonly kind: "credentials" | "network") {
    super(kind);
    this.name = "LoginError";
  }
}

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
    let res: Response;
    try {
      res = await fetch(`${BASE}/auth/login`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ username, password }),
      });
    } catch {
      // fetch only rejects on a transport failure — DNS, CORS, API down.
      // Reporting this as "wrong password" sent people hunting for a typo
      // while the API container was simply not running.
      throw new LoginError("network");
    }
    if (res.status === 401) throw new LoginError("credentials");
    if (!res.ok) throw new LoginError("network");
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
