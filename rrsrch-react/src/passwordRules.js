/**
 * Password rules for email sign-ups, shown as a checklist while someone types. The server enforces the same
 * rules (passwordProblems in server.js); keep the two in step.
 */
export const PASSWORD_MIN = 14;
const PASSWORD_MAX_BYTES = 72; // bcrypt ignores everything after 72 bytes
const COMMON = new Set([
  'password', 'passw0rd', 'password1', 'password123', 'p@ssw0rd', 'qwerty', 'qwertyuiop', 'qwerty123',
  'letmein', 'welcome', 'welcome1', 'iloveyou', 'admin', 'administrator', 'monkey', 'dragon', 'football',
  'baseball', 'sunshine', 'princess', 'trustno1', 'changeme', 'rrsrch', 'research', '123456789012',
  '1234567890', 'abc123', '111111111111', 'qazwsxedc', '1q2w3e4r', 'zaq12wsx', 'superman', 'starwars',
]);

// bytes in UTF-8, as bcrypt counts them
const utf8Length = (s) => [...s].reduce((n, ch) => {
  const c = ch.codePointAt(0);
  return n + (c < 0x80 ? 1 : c < 0x800 ? 2 : c < 0x10000 ? 3 : 4);
}, 0);

export function passwordChecks(password, { name = '', email = '' } = {}) {
  const lower = password.toLowerCase();
  const stripped = lower.replace(/[^a-z0-9]/g, '');
  const kinds = [/[a-z]/, /[A-Z]/, /[0-9]/, /[^A-Za-z0-9]/].filter((re) => re.test(password)).length;
  const common = COMMON.has(lower) || COMMON.has(stripped)
    || [...COMMON].some((w) => w.length >= 6 && stripped.replace(/[0-9]+$/, '') === w);
  const predictable = /^(.)\1+$/.test(password) || 'abcdefghijklmnopqrstuvwxyz0123456789'.includes(lower)
    || '01234567890'.includes(lower) || 'qwertyuiopasdfghjklzxcvbnm'.includes(lower);
  const personal = [String(email).split('@')[0], ...String(name).split(/\s+/)]
    .map((x) => x.toLowerCase()).filter((x) => x.length >= 4);
  const bytes = utf8Length(password);
  return [
    { label: `${PASSWORD_MIN} to ${PASSWORD_MAX_BYTES} characters`, ok: password.length >= PASSWORD_MIN && bytes <= PASSWORD_MAX_BYTES },
    { label: 'Three of: lowercase, uppercase, digits, symbols', ok: kinds >= 3 },
    { label: 'Not a common or predictable password', ok: password.length > 0 && !common && !predictable },
    { label: 'Doesn\'t contain your name or email', ok: password.length > 0 && !personal.some((x) => lower.includes(x)) },
  ];
}

export const passwordOk = (password, who) => passwordChecks(password, who).every((c) => c.ok);
