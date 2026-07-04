const express = require('express');
const authController = require('../controllers/authController');
const { protect, authorize } = require('../middleware/auth');
const rateLimit = require('express-rate-limit');

const router = express.Router();

// Rate limiters
const loginLimiter = rateLimit({
  windowMs: 15 * 60 * 1000,
  max: 5,
  skip: (req) => {
    // Skip rate limiting in development
    return process.env.NODE_ENV === 'development';
  }
});

const registerLimiter = rateLimit({
  windowMs: 60 * 60 * 1000,
  max: 3,
  skip: (req) => {
    return process.env.NODE_ENV === 'development';
  }
});

// Public routes
router.post('/register', (req, res) => {
  return res.status(403).json({
    success: false,
    error: 'Registration is disabled. Only pre-configured Platform Security Manager credentials can be used.'
  });
});
router.post('/login', loginLimiter, authController.login);
router.post('/refresh-token', authController.refreshToken);

// Protected routes
router.get('/me', protect, authController.getMe);
router.put('/profile', protect, authController.updateProfile);
router.post('/change-password', protect, authController.changePassword);
router.post('/logout', protect, authController.logout);

// Admin only routes (example)
router.get('/users', protect, authorize('admin'), async (req, res) => {
  try {
    const User = require('../models/User');
    const users = await User.find().select('-password');
    res.json({ 
      success: true,
      users 
    });
  } catch (error) {
    res.status(500).json({ 
      success: false,
      error: error.message 
    });
  }
});

module.exports = router;
