import { Navigate, useLocation } from 'react-router-dom';
import useAuthStore from '../stores/useAuthStore';

/**
 * ProtectedRoute - Wraps components that require authentication
 * Redirects to login if user is not authenticated
 */
export default function ProtectedRoute({ children }) {
  const { isAuthenticated, loading } = useAuthStore();
  const location = useLocation();

  if (loading) {
    return (
      <div style={{
        display: 'flex',
        justifyContent: 'center',
        alignItems: 'center',
        height: '100vh',
        background: 'linear-gradient(135deg, #667eea 0%, #764ba2 100%)',
        fontFamily: 'Segoe UI, sans-serif'
      }}>
        <div style={{ color: 'white', textAlign: 'center' }}>
          <h2>Loading...</h2>
          <p>Verifying authentication</p>
        </div>
      </div>
    );
  }

  return isAuthenticated ? children : <Navigate to="/login" state={{ from: location }} replace />;
}
