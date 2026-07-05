// Shared API auth helper.
//
// Set VITE_API_KEY (frontend .env) to match the backend's RIGVISION_API_KEY. When
// both are set, mutating requests carry the `X-API-Key` header; the backend rejects
// requests without it (401). When neither is set, auth is off (dev default).
const API_KEY = import.meta.env.VITE_API_KEY || ''

// Build request headers, attaching the API key when one is configured.
export function authHeaders(extra = {}) {
  return API_KEY ? { 'X-API-Key': API_KEY, ...extra } : { ...extra }
}
