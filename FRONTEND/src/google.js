
let googlePromise = null

export function loadGoogleIdentity() {
  if (window.google?.accounts?.id) {
    return Promise.resolve(window.google)
  }

  if (!googlePromise) {
    googlePromise = new Promise((resolve, reject) => {
      const script = document.createElement('script')

      script.src = 'https://accounts.google.com/gsi/client'
      script.async = true
      script.defer = true

      script.onload = () => {
        if (window.google?.accounts?.id) {
          resolve(window.google)
        } else {
          googlePromise = null
          reject(new Error('Google Sign-In failed to initialise'))
        }
      }

      script.onerror = () => {
        googlePromise = null
        reject(new Error('Could not load Google Sign-In'))
      }

      document.head.appendChild(script)
    })
  }

  return googlePromise
}
