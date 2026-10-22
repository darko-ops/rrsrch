// The /join page (server.js joinPage): what an agent gets, and how close the Arena is.  Run: npm run test:server
const test = require('node:test');
const assert = require('node:assert');
const { joinPage } = require('../server');

test('/join says what an agent gets and counts independent operators toward the Arena', () => {
  const html = joinPage({ needs: { unanswered_questions: 2 }, arena: { operators: 3, needed: 8 } }, null);
  assert.match(html, /<h2 id="arena">What your agent gets<\/h2>/);
  assert.match(html, /<strong>Atoms<\/strong>/);
  assert.match(html, /<b>3 of 8<\/b>/);
  assert.match(html, /width:38%/);
});

test('without the arena count, /join still explains what an agent gets, with no progress bar', () => {
  const html = joinPage(null, null);
  assert.match(html, /What your agent gets/);
  assert.doesNotMatch(html, /class="bar"/);
});
