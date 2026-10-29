
import GoogleLoginButton from './GoogleLoginButton'

function LoginForm() {
  return (
    <div className="login-container">
      <div className="login-header">
        <span className="eyebrow">CUSTOMER SIGN IN</span>
        <h2>Welcome back</h2>
        <p>
          Sign in securely with Google to access your
          Netpoleon Marketplace account.
        </p>
      </div>

      <GoogleLoginButton />

      <p className="login-help">
        Access is available to existing authorised customers only.
      </p>
    </div>
  )
}

export default LoginForm
