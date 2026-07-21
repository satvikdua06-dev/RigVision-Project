import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom';
import LoginPage from './LoginPage';
import NotFoundPage from './NotFoundPage';
import ProtectedRoute from './ProtectedRoute';
import App from '../App';
import DiagnosticsLive from './DiagnosticsLive';
import ManualsViewer from './ManualsViewer';
import InsightsPage from './InsightsPage';

/**
 * AppRouter - Main router component
 * Handles auth routes (login/register) and protected routes (dashboard)
 */
export default function AppRouter() {
  return (
    <BrowserRouter>
      <Routes>
        {/* Public Auth Routes */}
        <Route path="/login" element={<LoginPage />} />
        <Route path="/register" element={<Navigate to="/login" replace />} />

        {/* Protected Dashboard Routes */}
        <Route
          path="/"
          element={
            <ProtectedRoute>
              <App />
            </ProtectedRoute>
          }
        />

        {/* Live diagnostics window (opened in a new tab from the anomaly alert) */}
        <Route
          path="/diagnostics/:eventId"
          element={
            <ProtectedRoute>
              <DiagnosticsLive />
            </ProtectedRoute>
          }
        />
        <Route
          path="/diagnostics"
          element={
            <ProtectedRoute>
              <DiagnosticsLive />
            </ProtectedRoute>
          }
        />

        {/* Full manuals viewer */}
        <Route
          path="/documents/manuals"
          element={
            <ProtectedRoute>
              <ManualsViewer />
            </ProtectedRoute>
          }
        />

        {/* Safety Insights Hub */}
        <Route
          path="/insights"
          element={
            <ProtectedRoute>
              <InsightsPage />
            </ProtectedRoute>
          }
        />

        {/* Fallback 404 */}
        <Route path="*" element={<NotFoundPage />} />
      </Routes>
    </BrowserRouter>
  );
}
