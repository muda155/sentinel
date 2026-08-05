"use client";
import { useState, type FormEvent } from "react";
import { useRouter } from "next/navigation";
import { LoginError, useAuth } from "@/lib/auth";
import { useT } from "@/lib/i18n";
import LanguageToggle from "@/components/LanguageToggle";
import { COLOR, FONT, RADIUS, SPACE, inputStyle } from "@/lib/theme";

export default function LoginPage() {
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<"credentials" | "network" | null>(null);
  const [busy, setBusy] = useState(false);
  const { login } = useAuth();
  const { t } = useT();
  const router = useRouter();

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    if (busy) return;
    setError(null);
    setBusy(true);
    try {
      await login(username, password);
      router.push("/");
    } catch (err) {
      setError(err instanceof LoginError ? err.kind : "network");
      setBusy(false);
    }
    // No setBusy(false) on success: the route is changing, and re-enabling the
    // button would flash it live for a frame before the page unmounts.
  };

  return (
    <main style={{
      display: "flex", justifyContent: "center", alignItems: "center",
      height: "100vh", background: COLOR.bg, color: COLOR.text,
    }}>
      <div style={{ position: "absolute", top: SPACE.lg, right: SPACE.lg }}>
        <LanguageToggle />
      </div>
      <form onSubmit={submit} style={{
        display: "flex", flexDirection: "column", gap: SPACE.lg,
        width: 320, padding: 28,
        background: COLOR.surface, border: `1px solid ${COLOR.border}`,
        borderRadius: RADIUS.lg,
      }}>
        <div>
          <h1 style={{ margin: 0, fontSize: FONT.xl, letterSpacing: "-0.01em" }}>
            {t("login.title")}
          </h1>
          <p style={{ margin: `${SPACE.xs}px 0 0`, fontSize: FONT.md, color: COLOR.textMuted }}>
            {t("login.subtitle")}
          </p>
        </div>

        {error && (
          <p role="alert" style={{
            margin: 0, fontSize: FONT.md, color: COLOR.dangerText,
            background: COLOR.dangerSurface, padding: `${SPACE.md}px ${SPACE.lg}px`,
            borderRadius: RADIUS.sm,
          }}>
            {t(error === "credentials" ? "login.error.credentials" : "login.error.network")}
          </p>
        )}

        <label style={{ display: "flex", flexDirection: "column", gap: SPACE.xs, fontSize: FONT.md }}>
          {t("login.username")}
          <input
            value={username}
            onChange={(e) => setUsername(e.target.value)}
            autoComplete="username"
            autoFocus
            required
            disabled={busy}
            style={inputStyle}
          />
        </label>

        <label style={{ display: "flex", flexDirection: "column", gap: SPACE.xs, fontSize: FONT.md }}>
          {t("login.password")}
          <input
            type="password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            autoComplete="current-password"
            required
            disabled={busy}
            style={inputStyle}
          />
        </label>

        <button type="submit" disabled={busy} style={{
          padding: SPACE.lg, borderRadius: RADIUS.md, border: "none",
          background: busy ? COLOR.borderStrong : COLOR.accent,
          color: busy ? COLOR.textMuted : COLOR.bg,
          cursor: busy ? "default" : "pointer",
          fontWeight: 600, fontSize: FONT.md,
        }}>
          {busy ? t("login.submitting") : t("login.submit")}
        </button>
      </form>
    </main>
  );
}
