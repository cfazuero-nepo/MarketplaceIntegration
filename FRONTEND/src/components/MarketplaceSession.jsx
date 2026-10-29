
import { useEffect, useState } from 'react'
import { getSignupSession } from '../services/authService'

const ROLE_LABELS = {
  account_admin: 'Billing account administrator',
  project_editor: 'Project editor',
}

export default function MarketplaceSession({ state }) {
  const [session, setSession] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

  useEffect(() => {
    if (!state) {
      setLoading(false)
      return
    }

    let cancelled = false

    setLoading(true)
    setError('')
    setSession(null)

    getSignupSession(state)
      .then((data) => {
        if (!cancelled) {
          setSession(data)
        }
      })
      .catch((err) => {
        if (!cancelled) {
          setError(
            err.message || 'Unable to load Marketplace session.'
          )
        }
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })

    return () => {
      cancelled = true
    }
  }, [state])

  if (!state) return null

  if (loading) {
    return (
      <p>Checking your Google Cloud Marketplace request...</p>
    )
  }

  if (error) {
    return (
      <div role="alert" className="error-message">
        {error}
      </div>
    )
  }

  if (!session) return null

  const roles = (session.roles || []).map(
    role => ROLE_LABELS[role] || role
  )

  const orderCount = Array.isArray(session.orders)
    ? session.orders.length
    : 0

  return (
    <section className="marketplace-session">
      <h3>Google Cloud Marketplace</h3>

      <p>Your Marketplace request was found.</p>

      {roles.length > 0 && (
        <p>
          <strong>Your role:</strong> {roles.join(', ')}
        </p>
      )}

      <p>
        <strong>Orders in request:</strong> {orderCount}
      </p>

      <p>
        Sign in with Google to continue with your
        Netpoleon account.
      </p>
    </section>
  )
}
