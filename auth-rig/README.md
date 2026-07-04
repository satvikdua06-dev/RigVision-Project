# Auth-Rig: Authentication Service for RigVision-3D

Complete authentication system with JWT tokens, MongoDB, and rate limiting.

## Features

✅ **User Registration & Login** — Email/username-based authentication
✅ **JWT Tokens** — Access tokens (1h) + refresh tokens (7d)
✅ **Rate Limiting** — Brute-force protection (5 attempts → 15min lock)
✅ **Password Security** — Bcrypt hashing (12 rounds)
✅ **Role-Based Access** — user, admin, operator roles
✅ **Account Lockout** — Automatic lockout after failed attempts
✅ **Session Management** — Login tracking, profile updates
✅ **Error Handling** — Comprehensive error middleware

## Quick Start

### 1. Install Dependencies
```bash
npm install
```

### 2. Configure Environment
Edit `.env`:
```env
PORT=5000
MONGO_URI=mongodb://admin:strong_password@localhost:27018/rigvision_auth?authSource=admin
JWT_SECRET=change_me_in_production
JWT_REFRESH_SECRET=change_me_in_production
```

### 3. Start Services
Make sure MongoDB is running:
```bash
docker compose up -d
```

### 4. Run Auth Server
```bash
npm run dev    # Development with hot-reload
npm start      # Production
```

Server runs on `http://localhost:5000`

---

## API Endpoints

### Public Routes

#### **POST** `/api/auth/register`
Register a new user.

**Request:**
```json
{
  "username": "john_doe",
  "email": "john@example.com",
  "password": "securepass123",
  "passwordConfirm": "securepass123"
}
```

**Response (201):**
```json
{
  "success": true,
  "message": "User registered successfully",
  "token": "eyJhbGc...",
  "refreshToken": "eyJhbGc...",
  "user": {
    "id": "507f1f77bcf86cd799439011",
    "username": "john_doe",
    "email": "john@example.com",
    "role": "user",
    "createdAt": "2026-06-15T10:00:00.000Z"
  }
}
```

---

#### **POST** `/api/auth/login`
Login with credentials.

**Request:**
```json
{
  "email": "john@example.com",
  "password": "securepass123"
}
```

**Response (200):**
```json
{
  "success": true,
  "message": "Login successful",
  "token": "eyJhbGc...",
  "refreshToken": "eyJhbGc...",
  "user": { ... }
}
```

---

#### **POST** `/api/auth/refresh-token`
Get a new access token using refresh token.

**Request:**
```json
{
  "refreshToken": "eyJhbGc..."
}
```

**Response (200):**
```json
{
  "success": true,
  "token": "eyJhbGc..."
}
```

---

### Protected Routes (require `Authorization: Bearer <token>`)

#### **GET** `/api/auth/me`
Get current user profile.

**Response (200):**
```json
{
  "success": true,
  "user": { ... }
}
```

---

#### **PUT** `/api/auth/profile`
Update user profile.

**Request:**
```json
{
  "username": "new_username",
  "email": "newemail@example.com"
}
```

---

#### **POST** `/api/auth/change-password`
Change password.

**Request:**
```json
{
  "currentPassword": "securepass123",
  "newPassword": "newsecurepass456",
  "confirmPassword": "newsecurepass456"
}
```

---

#### **POST** `/api/auth/logout`
Logout (mainly client-side, but endpoint provided).

---

### Admin Routes

#### **GET** `/api/auth/users`
Get all users (admin only).

**Response (200):**
```json
{
  "success": true,
  "users": [ ... ]
}
```

---

## Error Responses

**400 Bad Request:**
```json
{
  "success": false,
  "error": "Missing required fields"
}
```

**401 Unauthorized:**
```json
{
  "success": false,
  "error": "Invalid credentials"
}
```

**429 Too Many Requests:**
```json
{
  "success": false,
  "error": "Too many login attempts, please try again later"
}
```

---

## Token Usage

Include token in request headers:
```bash
curl -H "Authorization: Bearer eyJhbGc..." http://localhost:5000/api/auth/me
```

Or in cookies (auto-handled by browser).

---

## Project Structure

```
auth-rig/
├── index.js                 # Main entry point
├── .env                     # Environment config
├── package.json
│
├── config/
│   └── db.js               # MongoDB connection
│
├── models/
│   └── User.js             # User schema & methods
│
├── controllers/
│   └── authController.js   # Auth business logic
│
├── routes/
│   └── auth.js             # Route definitions
│
├── middleware/
│   ├── auth.js             # JWT verification
│   └── errorHandler.js     # Error handling
```

---

## Security Features

- **Helmet.js** — HTTP security headers
- **CORS** — Cross-origin resource sharing
- **Rate Limiting** — Account lockout after 5 failed attempts
- **Bcrypt** — Password hashing with 12 rounds
- **JWT** — Secure token-based sessions
- **Input Validation** — Schema-level MongoDB validation
- **Error Masking** — Generic error messages (no info leakage)
- **Cookie-based Auth** — Secure HttpOnly cookies supported

---

## Integration with RigVision Frontend

### Setup Frontend to Use Auth

**1. Store tokens after login:**
```javascript
// frontend/src/stores/useAuthStore.js
import { create } from 'zustand';

const useAuthStore = create((set) => ({
  token: localStorage.getItem('token'),
  user: JSON.parse(localStorage.getItem('user') || '{}'),
  
  login: async (email, password) => {
    const res = await fetch('http://localhost:5000/api/auth/login', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ email, password })
    });
    const data = await res.json();
    if (data.success) {
      localStorage.setItem('token', data.token);
      localStorage.setItem('user', JSON.stringify(data.user));
      set({ token: data.token, user: data.user });
    }
  }
}));
```

**2. Protect API calls:**
```javascript
const headers = {
  'Content-Type': 'application/json',
  'Authorization': `Bearer ${useAuthStore.getState().token}`
};

fetch('http://localhost:5000/api/auth/me', { headers });
```

---

## Running Tests

```bash
# Add Jest/Mocha for testing (optional)
npm install --save-dev jest @testing-library/react
```

---

## Production Checklist

- [ ] Generate strong JWT secrets
- [ ] Use environment-specific configs
- [ ] Enable HTTPS/TLS
- [ ] Set `NODE_ENV=production`
- [ ] Use managed MongoDB (Atlas, Azure, etc.)
- [ ] Enable MongoDB authentication
- [ ] Set up monitoring/logging
- [ ] Configure rate limiting per deployment
- [ ] Use secret management (Vault, AWS Secrets Manager, etc.)

---

## Troubleshooting

**MongoDB connection fails:**
```bash
# Check MongoDB is running
docker compose ps

# Restart MongoDB
docker compose restart mongo
```

**JWT verification errors:**
- Ensure token is fresh (check expiry)
- Verify JWT_SECRET matches between services

**Rate limiting blocking legitimate users:**
- Adjust `LOGIN_MAX_ATTEMPTS` and `ACCOUNT_LOCK_MINUTES` in `.env`

---

## License

MIT
