const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');
const vm = require('node:vm');

const source = fs.readFileSync(path.join(__dirname, '../scripts/waitlist-google-apps-script.gs'), 'utf8');
const TOKEN = 'fixture_waitlist_token_' + 'x'.repeat(32);

function app(options = {}) {
  const rows = [];
  const formulas = [];
  const calls = { opens: 0, locks: 0, releases: 0, flushes: 0, writes: 0 };
  let held = false;
  let exists = false;
  const properties = { WAITLIST_TOKEN: TOKEN, WAITLIST_SPREADSHEET_ID: 'fixture_spreadsheet_id_123456', ...options.properties };
  const sheet = {
    getLastRow: () => rows.length,
    getMaxRows: () => 1000,
    insertRowsAfter: () => {},
    getRange(row, column, height = 1, width = 1) {
      function read(data) {
        return Array.from({ length: height }, (_, r) =>
          Array.from({ length: width }, (_, c) => data[row + r - 1]?.[column + c - 1] ?? ''));
      }
      function write(values, richText) {
        assert.equal(held, true, 'all writes must hold the script lock');
        if (options.writeFails) throw new Error('private upstream error');
        calls.writes++;
        values.forEach((valuesRow, r) => valuesRow.forEach((value, c) => {
          rows[row + r - 1] ??= [];
          formulas[row + r - 1] ??= [];
          const text = richText ? value.text : value;
          rows[row + r - 1][column + c - 1] = text;
          formulas[row + r - 1][column + c - 1] = !richText && String(text).startsWith('=') ? text : '';
        }));
        return this;
      }
      return {
        getValues: () => read(rows),
        getFormulas: () => read(formulas),
        setValues: values => write(values, false),
        setRichTextValues: values => write(values, true),
      };
    },
  };
  const context = vm.createContext({
    PropertiesService: { getScriptProperties: () => ({
      getProperty: key => properties[key] ?? null,
      setProperty: (key, value) => { properties[key] = value; },
    }) },
    LockService: { getScriptLock: () => ({
      tryLock() { calls.locks++; held = !options.lockFails; return held; },
      releaseLock() { assert.equal(held, true); held = false; calls.releases++; },
    }) },
    SpreadsheetApp: {
      openById(id) {
        calls.opens++;
        assert.equal(held, true, 'sheet access must hold the script lock');
        assert.equal(id, properties.WAITLIST_SPREADSHEET_ID);
        return {
          getSheetByName: name => { assert.equal(name, 'Waitlist'); return exists ? sheet : null; },
          insertSheet: name => { assert.equal(name, 'Waitlist'); exists = true; return sheet; },
        };
      },
      newRichTextValue() { return { setText(text) { return { build: () => ({ text }) }; } }; },
      flush() {
        assert.equal(held, true, 'flush must happen before releasing the lock');
        calls.flushes++;
        if (options.flushFails) throw new Error('private flush error');
        if (options.unconfirmedWrite) rows.splice(1);
      },
    },
    ContentService: {
      MimeType: { JSON: 'application/json' },
      createTextOutput(text) { return { text, setMimeType(type) { this.type = type; return this; } }; },
    },
  });
  vm.runInContext(source, context);
  function post(body, raw) {
    const response = context.doPost({ postData: { type: 'application/json', contents: raw ?? JSON.stringify(body) } });
    assert.equal(response.type, 'application/json');
    return JSON.parse(response.text);
  }
  return { post, rows, formulas, calls, context };
}

test('rejects unauthorized, malformed and invalid requests before sheet access', () => {
  const endpoint = app();
  for (const body of [
    { token: 'wrong', email: 'person@example.com' },
    { token: TOKEN, email: 'not-an-email' },
    { token: TOKEN, email: 'a\nb@example.com' },
    { token: TOKEN, email: 'a..b@example.com' },
    { token: TOKEN, email: 'a@-bad.example' },
    { token: TOKEN, email: 'ü@example.com' },
    { token: TOKEN, email: 'a'.repeat(65) + '@example.com' },
  ]) assert.deepEqual(endpoint.post(body), { ok: false });
  assert.deepEqual(endpoint.post(null, '{bad-json'), { ok: false });
  assert.deepEqual(endpoint.post(null, 'x'.repeat(4097)), { ok: false });
  assert.equal(endpoint.calls.opens, 0);
  assert.equal(endpoint.calls.locks, 0);
  assert.equal(typeof endpoint.context.doGet, 'undefined', 'there is no public read endpoint');
  const misconfigured = app({ properties: { WAITLIST_TOKEN: 'short' } });
  assert.deepEqual(misconfigured.post({ token: 'short', email: 'person@example.com' }), { ok: false });
  assert.equal(misconfigured.calls.opens, 0);
});

test('writes one normalized row, then acknowledges duplicates without appending', () => {
  const endpoint = app();
  assert.deepEqual(endpoint.post({ token: TOKEN, email: ' Person+Launch@Example.COM ' }), { ok: true });
  assert.equal(endpoint.calls.flushes, 1);
  assert.equal(endpoint.calls.releases, 1);
  assert.deepEqual(endpoint.rows[0], ['Email', 'Signed up at (UTC)']);
  assert.equal(endpoint.rows[1][0], 'person+launch@example.com');
  assert.match(endpoint.rows[1][1], /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z$/);
  const firstTimestamp = endpoint.rows[1][1];
  assert.deepEqual(endpoint.post({ token: TOKEN, email: 'PERSON+LAUNCH@example.com' }), { ok: true });
  assert.equal(endpoint.rows.length, 2);
  assert.equal(endpoint.rows[1][1], firstTimestamp);
  assert.equal(endpoint.calls.flushes, 2);
  assert.equal(endpoint.calls.releases, 2);
});

test('never acknowledges failed writes or flushes and always releases an acquired lock', () => {
  for (const failure of ['writeFails', 'flushFails', 'lockFails', 'unconfirmedWrite']) {
    const endpoint = app({ [failure]: true });
    assert.deepEqual(endpoint.post({ token: TOKEN, email: 'person@example.com' }), { ok: false });
    assert.equal(endpoint.calls.releases, failure === 'lockFails' ? 0 : 1);
    if (failure === 'lockFails') assert.equal(endpoint.calls.opens, 0);
  }
});

test('stores formula-like email local parts as literal rich text', () => {
  const endpoint = app();
  for (const email of ['=hello@example.com', '+launch@example.com', '-hello@example.com']) {
    assert.deepEqual(endpoint.post({ token: TOKEN, email }), { ok: true });
    const last = endpoint.rows.length - 1;
    assert.equal(endpoint.rows[last][0], email);
    assert.equal(endpoint.formulas[last][0], '');
  }
});
