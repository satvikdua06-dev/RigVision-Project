import { create } from 'zustand';

const AUTH_API = import.meta.env.VITE_AUTH_API || 'http://localhost:5000/api/auth';

const decodeUserFromToken = (token) => {
  if (!token) return null;
  try {
    const base64Url = token.split('.')[1];
    const base64 = base64Url.replace(/-/g, '+').replace(/_/g, '/');
    const jsonPayload = decodeURIComponent(window.atob(base64).split('').map(function (c) {
      return '%' + ('00' + c.charCodeAt(0).toString(16)).slice(-2);
    }).join(''));
    const payload = JSON.parse(jsonPayload);
    return {
      _id: payload.id,
      username: payload.username,
      email: payload.email,
      role: payload.role
    };
  } catch (e) {
    console.error('Error decoding JWT payload:', e);
    return null;
  }
};

const getInitialUser = () => {
  const token = sessionStorage.getItem('token');
  if (!token) return null;
  try {
    const userWithRole = decodeUserFromToken(token);
    if (!userWithRole || userWithRole.role !== 'admin') {
      sessionStorage.removeItem('token');
      sessionStorage.removeItem('refreshToken');
      return null;
    }
    return userWithRole;
  } catch (e) {
    return null;
  }
};

const useAuthStore = create((set, get) => ({
  // State
  user: getInitialUser(),
  token: sessionStorage.getItem('token') || null,
  refreshToken: sessionStorage.getItem('refreshToken') || null,
  isAuthenticated: !!sessionStorage.getItem('token'),
  loading: false,
  error: null,

  // Actions
  register: async (username, email, password, passwordConfirm) => {
    set({ loading: true, error: null });
    try {
      const res = await fetch(`${AUTH_API}/register`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ username, email, password, passwordConfirm })
      });

      const data = await res.json();
      if (!data.success) throw new Error(data.error);

      const userWithRole = decodeUserFromToken(data.token);
      if (!userWithRole || userWithRole.role !== 'admin') {
        throw new Error('Access denied');
      }

      sessionStorage.setItem('token', data.token);
      sessionStorage.setItem('refreshToken', data.refreshToken);

      set({
        user: userWithRole,
        token: data.token,
        refreshToken: data.refreshToken,
        isAuthenticated: true,
        loading: false
      });

      return { success: true, user: userWithRole };
    } catch (error) {
      const errorMsg = error.message || 'Registration failed';
      set({ error: errorMsg, loading: false });
      return { success: false, error: errorMsg };
    }
  },

  login: async (email, password) => {
    set({ loading: true, error: null });
    try {
      const res = await fetch(`${AUTH_API}/login`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ email, password })
      });

      const data = await res.json();
      if (!data.success) throw new Error(data.error);

      const userWithRole = decodeUserFromToken(data.token);
      if (!userWithRole || userWithRole.role !== 'admin') {
        throw new Error('Access denied: Only safety managers/admins are authorized to access this system.');
      }

      sessionStorage.setItem('token', data.token);
      sessionStorage.setItem('refreshToken', data.refreshToken);

      set({
        user: userWithRole,
        token: data.token,
        refreshToken: data.refreshToken,
        isAuthenticated: true,
        loading: false
      });

      return { success: true, user: userWithRole };
    } catch (error) {
      const errorMsg = error.message || 'Login failed';
      set({ error: errorMsg, loading: false });
      return { success: false, error: errorMsg };
    }
  },

  logout: async () => {
    try {
      const state = get();
      if (state.token) {
        await fetch(`${AUTH_API}/logout`, {
          method: 'POST',
          headers: {
            'Authorization': `Bearer ${state.token}`
          }
        });
      }
    } catch (error) {
      console.error('Logout error:', error);
    }

    sessionStorage.removeItem('token');
    sessionStorage.removeItem('refreshToken');

    set({
      user: null,
      token: null,
      refreshToken: null,
      isAuthenticated: false,
      error: null
    });
  },

  refreshAccessToken: async () => {
    try {
      const state = get();
      if (!state.refreshToken) throw new Error('No refresh token');

      const res = await fetch(`${AUTH_API}/refresh-token`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ refreshToken: state.refreshToken })
      });

      const data = await res.json();
      if (!data.success) throw new Error(data.error);

      sessionStorage.setItem('token', data.token);

      const updatedUser = decodeUserFromToken(data.token);

      set({
        token: data.token,
        user: updatedUser
      });

      return true;
    } catch (error) {
      console.error('Token refresh failed:', error);
      get().logout();
      return false;
    }
  },

  getMe: async () => {
    try {
      const state = get();
      if (!state.token) throw new Error('No token');

      const res = await fetch(`${AUTH_API}/me`, {
        headers: { 'Authorization': `Bearer ${state.token}` }
      });

      const data = await res.json();
      if (!data.success) throw new Error(data.error);

      set({ user: data.user });
      return data.user;
    } catch (error) {
      console.error('Failed to get user:', error);
      return null;
    }
  },

  updateProfile: async (username, email) => {
    set({ loading: true, error: null });
    try {
      const state = get();
      const res = await fetch(`${AUTH_API}/profile`, {
        method: 'PUT',
        headers: {
          'Content-Type': 'application/json',
          'Authorization': `Bearer ${state.token}`
        },
        body: JSON.stringify({ username, email })
      });

      const data = await res.json();
      if (!data.success) throw new Error(data.error);

      set({ user: data.user, loading: false });

      return { success: true, user: data.user };
    } catch (error) {
      const errorMsg = error.message || 'Update failed';
      set({ error: errorMsg, loading: false });
      return { success: false, error: errorMsg };
    }
  },

  changePassword: async (currentPassword, newPassword, confirmPassword) => {
    set({ loading: true, error: null });
    try {
      const state = get();
      const res = await fetch(`${AUTH_API}/change-password`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'Authorization': `Bearer ${state.token}`
        },
        body: JSON.stringify({ currentPassword, newPassword, confirmPassword })
      });

      const data = await res.json();
      if (!data.success) throw new Error(data.error);

      set({ loading: false, error: null });
      return { success: true };
    } catch (error) {
      const errorMsg = error.message || 'Password change failed';
      set({ error: errorMsg, loading: false });
      return { success: false, error: errorMsg };
    }
  },

  setAuthorizationHeader: () => {
    const state = get();
    if (state.token) {
      return { 'Authorization': `Bearer ${state.token}` };
    }
    return {};
  }
}));

export default useAuthStore;
