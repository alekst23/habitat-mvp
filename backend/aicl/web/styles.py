"""Self-contained styles for the server-rendered Habitat owner experience."""

CSS = r"""
@layer reset, base, components, responsive;
@layer reset {
  *, *::before, *::after { box-sizing: border-box; }
  body, h1, h2, h3, p, ul, ol, fieldset { margin: 0; }
  button, input, textarea, select { font: inherit; }
  button, a, input, textarea, select { -webkit-tap-highlight-color: transparent; }
  img, svg { max-width: 100%; }
  [hidden] { display: none !important; }
}
@layer base {
  :root {
    --canvas: #f5f5ef; --paper: #fff; --ink: #203c31; --text: #31463d;
    --muted: #68776e; --line: #dfe5dc; --green: #254f3d; --green-hover: #193e2c;
    --sage: #eaf0e4; --sage-strong: #c2d3ae; --clay: #a75d3d; --clay-light: #f8eee5;
    --red: #993a36; --red-light: #fcf0ed; --radius: 16px;
    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
    font-size: 14px; color: var(--text); background: var(--canvas);
    font-synthesis: none; text-rendering: optimizeLegibility;
  }
  body { line-height: 1.55; overflow-wrap: anywhere; }
  a { color: var(--green); text-underline-offset: 3px; }
  a:hover { color: var(--green-hover); }
  h1, h2, h3 { color: var(--ink); }
  h1 { font-family: Georgia, 'Times New Roman', serif; font-size: clamp(30px, 3.4vw, 44px); font-weight: 400; letter-spacing: -1.5px; line-height: 1.14; }
  h2 { font-size: 18px; font-weight: 650; letter-spacing: -.35px; line-height: 1.4; }
  h3 { font-size: 15px; font-weight: 650; }
  p + p { margin-top: 12px; }
  code { background: #eef1ea; border-radius: 4px; padding: 2px 5px; font-size: .86em; overflow-wrap: anywhere; }
  button, .button {
    display: inline-flex; align-items: center; justify-content: center; gap: 8px;
    min-height: 42px; padding: 10px 17px; border: 1px solid transparent; border-radius: 8px;
    background: var(--green); color: #fff; font-weight: 600; font-size: 13px; line-height: 1.4;
    text-decoration: none; cursor: pointer; transition: background .15s, border-color .15s, box-shadow .15s;
  }
  button:hover, .button:hover { background: var(--green-hover); color: #fff; }
  button:disabled { cursor: wait; opacity: .58; }
  .secondary { background: #fff; color: var(--ink); border-color: #cfd8cd; }
  .secondary:hover { color: var(--ink); background: #f2f5ee; border-color: #a8b6a5; }
  .ghost { background: transparent; color: var(--green); border-color: transparent; }
  .ghost:hover { background: var(--sage); color: var(--green); }
  .danger { background: #fff; color: var(--red); border-color: #e7c9c2; }
  .danger:hover { background: var(--red-light); color: var(--red); border-color: #ce9990; }
  .small { min-height: 34px; padding: 7px 12px; font-size: 12px; }
  :focus-visible { outline: 3px solid #9a6f32; outline-offset: 3px; }
  input:not([type=hidden]):not([type=checkbox]):not([type=radio]), textarea, select {
    display: block; width: 100%; min-width: 0; min-height: 44px; padding: 10px 12px;
    border: 1px solid #cdd6cc; border-radius: 8px; background: #fff; color: #203c31;
    box-shadow: 0 1px 2px #1a312008; transition: border-color .15s;
  }
  input:hover, textarea:hover, select:hover { border-color: #a4b39d; }
  input:focus, textarea:focus, select:focus { border-color: var(--green); }
  input::placeholder, textarea::placeholder { color: #8a958c; }
  textarea { resize: vertical; min-height: 140px; line-height: 1.6; }
  input[type=checkbox], input[type=radio] { width: 17px; height: 17px; accent-color: var(--green); flex: 0 0 17px; margin: 3px 0 0; }
  label { font-weight: 550; font-size: 13px; color: #30483b; }
  fieldset { border: 0; padding: 0; min-width: 0; }
  legend { font-size: 15px; font-weight: 650; margin-bottom: 12px; padding: 0; }
  table { border-collapse: collapse; width: 100%; font-size: 12px; }
  th { text-align: left; padding: 12px 16px; background: #f6f7f2; color: #68776e; font-weight: 600; white-space: nowrap; }
  td { padding: 13px 16px; border-top: 1px solid #e8ece4; font-variant-numeric: tabular-nums; }
  td:first-child { color: #2e493a; font-weight: 550; }
  tbody tr:hover { background: #fbfcf8; }
  ul, ol { padding-left: 22px; }
  ::selection { background: #d7e4c9; }
}
@layer components {
  .skip-link { position: fixed; left: 12px; top: -70px; z-index: 100; padding: 12px 18px; border-radius: 8px; background: var(--green); color: white; }
  .skip-link:focus { top: 12px; color: white; }
  .app-shell { min-height: 100vh; display: grid; grid-template-columns: 196px minmax(0, 1fr); --radius: 12px; }
  .sidebar { position: sticky; top: 0; align-self: start; height: 100vh; overflow-y: auto; background: #1f3d30; color: #eaf0e6; padding: 22px 12px 18px; display: flex; flex-direction: column; }
  .brand { display: flex; align-items: center; gap: 11px; color: inherit; text-decoration: none; }
  .brand:hover { color: inherit; }
  .brand-mark { width: 35px; height: 40px; flex: 0 0 35px; display: grid; place-items: center; color: #c9d9b6; }
  .brand-mark svg { width: 35px; height: 40px; }
  .brand-name { display: block; font-size: 24px; font-family: Georgia, serif; letter-spacing: -.6px; line-height: 1.15; }
  .brand-tagline { display: block; font-size: 9px; letter-spacing: 1.65px; text-transform: uppercase; opacity: .65; margin-top: 4px; }
  .sidebar .brand { gap: 9px; padding: 0 5px; }
  .sidebar .brand-mark, .sidebar .brand-mark svg { width: 28px; height: 32px; }
  .sidebar .brand-mark { flex-basis: 28px; }
  .sidebar .brand-name { font-size: 23px; }
  .sidebar .brand-tagline { font-size: 8px; letter-spacing: 1px; }
  .nav-list { padding: 0; list-style: none; display: grid; gap: 4px; margin-top: 28px; }
  .nav-link { display: flex; align-items: center; gap: 10px; border-radius: 7px; min-height: 42px; padding: 10px 12px; color: #cad8c9; text-decoration: none; font-size: 13px; font-weight: 500; }
  .nav-link:hover { color: #fff; background: #ffffff0d; }
  .nav-link.active, .nav-link[aria-current=page] { background: #d7e3c914; color: #f5f9ee; box-shadow: inset 3px 0 #bed0a4; }
  .nav-icon { width: 19px; height: 19px; display: grid; place-items: center; opacity: .9; }
  .nav-icon svg { width: 18px; height: 18px; }
  .sidebar-footer { margin-top: auto; padding: 16px 6px 0; border-top: 1px solid #ffffff1f; }
  .account-identity { display: flex; align-items: center; gap: 10px; min-width: 0; }
  .account-avatar { width: 34px; height: 34px; flex: 0 0 34px; display: grid; place-items: center; border: 1px solid #ffffff26; border-radius: 50%; background: #ffffff0d; color: #dce7d7; font-size: 14px; font-weight: 600; }
  .account-copy { min-width: 0; }
  .account-status { display: block; color: #afc1af; font-size: 10px; }
  .account-name { display: block; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; color: #f5f9ee; font-size: 13px; font-weight: 600; }
  .sidebar-account form { margin-top: 12px; }
  .account-logout { width: 100%; justify-content: flex-start; min-height: 40px; padding: 9px 10px; background: transparent; border-color: #ffffff26; color: #dce7d7; font-size: 12px; font-weight: 500; }
  .account-logout:hover { background: #ffffff0d; border-color: #ffffff40; }
  .app-main { min-width: 0; }
  .topbar { min-height: 44px; padding: 10px 24px; display: flex; align-items: center; justify-content: space-between; gap: 16px; border-bottom: 1px solid var(--line); background: #fafbf7; }
  .breadcrumb { color: #778277; font-size: 12px; display: flex; align-items: center; gap: 12px; }
  .breadcrumb a { text-decoration: none; color: #778277; }
  .breadcrumb strong, .breadcrumb span:last-child { font-weight: 500; color: #3e5145; }
  .environment-badge { display: inline-flex; align-items: center; gap: 7px; border: 1px solid #d8e0cf; background: #eff3e8; border-radius: 30px; padding: 5px 10px; color: #5d7053; font-size: 10px; font-weight: 650; white-space: nowrap; }
  .environment-badge::before { content: ''; width: 5px; height: 5px; border-radius: 50%; background: #7b915f; }
  .page-content { padding: 36px 40px 64px; max-width: 1540px; margin: 0 auto; }
  .page-header { display: flex; align-items: flex-end; justify-content: space-between; gap: 24px; margin-bottom: 28px; }
  .page-header > *, .card-header > *, .breadcrumb > * { min-width: 0; }
  .eyebrow, .kicker { color: #77816f; font-size: 10px; font-weight: 700; letter-spacing: 1.7px; text-transform: uppercase; display: block; margin-bottom: 10px; }
  .page-subtitle { max-width: 640px; font-size: 13px; color: var(--muted); margin-top: 12px; line-height: 1.65; }
  .page-actions, .button-row { display: flex; gap: 10px; align-items: center; flex-wrap: wrap; }
  .page-actions { flex-shrink: 0; }
  .muted, .field-hint { color: var(--muted); }
  .field-hint { font-size: 12px; line-height: 1.55; font-weight: 400; }
  .card { background: var(--paper); border: 1px solid var(--line); border-radius: var(--radius); min-width: 0; overflow: clip; box-shadow: 0 2px 3px #182f1c02; }
  .card-header { padding: 22px 24px 18px; display: flex; gap: 16px; align-items: flex-start; justify-content: space-between; border-bottom: 1px solid #edf0e8; }
  .card-header p { color: var(--muted); font-size: 12px; margin-top: 5px; }
  .card-body { padding: 24px; }
  .card-body > * + * { margin-top: 18px; }
  .card-body > input[type=hidden] + * { margin-top: 0; }
  .section-heading { display: flex; align-items: center; justify-content: space-between; gap: 16px; margin: 30px 0 16px; }
  .section-heading p { color: var(--muted); font-size: 12px; margin-top: 4px; }
  .stat-grid { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 16px; margin-bottom: 26px; }
  .stat-grid:has(> :nth-child(4)) { grid-template-columns: repeat(4, minmax(0, 1fr)); }
  .stat-card { background: #fff; border: 1px solid var(--line); border-radius: 12px; padding: 20px 22px; min-width: 0; position: relative; }
  .stat-label { font-size: 11px; color: var(--muted); font-weight: 500; display: block; }
  .stat-value { font-size: clamp(23px, 2.5vw, 32px); color: var(--ink); font-weight: 500; letter-spacing: -1px; font-variant-numeric: tabular-nums; line-height: 1.35; display: block; margin-top: 8px; }
  .stat-value small { font-size: 13px; letter-spacing: 0; color: var(--muted); }
  .stat-note { color: #829078; font-size: 11px; display: block; margin-top: 7px; }
  .agent-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(min(100%, 300px), 1fr)); list-style: none; padding: 0; gap: 18px; }
  .agent-card-item { display: flex; min-width: 0; }
  .agent-card { background: white; border: 1px solid var(--line); border-radius: var(--radius); padding: 24px; display: flex; flex: 1; flex-direction: column; gap: 16px; color: var(--text); text-decoration: none; transition: border-color .15s, box-shadow .15s; min-width: 0; }
  .agent-card:hover, .agent-card:focus-visible { border-color: #aabca0; box-shadow: 0 5px 20px #203c3108; color: var(--text); }
  .agent-avatar { width: 42px; height: 42px; border-radius: 12px; background: #edf1e5; color: #6a8059; display: grid; place-items: center; font-size: 20px; font-family: Georgia, serif; flex: 0 0 42px; }
  .agent-meta { display: flex; align-items: center; justify-content: space-between; gap: 12px; }
  .agent-card h3 { color: var(--ink); font-size: 18px; }
  .agent-card p { color: var(--muted); font-size: 12px; overflow-wrap: anywhere; }
  .agent-card > .card-body { padding: 0; }
  .card-footer { margin-top: auto; padding-top: 16px; border-top: 1px solid #edf0e8; display: flex; gap: 10px; align-items: center; justify-content: space-between; color: #73816c; font-size: 11px; }
  .status-badge { display: inline-flex; align-items: center; gap: 6px; font-size: 10px; font-weight: 650; text-transform: capitalize; border: 1px solid #dbe2d4; border-radius: 20px; padding: 4px 9px; background: #f2f5ec; color: #60734f; white-space: nowrap; }
  .status-badge::before { content: ''; width: 5px; height: 5px; background: currentColor; border-radius: 50%; }
  .status-badge.active { background: #eaf3e9; border-color: #d1e2cd; color: #3c7147; }
  .status-badge.draft, .status-badge.archived { background: #f1f2ed; color: #737c6e; border-color: #e1e5dc; }
  .status-badge.gated, .status-badge.paused { background: #faf0e4; color: #98602e; border-color: #efdac1; }
  .status-badge.revoked { background: #fbefeb; color: #a25a46; border-color: #efdad2; }
  .empty-state { text-align: center; padding: 42px 28px; background: #fff; border: 1px dashed #cfdac7; border-radius: var(--radius); }
  .empty-state p { color: var(--muted); font-size: 13px; max-width: 430px; margin: 9px auto 20px; }
  .empty-illustration { width: 60px; height: 60px; background: var(--sage); border-radius: 18px; display: grid; place-items: center; margin: 0 auto 18px; color: #6d8657; font-size: 28px; }
  .form-grid { display: grid; gap: 22px; }
  .form-grid + fieldset { margin-top: 28px; }
  fieldset > .field-hint { margin-bottom: 14px; }
  .form-actions { display: flex; align-items: center; gap: 16px; flex-wrap: wrap; padding-top: 24px; margin-top: 24px; border-top: 1px solid var(--line); }
  .workspace-footer { display: flex; align-items: center; justify-content: space-between; gap: 20px; border-top: 1px solid var(--line); padding-top: 20px; margin-top: 34px; font-size: 11px; }
  .field { display: grid; gap: 7px; min-width: 0; }
  .capability-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 10px; }
  .capability-option { display: flex; gap: 11px; align-items: flex-start; background: #fcfdf9; border: 1px solid var(--line); border-radius: 9px; padding: 14px; cursor: pointer; font-weight: 400; min-width: 0; }
  .capability-option:hover { border-color: #9fb393; }
  .capability-option:has(input:checked) { border-color: #b6c9a6; background: #f0f5e9; }
  .capability-copy { display: grid; gap: 4px; min-width: 0; }
  .capability-title { color: #345039; font-weight: 600; font-size: 12px; }
  .capability-description { font-size: 11px; color: var(--muted); line-height: 1.55; }
  .notice { padding: 14px 17px; border: 1px solid #d9e3cf; border-radius: 10px; background: #f0f5e9; color: #4f6b3e; font-size: 12px; margin-bottom: 20px; overflow-wrap: anywhere; }
  .notice p + p { margin-top: 6px; }
  .notice.error, .notice[role=alert] { background: var(--red-light); border-color: #eed3cc; color: #8b463c; }
  .notice.info { background: #f4f2e8; border-color: #e7e2cf; color: #756c4c; }
  .notice:empty { display: none; }
  .split-layout { display: grid; grid-template-columns: minmax(0, 1fr) 280px; align-items: start; gap: 24px; }
  .guide-card { padding: 25px; background: #edf1e4; border: 1px solid #dce3d0; border-radius: var(--radius); }
  .guide-card p { font-size: 12px; color: #65735a; margin-top: 10px; }
  .steps { list-style: none; padding: 0; display: grid; gap: 22px; margin-top: 25px; }
  .steps li { display: flex; align-items: flex-start; gap: 12px; font-size: 12px; }
  .steps p { margin-top: 3px; }
  .step-number { border: 1px solid #c7d2ba; background: #f5f7ee; width: 26px; height: 26px; border-radius: 50%; display: grid; place-items: center; color: #637952; font-size: 11px; flex-shrink: 0; }
  .conversation { list-style: none; padding: 26px; display: grid; gap: 20px; min-height: 240px; }
  .message { max-width: 88%; padding: 16px 18px; background: #f3f5ee; border: 1px solid #e3e8dc; border-radius: 0 13px 13px 13px; color: #40523f; font-size: 13px; overflow-wrap: anywhere; }
  .message.user { justify-self: end; background: #284b38; border-color: #284b38; color: #edf3e8; border-radius: 13px 0 13px 13px; }
  .message-label { display: block; text-transform: uppercase; font-size: 9px; letter-spacing: 1.1px; margin-bottom: 7px; opacity: .7; }
  .message-text { white-space: pre-wrap; }
  .conversation-placeholder { display: grid; justify-items: center; text-align: center; align-content: center; gap: 16px; color: var(--muted); font-size: 12px; }
  .chat-card > .card-body { padding: 22px 24px 0; }
  .chat-card .conversation { padding-left: 0; padding-right: 0; }
  .composer-input { display: flex; align-items: center; gap: 10px; margin-top: 8px; }
  .composer-input input { flex: 1; }
  .composer { border-top: 1px solid var(--line); padding: 22px 24px; background: #fdfefb; }
  .composer .field { flex: 1; }
  .composer .inline-form { align-items: end; }
  .detail-grid { display: grid; grid-template-columns: minmax(0, 1.65fr) minmax(290px, 1fr); gap: 22px; align-items: start; }
  .main-column, .side-column { display: grid; gap: 22px; min-width: 0; }
  .panel { scroll-margin-top: 24px; }
  .section-anchor { scroll-margin-top: 24px; }
  nav.section-anchor { display: flex; gap: 22px; margin: -5px 0 25px; padding-bottom: 12px; border-bottom: 1px solid var(--line); overflow-x: auto; }
  nav.section-anchor a { white-space: nowrap; color: var(--muted); font-size: 12px; text-decoration: none; padding: 8px 0; }
  nav.section-anchor a:hover { color: var(--green); }
  nav.section-anchor .task-nav { color: var(--green); font-weight: 700; }
  .simulation-note { padding: 10px 14px; margin-bottom: 20px; font-size: 11px; }
  .controls-heading { margin-top: 36px; padding-top: 28px; border-top: 1px solid var(--line); }
  .control-diagnostics > summary { display: flex; align-items: center; justify-content: space-between; gap: 14px; padding: 20px 24px; cursor: pointer; list-style: none; }
  .control-diagnostics > summary::-webkit-details-marker { display: none; }
  .control-diagnostics > summary > span:first-child { display: grid; gap: 5px; }
  .control-diagnostics > summary::after { content: '+'; font-size: 20px; color: var(--green); }
  .control-diagnostics[open] > summary { border-bottom: 1px solid var(--line); }
  .control-diagnostics[open] > summary::after { content: '−'; }
  #budgets, #capabilities, #activity { margin-top: 26px; }
  #activity > section + section { margin-top: 22px; }
  .limit-grid { margin: 16px 0 10px; }
  form > .capability-grid { margin-bottom: 20px; }
  #budget-units { margin-bottom: 16px; }
  .table-wrap { overflow-x: auto; -webkit-overflow-scrolling: touch; }
  .data-table { min-width: 450px; }
  .data-table td { white-space: nowrap; overflow-wrap: normal; }
  .limit-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 16px; }
  .inline-form { display: flex; flex-wrap: wrap; align-items: end; gap: 10px; }
  .inline-form .field, .inline-form > input:not([type=hidden]), .inline-form > select { flex: 1; min-width: 130px; }
  .inline-form label { width: 100%; }
  .activity-list { padding: 0; list-style: none; display: grid; }
  .activity-item { padding: 13px 0; border-bottom: 1px solid #edf0e8; display: flex; align-items: flex-start; gap: 12px; min-width: 0; font-size: 12px; }
  .activity-item:last-child { border-bottom: 0; padding-bottom: 0; }
  .activity-item:first-child { padding-top: 0; }
  .activity-icon { width: 26px; height: 26px; border-radius: 50%; display: grid; place-items: center; background: #eef3e8; color: #79915f; flex-shrink: 0; font-size: 12px; }
  .activity-item p { overflow-wrap: anywhere; }
  .connection-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 20px; margin-bottom: 26px; }
  .connection-card { padding: 26px; background: #fff; border: 1px solid var(--line); border-radius: var(--radius); display: grid; gap: 17px; }
  .connection-card p { color: var(--muted); font-size: 12px; }
  .provider-icon { width: 42px; height: 42px; border-radius: 12px; display: grid; place-items: center; background: #f7eee5; color: #a96445; font-family: Georgia, serif; font-size: 22px; }
  .attachment-row { padding: 16px 0; border-bottom: 1px solid #e8ece4; }
  .attachment-row:first-child { padding-top: 0; }
  .attachment-row:last-child { padding-bottom: 0; border: 0; }
  .attachment-row form { margin-top: 10px; }
  .domain-list { padding: 0; list-style: none; margin-bottom: 18px; }
  .domain-list li { display: flex; align-items: center; justify-content: space-between; gap: 12px; padding: 9px 0; border-bottom: 1px solid #edf0e8; overflow-wrap: anywhere; }
  .preview-grid { display: grid; grid-template-columns: auto 1fr; gap: 6px 12px; font-size: 12px; margin: 12px 0; overflow-wrap: anywhere; }
  .work-result { margin-top: 14px; font-size: 12px; }
  .work-result:empty { display: none; }
  .public-shell { min-height: 100vh; }
  .public-content { max-width: none; padding: 0; }
  .judge-intro { width: calc(100% - 40px); max-width: 760px; margin: 48px auto 64px; }
  .judge-intro-story { padding: 36px 40px; }
  .judge-intro-story h1 { margin-bottom: 22px; }
  .judge-intro-lead { font-size: 16px; line-height: 1.65; }
  .judge-access { padding: 28px 40px 32px; background: #f0f4eb; border-top: 1px solid var(--line); }
  .judge-access > p:not(.eyebrow) { margin-top: 12px; }
  .judge-access-details { display: grid; grid-template-columns: 1fr 1fr; gap: 24px; margin: 24px 0 0; }
  .judge-access-details dt { font-weight: 650; color: var(--ink); }
  .judge-access-details dd { margin: 5px 0 0; color: var(--muted); font-size: 13px; }
  .judge-waitlist { padding: 28px 40px; border-top: 1px solid var(--line); }
  .waitlist-page { width: calc(100% - 40px); max-width: 560px; margin: 70px auto; padding: 32px; }
  .waitlist-copy { color: var(--muted); font-size: 13px; margin: 10px 0 18px; }
  .waitlist-form .field-hint { margin-top: 12px; }
  .waitlist-back { display: inline-block; margin-top: 24px; font-size: 13px; }
  .auth-centered { max-width: 470px; margin: 70px auto; }
  .auth-card > .card-body { padding: 0; }
  .auth-card h2 { font: 400 32px/1.2 Georgia, serif; letter-spacing: -.8px; }
  .auth-story .hero-title { font-size: clamp(36px, 4vw, 48px); }
  .created-card { max-width: 660px; margin: 36px auto; text-align: center; }
  .created-card .card-body { padding: 44px; }
  .created-card h2 { font: 400 30px/1.3 Georgia, serif; }
  .created-card .page-actions { justify-content: center; margin-top: 26px; }
  .public-header { max-width: 1250px; margin: auto; padding: 28px 40px; display: flex; align-items: center; justify-content: space-between; gap: 20px; border-bottom: 1px solid var(--line); }
  .public-header .brand { color: var(--ink); }
  .public-header .brand-mark { color: #64864e; }
  .auth-layout { max-width: 1080px; margin: 70px auto; padding: 0 40px; display: grid; grid-template-columns: 1fr 1fr; gap: 80px; align-items: center; }
  .auth-story h2 { font: 400 42px/1.15 Georgia, serif; letter-spacing: -1.2px; max-width: 390px; }
  .auth-story p { color: var(--muted); margin-top: 22px; font-size: 14px; max-width: 360px; }
  .auth-card { border: 1px solid var(--line); border-radius: 20px; background: white; padding: 36px; box-shadow: 0 12px 40px #34482905; }
  .auth-card h1 { font-size: 32px; margin-bottom: 16px; }
  .auth-card > p { color: var(--muted); font-size: 13px; margin-bottom: 24px; }
  .auth-card form { display: grid; gap: 16px; }
  .auth-card form label { margin-bottom: -9px; }
  .auth-card .button { width: 100%; margin-top: 18px; }
  .hero { max-width: 1250px; margin: auto; padding: 80px 40px; display: grid; grid-template-columns: 1.1fr 1fr; gap: 70px; align-items: center; }
  .hero-title { font-size: clamp(42px, 5vw, 68px); letter-spacing: -2.4px; line-height: 1.08; max-width: 560px; }
  .hero-copy { font-size: 15px; line-height: 1.8; color: var(--muted); max-width: 440px; margin: 24px 0 30px; }
  .feature-list { list-style: none; padding: 0; display: grid; gap: 12px; color: #677960; font-size: 12px; margin-top: 34px; }
  .feature-list li::before { content: '✓'; margin-right: 9px; color: #6f8b54; }
  .hero-visual { border-radius: 24px; background: #e8eddf; border: 1px solid #d7e0cb; padding: 40px 30px; position: relative; }
  .flow-node { border: 1px solid #cdd8c0; border-radius: 12px; background: #f9fbf5; padding: 22px; color: #45613c; box-shadow: 0 6px 14px #455c3310; }
  .flow-node { display: flex; align-items: center; gap: 16px; }
  .flow-node p { font-size: 12px; color: #79836e; margin-top: 6px; }
  .flow-line { width: 1px; height: 28px; margin: auto; background: #a9bb96; }
  /* Keep the working app dense; public landing and sign-in retain their spacing. */
  .app-shell .page-content { padding: 20px 24px 40px; }
  .app-shell .page-header { align-items: center; gap: 16px; margin-bottom: 18px; }
  .app-shell .page-header .eyebrow { display: none; }
  .app-shell h1 { font-size: 30px; letter-spacing: -.8px; }
  .app-shell .page-subtitle { margin-top: 5px; line-height: 1.45; max-width: 780px; }
  .app-shell .page-actions, .app-shell .button-row { gap: 8px; }
  .app-shell button, .app-shell .button { min-height: 38px; padding: 8px 12px; }
  .app-shell .small { min-height: 32px; padding: 6px 10px; }
  .app-shell input:not([type=hidden]):not([type=checkbox]):not([type=radio]),
  .app-shell select { min-height: 38px; padding: 8px 10px; }
  .app-shell textarea { padding: 9px 10px; }
  .app-shell .card-header { padding: 14px 16px; gap: 12px; }
  .app-shell .card-body { padding: 16px; }
  .app-shell .card-body > * + * { margin-top: 12px; }
  .app-shell .card-body > input[type=hidden] + * { margin-top: 0; }
  .app-shell .section-heading { margin: 20px 0 10px; gap: 12px; }
  .app-shell .stat-grid { gap: 12px; margin-bottom: 18px; }
  .app-shell .stat-card { padding: 14px 16px; }
  .app-shell .stat-value { font-size: 27px; margin-top: 4px; line-height: 1.2; }
  .app-shell .stat-note { margin-top: 5px; }
  .app-shell .agent-grid { gap: 14px; }
  .app-shell .agent-card { padding: 18px; gap: 12px; }
  .app-shell .agent-card > .card-body { padding: 0; }
  .app-shell .card-footer { padding-top: 12px; }
  .app-shell .form-grid { gap: 16px; }
  .app-shell .form-actions { padding-top: 16px; margin-top: 16px; gap: 12px; }
  .app-shell .field { gap: 5px; }
  .app-shell .notice { padding: 10px 12px; margin-bottom: 14px; }
  .app-shell .detail-grid, .app-shell .split-layout { gap: 18px; }
  .app-shell .main-column, .app-shell .side-column { gap: 16px; }
  .app-shell .guide-card { padding: 18px; }
  .app-shell .connection-card { padding: 18px; gap: 12px; }
  .app-shell nav.section-anchor { margin-bottom: 18px; gap: 18px; padding-bottom: 8px; }
  .app-shell .control-diagnostics > summary { padding: 14px 16px; }
  .app-shell .controls-heading { margin-top: 24px; padding-top: 20px; }
  .app-shell .workspace-footer { margin-top: 24px; padding-top: 16px; }
  .app-shell th, .app-shell td { padding: 10px 12px; }
}
@layer responsive {
  @media (max-width: 1180px) {
    .app-shell { grid-template-columns: 184px minmax(0, 1fr); }
    .topbar { padding-inline: 20px; }
    .app-shell .page-content { padding: 20px 20px 36px; }
    .page-header { align-items: flex-start; flex-wrap: wrap; }
    .detail-grid { grid-template-columns: minmax(0, 1fr); }
    .side-column { grid-template-columns: repeat(2, minmax(0, 1fr)); align-items: start; }
    .split-layout { grid-template-columns: minmax(0, 1fr) 235px; gap: 18px; }
    .stat-card { padding: 18px; }
    .stat-grid:has(> :nth-child(4)) { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  }
  @media (max-width: 800px) {
    .app-shell { display: block; }
    .sidebar { position: static; height: auto; padding: 10px 16px 0; }
    .sidebar .brand { gap: 7px; padding: 0 4px; }
    .sidebar .brand-name { font-size: 20px; }
    .sidebar .brand-mark, .sidebar .brand-mark svg { width: 20px; height: 24px; }
    .sidebar .brand-mark { flex-basis: 20px; }
    .sidebar .brand-tagline { display: none; }
    .nav-list { margin-top: 7px; display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 4px; }
    .nav-link { justify-content: center; gap: 6px; min-height: 44px; padding: 8px 6px; font-size: 12px; line-height: 1.25; border-radius: 6px 6px 0 0; }
    .nav-icon { flex-shrink: 0; }
    .nav-link.active, .nav-link[aria-current=page] { box-shadow: inset 0 -3px #bed0a4; }
    .sidebar-account { display: flex; align-items: center; justify-content: space-between; gap: 16px; margin-top: 8px; padding: 10px 4px; }
    .sidebar-account .account-identity { flex: 1; overflow: hidden; }
    .sidebar-account form { margin: 0; flex-shrink: 0; }
    .topbar { min-height: 34px; padding: 7px 20px; }
    .app-shell .page-content { padding: 16px 20px 32px; }
    .app-shell .page-header { gap: 10px; margin-bottom: 14px; }
    .app-shell h1 { font-size: 28px; }
    .app-shell button, .app-shell .button,
    .app-shell input:not([type=hidden]):not([type=checkbox]):not([type=radio]),
    .app-shell select { min-height: 44px; }
    .split-layout { grid-template-columns: minmax(0, 1fr); }
    .guide-card { order: 2; }
    .auth-layout { gap: 32px; padding: 0 24px; margin: 40px auto; }
    .auth-story h2 { font-size: 32px; }
    .auth-card { padding: 26px; }
    .hero { padding: 44px 28px; gap: 36px; }
    .hero-visual { padding: 25px 22px; }
  }
  @media (max-width: 560px) {
    .sidebar { padding-inline: 10px; }
    .nav-list { gap: 2px; }
    .nav-link { font-size: 11px; padding-inline: 3px; }
    .nav-icon { display: none; }
    h1 { font-size: 32px; letter-spacing: -.9px; }
    .app-shell .page-content { padding: 14px 14px 30px; }
    .topbar { padding: 7px 14px; gap: 8px; }
    .breadcrumb { font-size: 10px; gap: 7px; overflow-wrap: anywhere; }
    .environment-badge { font-size: 9px; padding: 5px 7px; }
    .app-shell .page-header { gap: 10px; margin-bottom: 14px; }
    .page-actions { width: 100%; }
    .page-actions .button { flex: 1; }
    .stat-grid { grid-template-columns: 1fr; gap: 10px; }
    .stat-grid:has(> :nth-child(4)) { grid-template-columns: 1fr; }
    .stat-card { padding: 15px 18px; display: grid; grid-template-columns: 1fr auto; align-items: center; }
    .stat-value { margin: 0; font-size: 25px; grid-column: 2; grid-row: 1 / span 2; }
    .stat-note { margin-top: 3px; grid-column: 1; }
    .card-header, .card-body, .composer { padding: 19px; }
    .app-shell .card-header, .app-shell .card-body, .app-shell .composer { padding: 14px; }
    .card-header { gap: 10px; }
    .side-column, .capability-grid, .connection-grid { grid-template-columns: minmax(0, 1fr); }
    .limit-grid { gap: 12px; }
    .limit-grid input { min-width: 0; }
    .inline-form { align-items: stretch; }
    .inline-form .field { flex-basis: 100%; }
    .inline-form > button { width: 100%; }
    nav.section-anchor { gap: 20px; }
    .conversation { padding: 18px; }
    .message { max-width: 95%; }
    .public-header { padding: 20px; }
    .judge-intro { margin: 24px 20px 40px; }
    .judge-intro-story, .judge-access { padding: 26px; }
    .judge-waitlist { padding: 24px; }
    .waitlist-page { margin: 32px auto; padding: 26px; }
    .judge-access-details { grid-template-columns: 1fr; gap: 18px; }
    .public-header .brand-tagline { display: none; }
    .auth-layout { display: flex; flex-direction: column; align-items: stretch; gap: 26px; margin: 30px auto; padding: 0 20px; }
    .auth-story h2 { font-size: 30px; }
    .auth-story p { margin-top: 12px; }
    .auth-card { padding: 26px; }
    .auth-centered { margin: 32px 20px; }
    .created-card .card-body { padding: 26px 20px; }
    .workspace-footer { flex-wrap: wrap; }
    .hero { grid-template-columns: minmax(0, 1fr); padding: 38px 22px; gap: 34px; }
    .hero-title { font-size: 46px; letter-spacing: -1.5px; }
    .hero-copy { margin: 20px 0 24px; }
    .hero-visual { padding: 24px; }
  }
  @media (prefers-reduced-motion: reduce) { *, *::before, *::after { transition: none !important; scroll-behavior: auto !important; } }
}
"""

CSS += """
.request-nav-count{margin-left:auto;min-width:21px;padding:1px 6px;border-radius:12px;background:#dce9c3;color:#203e30;font:600 11px/18px system-ui;text-align:center}
.request-nav-count[hidden]{display:none}
.request-attention{border:1px solid var(--line);background:var(--surface,#fff);border-radius:10px;margin:0 0 20px;overflow:hidden}
.request-attention-heading{display:flex;align-items:center;justify-content:space-between;gap:12px;padding:10px 14px;background:var(--canvas);font-size:13px}
.request-attention-heading a{font-size:12px;color:var(--forest,#245442)}
.request-attention ul{list-style:none;margin:0;padding:0}.request-attention li+li{border-top:1px solid var(--line)}
.request-attention li>a{display:flex;justify-content:space-between;align-items:center;gap:12px;padding:10px 14px;text-decoration:none;color:inherit}
.request-attention li>a:hover{background:var(--canvas)}.request-attention strong{font-size:13px}.request-attention small{display:block;color:var(--muted);font-size:11px;margin-top:3px}
"""
