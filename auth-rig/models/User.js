const mongoose = require('mongoose');
const bcrypt = require('bcrypt');

const userSchema = new mongoose.Schema({
  username: { 
    type: String, 
    required: true, 
    unique: true,
    trim: true,
    minlength: 3
  },
  email: { 
    type: String, 
    required: true, 
    unique: true,
    lowercase: true,
    match: /.+\@.+\..+/
  },
  password: { 
    type: String, 
    required: true,
    minlength: 6
  },
  role: { 
    type: String, 
    enum: ['user', 'admin', 'operator'], 
    default: 'user' 
  },
  loginAttempts: { 
    type: Number, 
    default: 0 
  },
  lockUntil: Date,
  lastLogin: Date,
  isActive: { 
    type: Boolean, 
    default: true 
  },
  createdAt: { 
    type: Date, 
    default: Date.now 
  },
  updatedAt: { 
    type: Date, 
    default: Date.now 
  }
});

// Hash password before saving
userSchema.pre('save', async function() {
  if (!this.isModified('password')) return;
  try {
    this.password = await bcrypt.hash(this.password, parseInt(process.env.BCRYPT_ROUNDS || 12));
    this.updatedAt = Date.now();
  } catch (error) {
    throw error;
  }
});

// Compare password method
userSchema.methods.comparePassword = async function(plainPassword) {
  return await bcrypt.compare(plainPassword, this.password);
};

// Check if account is locked
userSchema.methods.isLocked = function() {
  return this.lockUntil && this.lockUntil > Date.now();
};

// Increment login attempts
userSchema.methods.incLoginAttempts = function() {
  this.loginAttempts += 1;
  if (this.loginAttempts >= parseInt(process.env.LOGIN_MAX_ATTEMPTS || 5)) {
    this.lockUntil = new Date(Date.now() + parseInt(process.env.ACCOUNT_LOCK_MINUTES || 15) * 60 * 1000);
  }
  return this.save();
};

// Reset login attempts
userSchema.methods.resetLoginAttempts = function() {
  this.loginAttempts = 0;
  this.lockUntil = undefined;
  this.lastLogin = Date.now();
  return this.save();
};

// Hide sensitive fields in JSON
userSchema.methods.toJSON = function() {
  const user = this.toObject();
  delete user.password;
  delete user.lockUntil;
  delete user.loginAttempts;
  return user;
};

module.exports = mongoose.model('User', userSchema);
