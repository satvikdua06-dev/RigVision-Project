// Quick API test
const http = require('http');

function testAPI(method, path, body, token) {
  return new Promise((resolve, reject) => {
    const headers = {
      'Content-Type': 'application/json'
    };
    if (token) {
      headers['Authorization'] = `Bearer ${token}`;
    }
    const options = {
      hostname: 'localhost',
      port: 5000,
      path: path,
      method: method,
      headers: headers
    };

    const req = http.request(options, (res) => {
      let data = '';
      res.on('data', chunk => data += chunk);
      res.on('end', () => {
        try {
          resolve(JSON.parse(data));
        } catch {
          resolve(data);
        }
      });
    });

    req.on('error', reject);
    if (body) req.write(JSON.stringify(body));
    req.end();
  });
}

async function runTests() {
  console.log('\n=== Testing Auth-Rig API ===\n');

  // Test 1: Register (Should fail)
  console.log('1️⃣ Testing REGISTER (should be blocked)...');
  const registerRes = await testAPI('POST', '/api/auth/register', {
    username: 'testuser',
    email: 'test@rigvision.com',
    password: 'TestPassword123',
    passwordConfirm: 'TestPassword123'
  });
  console.log('Register Response:', JSON.stringify(registerRes, null, 2));
  
  if (registerRes.success) {
    console.log('   ❌ Registration was allowed! (Security Risk)');
    return;
  }
  console.log('   ✅ Registration successfully blocked\n');

  // Test 2: Login
  console.log('2️⃣ Testing LOGIN with pre-seeded Security Manager credentials...');
  const loginRes = await testAPI('POST', '/api/auth/login', {
    email: 'security.manager@rigvision.dev',
    password: 'OngcSecurity2026!'
  });
  console.log('Login Response:', JSON.stringify(loginRes, null, 2));
  
  if (!loginRes.success) {
    console.log('   ❌ Login failed');
    return;
  }
  const token = loginRes.token;
  console.log('   ✅ Login successful\n');

  // Test 3: Get current user
  console.log('3️⃣ Testing GET /api/auth/me...');
  const meRes = await testAPI('GET', '/api/auth/me', null, token);
  console.log('Me Response:', JSON.stringify(meRes, null, 2));
  if (meRes.success) {
    console.log('   ✅ Protected route working\n');
  } else {
    console.log('   ❌ Protected route failed\n');
  }

  // Test 4: Health check
  console.log('4️⃣ Testing HEALTH CHECK...');
  const healthRes = await testAPI('GET', '/health', null);
  console.log('Health Response:', JSON.stringify(healthRes, null, 2));
  if (healthRes.success) {
    console.log('   ✅ Health check working\n');
  } else {
    console.log('   ❌ Health check failed\n');
  }

  console.log('=== All tests completed ===\n');
}

runTests().catch(console.error);
