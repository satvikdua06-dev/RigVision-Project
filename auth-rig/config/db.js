const mongoose = require('mongoose');
const User = require('../models/User');

const seedSecurityManager = async () => {
  try {
    const username = process.env.SECURITY_MANAGER_USERNAME || 'security_manager';
    const email = process.env.SECURITY_MANAGER_EMAIL || 'security.manager@rigvision.dev';
    const password = process.env.SECURITY_MANAGER_PASSWORD || 'OngcSecurity2026!';

    console.log('DEBUG SEEDER:', {
      env_email: process.env.SECURITY_MANAGER_EMAIL,
      local_email: email,
      local_email_lc: email.toLowerCase()
    });

    // Find by username or email to support self-healing of database typos
    let existingUser = await User.findOne({
      $or: [
        { username: username },
        { email: email.toLowerCase() }
      ]
    });

    if (!existingUser) {
      const securityManager = new User({
        username,
        email,
        password,
        role: 'admin',
        isActive: true
      });
      await securityManager.save();
      console.log(`🌱 Platform Security Manager seeded successfully (${email})`);
    } else {
      let modified = false;
      if (existingUser.email !== email.toLowerCase()) {
        console.log(`🔧 Correcting Security Manager email typo in DB from ${existingUser.email} to ${email}`);
        existingUser.email = email;
        modified = true;
      }
      if (existingUser.username !== username) {
        existingUser.username = username;
        modified = true;
      }
      if (modified) {
        existingUser.password = password;
        await existingUser.save();
        console.log(`✅ Platform Security Manager credentials updated successfully`);
      } else {
        console.log(`ℹ️ Platform Security Manager already exists (${existingUser.email})`);
      }
    }
  } catch (error) {
    console.error(`❌ Error seeding Platform Security Manager: ${error.message}`);
  }
};

const seedOperatorUser = async () => {
  try {
    const username = 'operator_user';
    const email = 'operator@rigvision.dev';
    const password = 'OngcOperator2026!';

    let existingUser = await User.findOne({
      $or: [
        { username: username },
        { email: email.toLowerCase() }
      ]
    });

    if (!existingUser) {
      const operator = new User({
        username,
        email,
        password,
        role: 'operator',
        isActive: true
      });
      await operator.save();
      console.log(`🌱 Platform Operator User seeded successfully (${email})`);
    } else {
      console.log(`ℹ️ Platform Operator User already exists (${existingUser.email})`);
    }
  } catch (error) {
    console.error(`❌ Error seeding Platform Operator User: ${error.message}`);
  }
};

const connectDB = async () => {
  try {
    const conn = await mongoose.connect(process.env.MONGO_URI, {
      serverSelectionTimeoutMS: 5000,
      retryWrites: true
    });

    console.log(`MongoDB Connected: ${conn.connection.host}`);

    // Seed security manager user
    await seedSecurityManager();

    // Seed operator user
    await seedOperatorUser();

    return conn;
  } catch (error) {
    console.error(`Error connecting to MongoDB: ${error.message}`);
    process.exit(1);
  }
};

module.exports = connectDB;
