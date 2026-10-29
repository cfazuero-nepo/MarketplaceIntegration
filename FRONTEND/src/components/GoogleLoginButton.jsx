
import { useEffect, useRef, useState } from 'react'
import { loadGoogleIdentity } from '../google'
import { useAuth } from '../auth/AuthContext'

const CLIENT_ID = import.meta.env.VITE_GOOGLE_CLIENT_ID

function GoogleLoginButton() {
  const buttonRef = useRef(null)
  const { login } = useAuth()
  const [error, setError] = useState('')
  const [isLoading, setIsLoading] = useState(true)

  useEffect(() => {
    let cancelled = false

    if (!CLIENT_ID) {
      setError('Google Client ID is not configured.')
      setIsLoading(false)
      return
    }

    loadGoogleIdentity()
      .then((google) => {
        if (cancelled || !buttonRef.current) return

        google.accounts.id.initialize({
          client_id: CLIENT_ID,

          callback: async (response) => {
            try {
              setError('')
              setIsLoading(true)

              if (!response.credential) {
                throw new Error('Google did not return a token.')
              }

              await login(response.credential)
            } catch (err) {
              setError(err.message || 'Google sign-in failed.')
            } finally {
              if (!cancelled) setIsLoading(false)
            }
          },

          ux_mode: 'popup',
        })

        buttonRef.current.innerHTML = ''

        google.accounts.id.renderButton(
          buttonRef.current,
          {
            theme: 'outline',
            size: 'large',
            text: 'signin_with',
            shape: 'rectangular',
            logo_alignment: 'left',
            width: 320,
          }
        )

        setIsLoading(false)
      })
      .catch((err) => {
        if (!cancelled) {
          setError(err.message)
          setIsLoading(false)
        }
      })

    return () => {
      cancelled = true
    }
  }, [login])

  return (
    <div className="google-signin-container">
      <div ref={buttonRef} />

      {isLoading && (
        <p className="login-status">
          Loading Google Sign-In...
        </p>
      )}

      {error && (
        <p className="login-error" role="alert">
          {error}
        </p>
      )}
    </div>
  )
}

export default GoogleLoginButton
