require('dotenv').config();
const connectDB = require('./config/db');
connectDB().then(() => {
  console.log('Database check script finished.');
  process.exit(0);
}).catch(err => {
  console.error(err);
  process.exit(1);
});
