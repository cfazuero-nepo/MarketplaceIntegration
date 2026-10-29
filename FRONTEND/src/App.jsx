
import LoginForm from './components/LoginForm'
import MarketplaceSession from './components/MarketplaceSession'
import { useAuth } from './auth/AuthContext'
import './App.css'

function App() {
  const { user, isAuthenticated, logout } = useAuth()

  // SMP-41:
  // Read the temporary Marketplace state from the URL.
  // Example: /?state=abc123
  const marketplaceState = new URLSearchParams(
    window.location.search
  ).get('state')

  if (isAuthenticated) {
    return (
      <main className="app-shell">

        {/* LEFT BRANDING PANEL */}
        <section className="brand-panel">
          <div className="brand-logo">
            <img
              src="/netpoleon-logo.png"
              alt="Netpoleon"
            />
          </div>

          <div className="brand-content">
            <span className="eyebrow">
              GOOGLE CLOUD MARKETPLACE
            </span>

            <h1>
              Secure access to your{' '}
              <span>cloud solutions.</span>
            </h1>

            <p>
              Access and manage your cloud marketplace
              connections through Netpoleon's secure
              customer portal.
            </p>
          </div>

          <p className="brand-footer">
            © {new Date().getFullYear()} Netpoleon ANZ.
            All rights reserved.
          </p>
        </section>

        {/* RIGHT PANEL: SIGNED-IN USER */}
        <section className="login-panel">
          <div className="login-container">

            <div className="login-header">
              <span className="eyebrow">
                GOOGLE CLOUD MARKETPLACE
              </span>

              <h2>Welcome to Netpoleon</h2>

              <p>You have successfully signed in.</p>
            </div>

            <p>Signed in as: {user?.email}</p>

            {/* SMP-41: Marketplace session information */}
            {marketplaceState && (
              <>
                <MarketplaceSession state={marketplaceState} />

                <p>
                  Your Google Sign-In is complete.
                  Marketplace account linking and
                  activation are handled in the next stage.
                </p>
              </>
            )}

            <button
              type="button"
              className="primary-button"
              onClick={logout}
            >
              Sign out
            </button>

          </div>
        </section>

      </main>
    )
  }

  return (
    <main className="app-shell">

      {/* LEFT BRANDING PANEL */}
      <section className="brand-panel">
        <div className="brand-logo">
          <img
            src="/netpoleon-logo.png"
            alt="Netpoleon"
          />
        </div>

        <div className="brand-content">
          <span className="eyebrow">
            GOOGLE CLOUD MARKETPLACE
          </span>

          <h1>
            Secure access to your{' '}
            <span>cloud solutions.</span>
          </h1>

          <p>
            Access and manage your cloud marketplace
            connections through Netpoleon's secure
            customer portal.
          </p>
        </div>

        <p className="brand-footer">
          © {new Date().getFullYear()} Netpoleon ANZ.
          All rights reserved.
        </p>
      </section>

      {/* RIGHT LOGIN PANEL */}
      <section className="login-panel">
        <div>

          {/* SMP-41: Show Marketplace session,
              only when a state exists in the URL */}
          {marketplaceState && (
            <MarketplaceSession state={marketplaceState} />
          )}

          {/* Existing working Google login */}
          <LoginForm />

        </div>
      </section>

    </main>
  )
}

export default App
