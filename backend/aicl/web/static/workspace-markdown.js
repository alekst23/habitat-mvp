(function () {
  "use strict";
  // A bounded Markdown subset built entirely from DOM nodes. Model output is
  // never HTML; images and arbitrary attributes cannot cause browser requests.
  var MAX_FORMATTED_LENGTH = 200000, MAX_NODES = 6000, MAX_DEPTH = 12;
  function element(tag, text) { var value = document.createElement(tag); if (text !== undefined) value.textContent = text; return value; }
  function publicLink(destination) {
    if (!/^https?:\/\//i.test(destination) || /[\s\\\u0000-\u001f\u007f]/.test(destination)) return null;
    try {
      var url = new URL(destination), host = url.hostname.toLowerCase();
      if (!['https:', 'http:'].includes(url.protocol) || url.username || url.password || !host || host === location.hostname.toLowerCase()) return null;
      // Relative/app routes, local hosts and IP literals are not model-authored
      // navigation targets. No resource is fetched by rendering a public link.
      if (!host.includes('.') || /^\d+(?:\.\d+){3}$/.test(host) || host.includes(':') || /(?:^|\.)(?:localhost|local|internal|test|invalid)$/.test(host)) return null;
      return url.href;
    } catch (_) { return null; }
  }
  function appendInline(parent, source, budget, depth, linksAllowed) {
    if (depth > MAX_DEPTH || budget.nodes >= MAX_NODES) { parent.append(document.createTextNode(source)); return; }
    var at = 0, plain = '';
    function flush() { if (plain) { parent.append(document.createTextNode(plain)); plain = ''; } }
    function formatted(tag, body) { flush(); budget.nodes += 1; var child = element(tag); appendInline(child, body, budget, depth + 1, linksAllowed); parent.append(child); }
    while (at < source.length) {
      if (budget.nodes >= MAX_NODES) { plain += source.slice(at); break; }
      var rest = source.slice(at, at + 4096), match;
      if (rest[0] === '\\' && /^\\[\\`*{}\[\]()#+\-.!_>|~]/.test(rest)) { plain += rest[1]; at += 2; continue; }
      if (rest[0] === '`') {
        var ticks = /^`+/.exec(rest)[0], close = source.indexOf(ticks, at + ticks.length);
        if (ticks.length <= 128 && close >= 0 && close < at + 4096 && source[close + ticks.length] !== '`') {
          flush(); budget.nodes += 1; parent.append(element('code', source.slice(at + ticks.length, close).replace(/\n/g, ' '))); at = close + ticks.length; continue;
        }
        plain += ticks; at += ticks.length; continue;
      }
      if ((rest[0] === '[' || rest.startsWith('![')) && (match = /^(!?)\[([^\[\]\n]*)\]\(/.exec(rest))) {
        var end = match[0].length, nesting = 1;
        // Bound and balance parentheses, including ordinary article URLs.
        while (end < rest.length && nesting && end < 4096) { if (rest[end] === '(') nesting += 1; if (rest[end] === ')') nesting -= 1; end += 1; }
        if (!nesting) {
          var destination = rest.slice(match[0].length, end - 1), href = !match[1] && linksAllowed ? publicLink(destination) : null;
          flush(); budget.nodes += 1;
          if (match[1]) parent.append(element('span', '[Image: ' + (match[2] || 'not loaded') + ']'));
          else if (href) {
            var link = element('a'); link.href = href; link.target = '_blank'; link.rel = 'noopener noreferrer'; link.referrerPolicy = 'no-referrer';
            appendInline(link, match[2] || destination, budget, depth + 1, false); parent.append(link);
          } else appendInline(parent, match[2] || destination, budget, depth + 1, false);
          at += end; continue;
        }
      }
      if ((rest.startsWith('**') || rest.startsWith('__')) && (match = /^(\*\*|__)(?=\S)([\s\S]*?\S)\1/.exec(rest))) { formatted('strong', match[2]); at += match[0].length; continue; }
      if ((rest[0] === '*' || rest[0] === '_') && (rest[0] !== '_' || !/[\w]/.test(source[at - 1] || '')) && (match = /^(\*|_)(?=\S)([^\n]*?\S)\1/.exec(rest))) { formatted('em', match[2]); at += match[0].length; continue; }
      plain += source[at]; at += 1;
    }
    flush();
  }
  function cells(line) { return line.trim().replace(/^\|/, '').replace(/\|$/, '').split(/(?<!\\)\|/).map(function (part) { return part.trim().replace(/\\\|/g, '|'); }); }
  function tableRule(line) { var parts = cells(line); return parts.length > 1 && parts.every(function (part) { return /^:?-{3,}:?$/.test(part); }); }
  function listItem(line) { return /^( {0,3})([-+*]|\d{1,6}[.)])\s+(.+)$/.exec(line); }
  function special(line) { return /^\s*$|^ {0,3}(?:#{1,6}\s|`{3,}|~{3,}|>|(?:[-*_]\s*){3,}$)/.test(line) || !!listItem(line); }
  function appendBlocks(parent, rows, budget, depth) {
    var at = 0;
    function block(tag, text) { budget.nodes += 1; var value = element(tag); appendInline(value, text, budget, depth, true); parent.append(value); return value; }
    if (depth > MAX_DEPTH) { parent.append(element('p', rows.join('\n'))); return; }
    while (at < rows.length) {
      if (budget.nodes >= MAX_NODES) { parent.append(element('p', rows.slice(at).join('\n'))); break; }
      var row = rows[at], match;
      if (!row.trim()) { at += 1; continue; }
      if ((match = /^ {0,3}(`{3,}|~{3,})[^`]*$/.exec(row))) {
        var fence = match[1], body = []; at += 1;
        while (at < rows.length && !new RegExp('^ {0,3}' + (fence[0] === '`' ? '`' : '~') + '{' + fence.length + ',}\\s*$').test(rows[at])) { body.push(rows[at]); at += 1; }
        at += at < rows.length ? 1 : 0; budget.nodes += 2; var pre = element('pre'); pre.append(element('code', body.join('\n'))); parent.append(pre); continue;
      }
      if ((match = /^ {0,3}(#{1,6})\s+(.+?)(?:\s+#+)?\s*$/.exec(row))) { block('h' + Math.min(6, match[1].length + 2), match[2]); at += 1; continue; }
      if (/^ {0,3}(?:[-*_]\s*){3,}$/.test(row)) { parent.append(element('hr')); budget.nodes += 1; at += 1; continue; }
      if (/^ {0,3}>/.test(row)) {
        var quoted = []; while (at < rows.length && /^ {0,3}>/.test(rows[at])) { quoted.push(rows[at].replace(/^ {0,3}> ?/, '')); at += 1; }
        var quote = element('blockquote'); budget.nodes += 1; appendBlocks(quote, quoted, budget, depth + 1); parent.append(quote); continue;
      }
      if (at + 1 < rows.length && row.includes('|') && tableRule(rows[at + 1]) && cells(row).length <= 32 && budget.nodes + cells(row).length + 5 < MAX_NODES) {
        var headers = cells(row), wrap = element('div'), table = element('table'), head = element('thead'), tr = element('tr'), bodyRows = element('tbody');
        wrap.className = 'workspace-markdown-table'; wrap.tabIndex = 0; wrap.setAttribute('role', 'region'); wrap.setAttribute('aria-label', 'Result table');
        headers.forEach(function (header) { var th = element('th'); th.scope = 'col'; appendInline(th, header, budget, depth, true); tr.append(th); budget.nodes += 1; }); head.append(tr); table.append(head, bodyRows); budget.nodes += 5; at += 2;
        while (at < rows.length && rows[at].trim() && rows[at].includes('|') && budget.nodes + headers.length + 1 < MAX_NODES) {
          var values = cells(rows[at]), tableRow = element('tr'); headers.forEach(function (_, index) { var td = element('td'); appendInline(td, values[index] || '', budget, depth, true); tableRow.append(td); budget.nodes += 1; }); bodyRows.append(tableRow); budget.nodes += 1; at += 1;
        }
        wrap.append(table); parent.append(wrap); continue;
      }
      if ((match = listItem(row))) {
        var ordered = /^\d/.test(match[2]), list = element(ordered ? 'ol' : 'ul'); budget.nodes += 1;
        if (ordered) list.start = parseInt(match[2], 10);
        while (at < rows.length && budget.nodes < MAX_NODES) {
          match = listItem(rows[at]); if (!match || /^\d/.test(match[2]) !== ordered) break;
          var indent = match[1].length + match[2].length + 1, itemRows = [match[3]], li = element('li'); at += 1; budget.nodes += 1;
          while (at < rows.length) {
            if (!rows[at].trim()) {
              if (at + 1 < rows.length && (listItem(rows[at + 1]) || rows[at + 1].startsWith(' '.repeat(indent)))) { itemRows.push(''); at += 1; continue; }
              break;
            }
            if (rows[at].startsWith(' '.repeat(indent))) { itemRows.push(rows[at].slice(indent)); at += 1; continue; }
            break;
          }
          appendBlocks(li, itemRows, budget, depth + 1); list.append(li);
        }
        parent.append(list); continue;
      }
      var paragraph = [row]; at += 1;
      while (at < rows.length && !special(rows[at]) && !(at + 1 < rows.length && rows[at].includes('|') && tableRule(rows[at + 1]))) { paragraph.push(rows[at]); at += 1; }
      block('p', paragraph.join('\n'));
    }
  }
  window.HabitatMarkdown = Object.freeze({ render: function (value) {
    var fragment = document.createDocumentFragment(), source = typeof value === 'string' ? value : '';
    if (source.length > MAX_FORMATTED_LENGTH) { var plain = element('pre', source); fragment.append(plain); return fragment; }
    appendBlocks(fragment, source.replace(/\r\n?/g, '\n').split('\n'), { nodes: 0 }, 0); return fragment;
  } });
}());
