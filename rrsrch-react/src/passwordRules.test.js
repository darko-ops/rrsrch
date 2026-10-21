import { passwordChecks, passwordOk } from './passwordRules';

const failing = (pw, who) => passwordChecks(pw, who).filter((c) => !c.ok).map((c) => c.label);

test('passwords need length, a mix of character kinds, and nothing common or personal', () => {
  expect(failing('short1!A')).toEqual(['14 to 72 characters']);
  expect(failing('alllowercaseletters')).toEqual(['Three of: lowercase, uppercase, digits, symbols']);
  expect(failing('Password123!!!')).toEqual(['Not a common or predictable password']);
  expect(failing('Demetri2026!!x', { email: 'demetri@rrsrch.com' })).toEqual(["Doesn't contain your name or email"]);
  expect(failing('ada.lovelace!2026', { name: 'Ada Lovelace' })).toEqual(["Doesn't contain your name or email"]);
  expect(failing('x'.repeat(40) + 'A1!' + 'é'.repeat(20))).toEqual(['14 to 72 characters']);   // over 72 bytes
  expect(passwordOk('correct-Horse-battery-7')).toBe(true);
  expect(passwordOk('Tr0ub4dor&3xyz')).toBe(true);
  expect(passwordOk('')).toBe(false);
});
