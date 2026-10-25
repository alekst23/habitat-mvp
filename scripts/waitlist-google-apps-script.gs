/**
 * Private waitlist sink. Deploy as an owner-executed Apps Script web app.
 * Configure WAITLIST_TOKEN and WAITLIST_SPREADSHEET_ID in Script Properties.
 * Only doPost is exposed; no endpoint returns addresses or spreadsheet details.
 * See docs/waitlist-google-sheets.md. Never log request bodies or secrets.
 */

function waitlistJson_(ok) {
  return ContentService.createTextOutput(JSON.stringify({ ok: ok }))
    .setMimeType(ContentService.MimeType.JSON);
}

function waitlistEmail_(input) {
  if (typeof input !== 'string' || input.length > 320) return null;
  const email = input.trim().toLowerCase();
  if (!email || email.length > 254 || !/^[\x21-\x7e]+$/.test(email)) return null;
  const parts = email.split('@');
  if (parts.length !== 2) return null;
  const local = parts[0], domain = parts[1];
  // Conventional ASCII mailboxes; quoted local parts and international addresses
  // are deliberately outside this small form's accepted format.
  if (!local || local.length > 64 || !/^[a-z0-9.!#$%&'*+/=?^_`{|}~-]+$/.test(local)
      || local.startsWith('.') || local.endsWith('.') || local.includes('..')) return null;
  const labels = domain.split('.');
  if (labels.length < 2 || !labels.every(function (label) {
    return /^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$/.test(label);
  })) return null;
  return email;
}

function waitlistTokenMatches_(expected, supplied) {
  if (typeof expected !== 'string' || !/^[A-Za-z0-9_-]{32,128}$/.test(expected)
      || typeof supplied !== 'string' || supplied.length !== expected.length) return false;
  let difference = 0;
  for (let i = 0; i < expected.length; i++) difference |= expected.charCodeAt(i) ^ supplied.charCodeAt(i);
  return difference === 0;
}

function doPost(event) {
  try {
    const post = event && event.postData;
    if (!post || typeof post.contents !== 'string' || post.contents.length > 4096
        || !/^application\/json(?:\s*;|$)/i.test(post.type || '')) return waitlistJson_(false);
    const body = JSON.parse(post.contents);
    if (!body || typeof body !== 'object' || Array.isArray(body)) return waitlistJson_(false);
    const properties = PropertiesService.getScriptProperties();
    if (!waitlistTokenMatches_(properties.getProperty('WAITLIST_TOKEN'), body.token)) return waitlistJson_(false);
    const email = waitlistEmail_(body.email);
    const spreadsheetId = properties.getProperty('WAITLIST_SPREADSHEET_ID');
    if (!email || !/^[A-Za-z0-9_-]{20,200}$/.test(spreadsheetId || '')) return waitlistJson_(false);

    // Use a script lock: document locks are unavailable to standalone/web apps.
    const lock = LockService.getScriptLock();
    if (!lock.tryLock(5000)) return waitlistJson_(false);
    let confirmed = false;
    try {
      const spreadsheet = SpreadsheetApp.openById(spreadsheetId);
      const sheet = spreadsheet.getSheetByName('Waitlist') || spreadsheet.insertSheet('Waitlist');
      if (sheet.getLastRow() === 0) sheet.getRange(1, 1, 1, 2).setValues([['Email', 'Signed up at (UTC)']]);
      const header = sheet.getRange(1, 1, 1, 2).getValues()[0];
      if (header[0] !== 'Email' || header[1] !== 'Signed up at (UTC)') throw new Error('Invalid waitlist layout');
      const lastRow = sheet.getLastRow();
      const entries = lastRow > 1 ? sheet.getRange(2, 1, lastRow - 1, 2).getValues() : [];
      const existing = entries.findIndex(function (row) {
        return typeof row[0] === 'string' && row[0].trim().toLowerCase() === email;
      });
      const rowNumber = existing >= 0 ? existing + 2 : lastRow + 1;
      if (existing < 0) {
        if (rowNumber > sheet.getMaxRows()) sheet.insertRowsAfter(sheet.getMaxRows(), 1000);
        // Rich text writes explicit text, including a leading '=' or '+'. Using
        // setValues(email) would allow Sheets to interpret '=' as a formula.
        const text = function (value) { return SpreadsheetApp.newRichTextValue().setText(value).build(); };
        sheet.getRange(rowNumber, 1, 1, 2).setRichTextValues([[text(email), text(new Date().toISOString())]]);
      }
      // Apply pending writes while holding the lock, then verify the stored row.
      // A timeout after a successful write is safe to retry: deduplication happens
      // under this same lock and returns the same receipt.
      SpreadsheetApp.flush();
      const savedRange = sheet.getRange(rowNumber, 1, 1, 2);
      const saved = savedRange.getValues()[0];
      confirmed = typeof saved[0] === 'string' && saved[0].trim().toLowerCase() === email
        && typeof saved[1] === 'string' && /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z$/.test(saved[1])
        && savedRange.getFormulas()[0].every(function (formula) { return formula === ''; });
    } finally {
      lock.releaseLock();
    }
    return waitlistJson_(confirmed);
  } catch (_) {
    // Apps Script ContentService cannot set arbitrary response status codes.
    // The backend must inspect this JSON receipt, not just HTTP 200.
    return waitlistJson_(false);
  }
}

/** Run once from the bound script editor, never from a web request. */
function setupBoundWaitlist() {
  const spreadsheet = SpreadsheetApp.getActiveSpreadsheet();
  if (!spreadsheet) throw new Error('Open this script from its waitlist spreadsheet first.');
  PropertiesService.getScriptProperties().setProperty('WAITLIST_SPREADSHEET_ID', spreadsheet.getId());
}
