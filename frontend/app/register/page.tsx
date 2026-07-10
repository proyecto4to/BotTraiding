"use client";

/** Registration: POST /api/auth/register (min 8 char password, viewer role
 * by default). On success the user is sent to /login. */

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState, type FormEvent } from "react";
import { useToast } from "@/components/Toast";
import { ApiError } from "@/lib/api";
import { useAuth } from "@/lib/auth";

export default function RegisterPage() {
  const { register } = useAuth();
  const { push } = useToast();
  const router = useRouter();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  const onSubmit = async (e: FormEvent) => {
    e.preventDefault();
    setError(null);
    if (password.length < 8) {
      setError("Password must be at least 8 characters.");
      return;
    }
    if (password !== confirm) {
      setError("Passwords do not match.");
      return;
    }
    setSubmitting(true);
    try {
      await register(email, password);
      push("Account created. You can sign in now.", "success");
      router.replace("/login");
    } catch (err) {
      setError(
        err instanceof ApiError && err.status === 409
          ? "Email already registered."
          : err instanceof Error
            ? err.message
            : "Registration failed.",
      );
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="auth-shell">
      <div className="auth-card">
        <div className="auth-brand">
          <span className="brand-dot" aria-hidden="true" />
          TradingPlatform — Register
        </div>

        {error ? (
          <div className="banner banner-error" role="alert">
            {error}
          </div>
        ) : null}

        <form onSubmit={onSubmit} aria-label="Register form">
          <div className="form-row">
            <label className="label" htmlFor="reg-email">
              Email
            </label>
            <input
              id="reg-email"
              className="input"
              type="email"
              autoComplete="email"
              required
              value={email}
              onChange={(e) => setEmail(e.target.value)}
            />
          </div>
          <div className="form-row">
            <label className="label" htmlFor="reg-password">
              Password (min 8 characters)
            </label>
            <input
              id="reg-password"
              className="input"
              type="password"
              autoComplete="new-password"
              required
              minLength={8}
              value={password}
              onChange={(e) => setPassword(e.target.value)}
            />
          </div>
          <div className="form-row">
            <label className="label" htmlFor="reg-confirm">
              Confirm password
            </label>
            <input
              id="reg-confirm"
              className="input"
              type="password"
              autoComplete="new-password"
              required
              value={confirm}
              onChange={(e) => setConfirm(e.target.value)}
            />
          </div>
          <button className="btn btn-primary btn-block" type="submit" disabled={submitting}>
            {submitting ? "Creating account…" : "Create account"}
          </button>
          <p className="muted" style={{ marginTop: 14, fontSize: "0.8rem" }}>
            Already registered? <Link href="/login">Sign in</Link>
          </p>
        </form>
      </div>
    </div>
  );
}
