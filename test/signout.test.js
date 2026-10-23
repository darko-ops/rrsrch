// Signing out ends every browser's sign-in to the account; paired devices stay.  Run: npm run test:server
const test = require('node:test');
const assert = require('node:assert');
const { tokenRevoked } = require('../server');

test('after sign-out, browser tokens issued earlier stop working; later ones and devices still work', () => {
  const user = { web_tokens_after: 2000 };
  assert.strictEqual(tokenRevoked(user, { sub: 'u', iat: 1000 }), true);
  assert.strictEqual(tokenRevoked(user, { sub: 'u', iat: 2500 }), false);
  assert.strictEqual(tokenRevoked(user, { sub: 'u', dev: 'd1' }), false);
  assert.strictEqual(tokenRevoked({}, { sub: 'u', iat: 1000 }), false);
});

test('tokens_after still cuts off everything, devices included', () => {
  const user = { tokens_after: 2000 };
  assert.strictEqual(tokenRevoked(user, { sub: 'u', iat: 1000 }), true);
  assert.strictEqual(tokenRevoked(user, { sub: 'u', dev: 'd1' }), true);
});
