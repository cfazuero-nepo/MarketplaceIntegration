
import {
  createContext,
  useCallback,
  useContext,
  useState,
} from 'react'

const AuthContext = createContext(null)

const API_BASE_URL =
  import.meta.env.VITE_API_BASE_URL || 'http://localhost:8080'

export function AuthProvider({ children }) {
  const [user, setUser] = useState(null)
  const [token, setToken] = useState(null)

  const login = useCallback(async (googleIdToken) => {
    const response = await fetch(`${API_BASE_URL}/api/me`, {
      headers: {
        Authorization: `Bearer ${googleIdToken}`,
      },
    })

    if (!response.ok) {
      throw new Error(
        response.status === 403
          ? 'Your account is not authorised.'
          : 'Google authentication could not be verified.'
      )
    }

    const data = await response.json()

    setToken(googleIdToken)
    setUser(data.user)

    return data.user
  }, [])

  const logout = useCallback(() => {
    window.google?.accounts?.id?.disableAutoSelect?.()
    setToken(null)
    setUser(null)
  }, [])

  return (
    <AuthContext.Provider
      value={{
        user,
        token,
        isAuthenticated: Boolean(user),
        login,
        logout,
      }}
    >
      {children}
    </AuthContext.Provider>
  )
}

export function useAuth() {
  const context = useContext(AuthContext)

  if (!context) {
    throw new Error('useAuth must be used inside AuthProvider')
  }

  return context
}
