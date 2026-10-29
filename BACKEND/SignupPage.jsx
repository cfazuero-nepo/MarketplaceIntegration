// React page served at FRONTEND_URL, e.g. https://app.example.com/marketplace/signup
// Google -> FastAPI (POST, verifies JWT) -> 303 redirect -> this page with ?state=...
import { useEffect, useState } from "react";

const API = "https://api.example.com"; // your FastAPI public URL

export default function MarketplaceSignup() {
  const state = new URLSearchParams(window.location.search).get("state");
  const [session, setSession] = useState(null);
  const [status, setStatus] = useState("loading");

  useEffect(() => {
    if (!state) return setStatus("missing");
    fetch(`${API}/api/marketplace/session/${encodeURIComponent(state)}`)
      .then((r) => (r.ok ? r.json() : Promise.reject(r.status)))
      .then((s) => {
        setSession(s);
        setStatus("ready");
      })
      .catch(() => setStatus("expired"));
  }, [state]);

  async function complete() {
    // TODO: create / link the customer's account in your app first,
    // then ask the backend to approve the Marketplace account.
    setStatus("approving");
    const r = await fetch(
      `${API}/api/marketplace/approve/${encodeURIComponent(state)}`,
      { method: "POST" }
    );
    setStatus(r.ok ? "done" : "error");
  }

  if (status === "loading") return <p>Verifying your Google Cloud purchase...</p>;
  if (status === "missing") return <p>Missing sign-up session. Start again from Google Cloud Marketplace.</p>;
  if (status === "expired") return <p>This sign-up link expired. Start again from Google Cloud Marketplace.</p>;
  if (status === "error") return <p>Approval failed. Please contact support.</p>;
  if (status === "done") return <p>Your account is approved. You can now log in.</p>;

  return (
    <div>
      <h1>Complete your sign-up</h1>
      <p>Roles: {session.roles.join(", ")}</p>
      <button onClick={complete} disabled={status === "approving"}>
        Complete registration
      </button>
    </div>
  );
}
