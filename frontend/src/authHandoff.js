// Auth handoff for windows opened via window.open (e.g. the live Diagnostics window).
//
// Auth lives in sessionStorage, which is PER-TAB and is NOT shared with tabs opened
// programmatically. So a freshly opened diagnostics tab would start logged out and
// bounce to /login. Here we copy the session from the opener (same-origin access is
// allowed) before the auth store initializes.
//
// MUST be imported FIRST in main.jsx — before AppRouter/useAuthStore — because
// useAuthStore reads sessionStorage at module-evaluation time.
try {
  if (!sessionStorage.getItem('token') && window.opener && !window.opener.closed) {
    const op = window.opener.sessionStorage
    const token = op.getItem('token')
    if (token) {
      sessionStorage.setItem('token', token)
      const refreshToken = op.getItem('refreshToken')
      const user = op.getItem('user')
      if (refreshToken) sessionStorage.setItem('refreshToken', refreshToken)
      if (user) sessionStorage.setItem('user', user)
    }
  }
} catch {
  // Opener closed or cross-origin — fall through to the normal login redirect.
}
