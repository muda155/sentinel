"use client";
import { useCallback, useEffect, useState, type FormEvent } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { api, ApiError, type UserRow } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { useT } from "@/lib/i18n";
import { COLOR, FONT, RADIUS, SPACE, buttonStyle, inputStyle, panelSurface } from "@/lib/theme";

export default function AdminUsersPage() {
  const { token, user, isAdmin, hydrated } = useAuth();
  const { t } = useT();
  const router = useRouter();
  const [users, setUsers] = useState<UserRow[]>([]);
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [role, setRole] = useState<"analyst" | "admin">("analyst");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const load = useCallback(() => {
    if (!token || !isAdmin) return;
    api.users(token).then(setUsers).catch(() => setError(t("admin.users.loadFailed")));
  }, [token, isAdmin, t]);

  useEffect(load, [load]);

  // Mirrors app/page.tsx: a logged-out visitor must be sent to /login, not
  // shown the forbidden screen — and that decision cannot be made before auth
  // hydrates, or the SSR'd first paint flashes the forbidden screen.
  useEffect(() => {
    if (hydrated && token === null) router.push("/login");
  }, [hydrated, token, router]);

  if (!hydrated) return null;
  if (!token) return null; // redirecting
  if (!isAdmin) {
    return (
      <main style={{ padding: 32, background: COLOR.bg, color: COLOR.text, height: "100vh" }}>
        <p>{t("admin.users.forbidden")}</p>
        <Link href="/" style={{ color: COLOR.link }}>{t("admin.users.back")}</Link>
      </main>
    );
  }

  const create = async (e: FormEvent) => {
    e.preventDefault();
    if (busy) return;
    setError(null);
    setBusy(true);
    try {
      const created = await api.createUser({ username, password, role }, token);
      // Append rather than refetch: /auth/users is not on the shared 60/min
      // bucket, but a refetch would also discard the form's scroll position
      // for no new information.
      setUsers((prev) => [...prev, created].sort((a, b) => a.username.localeCompare(b.username)));
      setUsername(""); setPassword(""); setRole("analyst");
    } catch (err) {
      setError(err instanceof ApiError && err.status === 409
        ? t("admin.users.duplicate")
        : t("admin.users.createFailed"));
    } finally {
      setBusy(false);
    }
  };

  const remove = async (row: UserRow) => {
    if (busy) return;   // a double click would 404 the second delete after the first succeeded
    if (!window.confirm(t("admin.users.confirmDelete").replace("{name}", row.username))) return;
    setError(null);
    setBusy(true);
    try {
      await api.deleteUser(row.user_id, token);
      setUsers((prev) => prev.filter((u) => u.user_id !== row.user_id));
    } catch {
      setError(t("admin.users.deleteFailed"));
    } finally {
      setBusy(false);
    }
  };

  return (
    <main style={{ padding: 32, background: COLOR.bg, color: COLOR.text,
                   height: "100vh", overflowY: "auto" }}>
      <Link href="/" style={{ color: COLOR.link, fontSize: FONT.md }}>← {t("admin.users.back")}</Link>
      <h1 style={{ fontSize: FONT.xl, marginTop: SPACE.lg }}>{t("admin.users.title")}</h1>

      {error && (
        <p role="alert" style={{ color: COLOR.dangerText, background: COLOR.dangerSurface,
                                 padding: `${SPACE.md}px ${SPACE.lg}px`, borderRadius: RADIUS.sm,
                                 fontSize: FONT.md, maxWidth: 620 }}>
          {error}
        </p>
      )}

      <form onSubmit={create} style={{ ...panelSurface, padding: SPACE.xl, maxWidth: 760,
                                       display: "flex", gap: SPACE.lg, alignItems: "flex-start",
                                       flexWrap: "wrap", marginBottom: SPACE.xl }}>
        <label style={{ display: "flex", flexDirection: "column", gap: SPACE.xs, fontSize: FONT.sm }}>
          {t("login.username")}
          <input value={username} onChange={(e) => setUsername(e.target.value)}
                 required minLength={3} autoComplete="off" disabled={busy}
                 style={{ ...inputStyle, width: 160 }} />
        </label>
        <label style={{ display: "flex", flexDirection: "column", gap: SPACE.xs, fontSize: FONT.sm }}>
          {/* The hint sits on the same line as the label so the three inputs
              share a bottom edge (flex-end staggered the password input 17px
              because the hint stretched its label). */}
          <span style={{ display: "flex", gap: SPACE.xs, alignItems: "baseline" }}>
            {t("login.password")}
            <span style={{ fontSize: FONT.xs, color: COLOR.textDim }}>{t("admin.users.passwordHint")}</span>
          </span>
          <input type="password" value={password} onChange={(e) => setPassword(e.target.value)}
                 required minLength={8} maxLength={72} autoComplete="new-password" disabled={busy}
                 style={{ ...inputStyle, width: 180 }} />
        </label>
        <label style={{ display: "flex", flexDirection: "column", gap: SPACE.xs, fontSize: FONT.sm }}>
          {t("admin.users.role")}
          {/* "Chuyên viên phân tích" needs ~180px or the arrow clips the text. */}
          <select value={role} onChange={(e) => setRole(e.target.value as "analyst" | "admin")}
                  disabled={busy} style={{ ...inputStyle, width: 180 }}>
            <option value="analyst">{t("admin.users.role.analyst")}</option>
            <option value="admin">{t("admin.users.role.admin")}</option>
          </select>
        </label>
        <button type="submit" disabled={busy} style={{ ...buttonStyle, background: COLOR.accent,
                                                       color: COLOR.bg, border: "none", fontWeight: 600,
                                                       alignSelf: "flex-end" }}>
          {busy ? t("admin.users.creating") : t("admin.users.create")}
        </button>
      </form>

      {users.length === 0 ? (
        <p style={{ color: COLOR.textMuted, fontSize: FONT.md }}>{t("admin.users.empty")}</p>
      ) : (
        <div style={{ ...panelSurface, maxWidth: 760, overflow: "hidden" }}>
          <div style={{ display: "flex", alignItems: "center", gap: SPACE.lg,
                        padding: `${SPACE.md}px ${SPACE.xl}px`, borderBottom: `1px solid ${COLOR.border}`,
                        fontSize: FONT.sm, color: COLOR.textMuted }}>
            <span style={{ flex: 1 }}>{t("login.username")}</span>
            <span style={{ width: 120 }}>{t("admin.users.role")}</span>
            <span style={{ width: 96 }}>{t("admin.users.created")}</span>
            <span style={{ width: 72 }} />
          </div>
          {users.map((u) => (
            <div key={u.user_id} style={{ display: "flex", alignItems: "center", gap: SPACE.lg,
                                          padding: `${SPACE.lg}px ${SPACE.xl}px`,
                                          borderTop: `1px solid ${COLOR.border}` }}>
              <span style={{ flex: 1, fontSize: FONT.md }}>{u.username}</span>
              <span style={{ fontSize: FONT.sm, color: COLOR.textMuted, width: 120 }}>
                {t(u.role === "admin" ? "admin.users.role.admin" : "admin.users.role.analyst")}
              </span>
              <span style={{ fontSize: FONT.sm, color: COLOR.textDim, width: 96 }}>
                {u.created_at ? new Date(u.created_at).toLocaleDateString() : ""}
              </span>
              {u.username === user?.username ? (
                <span style={{ width: 72 }} />
              ) : (
                <button onClick={() => remove(u)} disabled={busy}
                        style={{ ...buttonStyle, width: 72, fontSize: FONT.sm,
                                 padding: `${SPACE.sm}px ${SPACE.md}px`, color: COLOR.danger }}>
                  {t("admin.users.delete")}
                </button>
              )}
            </div>
          ))}
        </div>
      )}
    </main>
  );
}
