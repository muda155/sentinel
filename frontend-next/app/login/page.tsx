"use client";
import { useState, type FormEvent } from "react";
import { useRouter } from "next/navigation";
import { useAuth } from "@/lib/auth";

export default function LoginPage() {
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const { login } = useAuth();
  const router = useRouter();

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setError("");
    try {
      await login(username, password);
      router.push("/");
    } catch {
      setError("Invalid username or password");
    }
  };

  return (
    <main style={{ display: "flex", justifyContent: "center", alignItems: "center", height: "100vh", background: "#1a1a2e", color: "#eee" }}>
      <form onSubmit={submit} style={{ display: "flex", flexDirection: "column", gap: 12, width: 300, padding: 24, background: "#16213e", borderRadius: 8 }}>
        <h1 style={{ margin: 0, textAlign: "center" }}>Sentinel Login</h1>
        {error && <p style={{ color: "#f87171", margin: 0, textAlign: "center" }}>{error}</p>}
        <input
          placeholder="Username"
          value={username}
          onChange={(e) => setUsername(e.target.value)}
          style={{ padding: 10, borderRadius: 4, border: "1px solid #333", background: "#0f3460", color: "#eee" }}
        />
        <input
          type="password"
          placeholder="Password"
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          style={{ padding: 10, borderRadius: 4, border: "1px solid #333", background: "#0f3460", color: "#eee" }}
        />
        <button type="submit" style={{ padding: 10, borderRadius: 4, border: "none", background: "#e94560", color: "#fff", cursor: "pointer", fontWeight: 600 }}>
          Sign In
        </button>
      </form>
    </main>
  );
}
