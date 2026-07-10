"use client";

/**
 * Login: email + password → POST /api/auth/login. When the account has MFA
 * enabled the gateway returns { mfa_required, mfa_pending_token } and the
 * form switches to the TOTP step → POST /api/auth/login/mfa.
 */

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState, type FormEvent } from "react";
import { useAuth } from "@/lib/auth";

export default function LoginPage() {
  const { state, login, submitMfa, cancelMfa } = useAuth();
  const router = useRouter();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [code, setCode] = useState("");

  useEffect(() => {
    if (state.status === "authenticated") router.replace("/dashboard");
  }, [state.status, router]);

  const submitting = state.status === "submitting";
  const mfaStep = state.status === "mfa_required" || (submitting && state.mfaPendingToken !== null);

  const onSubmitCredentials = async (e: FormEvent) => {
    e.preventDefault();
    await login(email, password);
  };

  const onSubmitCode = async (e: FormEvent) => {
    e.preventDefault();
    await submitMfa(code.trim());
  };

  return (
    <div className="auth-shell">
      <div className="auth-card">
        <div className="auth-brand">
          <span className="brand-dot" aria-hidden="true" />
          TradingPlatform
        </div>

        {state.error ? (
          <div className="banner banner-error" role="alert">
            {state.error}
          </div>
        ) : null}

        {!mfaStep ? (
          <form onSubmit={onSubmitCredentials} aria-label="Login form">
            <div className="form-row">
              <label className="label" htmlFor="login-email">
                Email
              </label>
              <input
                id="login-email"
                className="input"
                type="email"
                autoComplete="email"
                required
                value={email}
                onChange={(e) => setEmail(e.target.value)}
              />
            </div>
            <div className="form-row">
              <label className="label" htmlFor="login-password">
                Password
              </label>
              <input
                id="login-password"
                className="input"
                type="password"
                autoComplete="current-password"
                required
                value={password}
                onChange={(e) => setPassword(e.target.value)}
              />
            </div>
            <button className="btn btn-primary btn-block" type="submit" disabled={submitting}>
              {submitting ? "Signing in…" : "Sign in"}
            </button>
            <p className="muted" style={{ marginTop: 14, fontSize: "0.8rem" }}>
              No account? <Link href="/register">Register</Link>
            </p>
          </form>
        ) : (
          <form onSubmit={onSubmitCode} aria-label="MFA form">
            <p className="muted" style={{ marginTop: 0 }}>
              Multi-factor authentication is enabled. Enter the 6-digit code from your
              authenticator app.
            </p>
            <div className="form-row">
              <label className="label" htmlFor="login-totp">
                TOTP code
              </label>
              <input
                id="login-totp"
                className="input"
                inputMode="numeric"
                autoComplete="one-time-code"
                pattern="[0-9]*"
                maxLength={8}
                required
                autoFocus
                value={code}
                onChange={(e) => setCode(e.target.value)}
              />
            </div>
            <button className="btn btn-primary btn-block" type="submit" disabled={submitting}>
              {submitting ? "Verifying…" : "Verify code"}
            </button>
            <button
              className="btn btn-block"
              type="button"
              style={{ marginTop: 8 }}
              onClick={() => {
                setCode("");
                cancelMfa();
              }}
            >
              Back
            </button>
          </form>
        )}
      </div>
    </div>
  );
}
