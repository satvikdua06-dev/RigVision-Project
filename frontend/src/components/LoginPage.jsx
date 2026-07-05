import { useState } from 'react';
import { useNavigate, useLocation } from 'react-router-dom';
import useAuthStore from '../stores/useAuthStore';
import '../styles/Auth.css';

export default function LoginPage() {
  const navigate = useNavigate();
  const location = useLocation();
  const { login, error: authError, loading } = useAuthStore();

  const [formData, setFormData] = useState({ email: '', password: '' });
  const [localError, setLocalError] = useState('');

  const from = location.state?.from 
    ? (location.state.from.pathname + location.state.from.search) 
    : '/';

  const handleChange = (e) => {
    const { name, value } = e.target;
    setFormData(prev => ({ ...prev, [name]: value }));
    setLocalError('');
  };

  const handleSubmit = async (e) => {
    e.preventDefault();
    if (!formData.email || !formData.password) {
      setLocalError('Please fill in all fields');
      return;
    }
    const result = await login(formData.email, formData.password);
    if (result.success) navigate(from, { replace: true });
    else setLocalError(result.error);
  };

  return (
    <div className="auth-container">
      <div className="auth-card">

        <div className="auth-brand">
          <svg width="28" height="28" viewBox="0 0 28 28" fill="none">
            <rect width="28" height="28" rx="6" fill="#1e2330" />
            <path d="M14 6 L22 20 H6 Z" fill="none" stroke="#4a7cff" strokeWidth="1.5" strokeLinejoin="round" />
            <line x1="14" y1="13" x2="14" y2="19" stroke="#4a7cff" strokeWidth="1.5" />
            <circle cx="14" cy="11" r="1.5" fill="#4a7cff" />
          </svg>
          <span className="auth-brand-name">RigVision-3D</span>
        </div>
        <p className="auth-brand-sub">Digital Twin Monitoring System</p>

        <hr className="divider" />

        <form onSubmit={handleSubmit} className="auth-form">
          {(localError || authError) && (
            <div className="error-message">{localError || authError}</div>
          )}

          <div className="form-group">
            <label htmlFor="email">Email address</label>
            <input
              type="email" id="email" name="email"
              value={formData.email} onChange={handleChange}
              placeholder="you@rigvision.dev"
              disabled={loading} required
            />
          </div>

          <div className="form-group">
            <label htmlFor="password">Password</label>
            <input
              type="password" id="password" name="password"
              value={formData.password} onChange={handleChange}
              placeholder="••••••••"
              disabled={loading} required
            />
          </div>

          <button type="submit" className="btn-primary" disabled={loading}>
            {loading ? (
              <>
                <svg className="spinner" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
                  <circle cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" className="opacity-25" />
                  <path fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z" className="opacity-75" />
                </svg>
                Signing in...
              </>
            ) : 'Sign in'}
          </button>
        </form>

        <div className="auth-demo">
          <p className="demo-label">Demo credentials</p>
          <div className="demo-credentials">
            <code><span className="label">Email</span>security.manager@rigvision.dev</code>
            <code><span className="label">Password</span>OngcSecurity2026!</code>
          </div>
        </div>

      </div>
    </div>
  );
}