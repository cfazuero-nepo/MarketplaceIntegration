
const API_BASE_URL = (
  import.meta.env.VITE_API_BASE_URL ||
  'http://localhost:8000'
).replace(/\/+$/, '')

// Existing password login function.
// Kept for compatibility with any existing imports.
export async function loginWithPassword(email, password) {
  let response

  try {
    response = await fetch(`${API_BASE_URL}/auth/login`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
      credentials: 'include',
      body: JSON.stringify({
        email,
        password,
      }),
    })
  } catch {
    throw new Error(
      'Cannot connect to the server. Please try again later.'
    )
  }

  if (!response.ok) {
    if (response.status === 401) {
      throw new Error('Invalid email or password.')
    }

    throw new Error(`Sign in failed (${response.status}).`)
  }

  return response
}

// Existing Google redirect login function.
// Your current Google Sign-In button uses its own working flow.
export function startGoogleLogin() {
  window.location.assign(`${API_BASE_URL}/auth/google/login`)
}

// SMP-41: Retrieve verified Marketplace signup session.
// The state is created by FastAPI after validating
// the Marketplace signup JWT.
export async function getSignupSession(state) {
  if (!state || typeof state !== 'string') {
    throw new Error('Marketplace signup state is missing.')
  }

  let response

  try {
    response = await fetch(
      `${API_BASE_URL}/api/marketplace/session/${encodeURIComponent(state)}`,
      {
        method: 'GET',
        headers: {
          Accept: 'application/json',
        },
      }
    )
  } catch {
    throw new Error(
      'Cannot connect to the Marketplace session service.'
    )
  }

  if (!response.ok) {
    if (response.status === 404) {
      throw new Error(
        'This Marketplace signup link is invalid or has expired.'
      )
    }

    if (response.status === 401 || response.status === 403) {
      throw new Error(
        'You are not authorised to view this Marketplace session.'
      )
    }

    throw new Error(
      `Unable to retrieve Marketplace session (${response.status}).`
    )
  }

  return response.json()
}
