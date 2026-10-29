/* Read-only audit tables use native AG Studio grids. No model or action dispatch. */
(() => {
  'use strict';
  const money = new Intl.NumberFormat('en-US', {style: 'currency', currency: 'USD', minimumFractionDigits: 2, maximumFractionDigits: 6});
  const dateTime = new Intl.DateTimeFormat('en-US', {month: 'short', day: 'numeric', year: 'numeric', hour: 'numeric', minute: '2-digit', timeZone: 'America/New_York', timeZoneName: 'short'});
  const scope = new URLSearchParams(location.search);
  const text = (id, name, extra = {}) => ({id, name, format: 'textFormat', ...extra});
  const number = (id, name, currency = false) => ({id, name, format: currency ? 'currencyFormat' : 'integerFormat',
    ...(currency ? {createValueFormatter: () => value => Number.isFinite(value) ? money.format(value) : '—'} : {})});
  const date = (id, name) => ({id, name, format: 'dateTimeFormat', accessor: row => row[id] ? new Date(row[id]) : null,
    createValueFormatter: () => value => value instanceof Date && !Number.isNaN(value.getTime()) ? dateTime.format(value) : '—'});
  const sourceField = () => text('evidence_url', 'Source', {context: {evidenceLink: true}});
  const display = value => Array.isArray(value) ? value.map(item => typeof item === 'string' ? item : item.label || item.component).join(', ') : value || '';
  const label = value => String(value || '').replace(/_/g, ' ');
  const dollars = value => Number.isFinite(value) ? value / 100 : null;

  function sourceLink(raw, title = 'View source') {
    let href = null;
    if (typeof raw === 'string' && /^\/(?!\/)/.test(raw)) {
      try {
        const url = new URL(raw, location.origin);
        if (url.origin === location.origin && /^\/(?:audit(?:\/|$)|instances\/|agent-workspaces\/|commerce\/orders\/|requests(?:\/|$))/.test(url.pathname)) {
          if (/^\/audit(?:\/|$)/.test(url.pathname)) {
            for (const key of ['instance_id', 'date_from', 'date_to', 'status_purchases', 'status_deliverables']) {
              if (scope.get(key)) url.searchParams.set(key, scope.get(key));
            }
            const view = scope.get('view');
            if (['purchases', 'deliverables'].includes(view) && scope.get('status')) url.searchParams.set(`status_${view}`, scope.get('status'));
          }
          href = url.pathname + url.search + url.hash;
        }
      } catch (_) { /* An invalid source stays non-navigable. */ }
    }
    const link = document.createElement(href ? 'a' : 'span');
    link.textContent = href ? title : raw ? 'Source unavailable' : '—';
    if (href) { link.href = href; link.className = 'audit-studio-source'; }
    return link;
  }

  function tableDefinition(kind, rows) {
    if (!Array.isArray(rows)) throw new Error('Invalid audit records');
    if (kind === 'costs') return {
      id: 'records', name: 'Resource ledger',
      description: 'Recorded funding and resource activity. Funding is not an expense; reservations are not settled charges.',
      fields: [date('created_at', 'Date'), text('agent_name', 'Agent'), text('component_label', 'Resource'), text('category', 'Entry'), number('amount_usd', 'Amount (USD)', true), text('charge_kind', 'Accounting'), text('status', 'Status'), text('coverage_note', 'Cost coverage'), sourceField()],
      data: rows.map(row => ({...row, component_label: row.component_label || label(row.component || row.category), category: label(row.category), charge_kind: label(row.charge_kind), status: label(row.status)})),
    };
    if (kind === 'cost_jobs') return {
      id: 'records', name: 'Cost by job',
      description: 'Recorded usage and estimates by source job. Funding and merchant payments are separate. Unallocated setup remains at agent level.',
      fields: [date('started_at', 'Started'), text('job_name', 'Job / allocation'), text('job_reference', 'Job reference'), text('status', 'Status'), text('agent_name', 'Agent'), number('settled_usd', 'Recorded usage (USD)', true), number('estimated_usd', 'Estimated (USD)', true), number('total_usd', 'Recorded + estimated (USD)', true), number('held_usd', 'Reserved (USD)', true), text('components', 'Resources'), text('coverage', 'Cost coverage'), sourceField()],
      data: rows.map(row => ({...row, components: display(row.components), coverage: display(row.coverage)})),
    };
    if (kind === 'actions') return {
      id: 'records', name: 'Agent actions', description: 'Recorded run activity, tool use, output saves, checks and owner decisions. Source links open the original evidence.',
      fields: [date('occurred_at', 'Date'), text('agent_name', 'Agent'), text('action', 'Action'), text('outcome', 'Outcome'), text('reason', 'Details'), sourceField(), text('purchase_url', 'Purchase', {context: {evidenceLink: true, linkText: 'View purchase'}})],
      data: rows,
    };
    if (kind === 'campaign') return {
      id: 'records', name: 'Campaign performance', description: 'Reported campaign-day metrics from scenario data. Monetary fields are USD.',
      fields: [number('day', 'Day'), date('reported_at', 'Reported'), number('spend_usd', 'Ad spend', true), number('impressions', 'Impressions'), number('clicks', 'Clicks'), number('attributed_installs', 'Installs'), number('cpc_usd', 'Cost / click', true), number('cpi_usd', 'Cost / install', true), sourceField()],
      data: rows.map(row => ({day: row.day, reported_at: row.reported_at, spend_usd: dollars(row.spend_minor), impressions: row.impressions, clicks: row.clicks, attributed_installs: row.attributed_installs, cpc_usd: dollars(row.cpc_minor), cpi_usd: dollars(row.cpi_minor), evidence_url: row.run_id ? `/audit/jobs/${encodeURIComponent(row.run_id)}` : null})),
    };
    throw new Error('Unsupported audit table');
  }

  document.querySelectorAll('.audit-studio-table').forEach((target, index) => {
    const fallback = document.getElementById(target.dataset.fallback);
    let failed = false;
    const showFallback = () => {
      failed = true;
      target.hidden = true;
      target.dataset.studioState = 'fallback';
      if (fallback) fallback.hidden = false;
    };
    try {
      const studio = window.agStudio;
      if (!studio?.createStudio) { showFallback(); return; }
      const records = tableDefinition(target.dataset.kind, JSON.parse(document.getElementById(target.dataset.source).textContent));
      if (target.dataset.licenseKey) studio.AgStudioLicenseManager.setLicenseKey(target.dataset.licenseKey);
      target.hidden = false;
      target.dataset.studioState = 'loading';
      target.replaceChildren();
      studio.createStudio(target, {
        studioId: `habitat-${target.id || `audit-table-${index}`}`, mode: 'view', enableFilterEditingInViewMode: true,
        data: {sources: [records]},
        theme: studio.studioTheme.withParams({fontFamily: 'Arial, sans-serif', fontSize: 12, textColor: '#254d3c', backgroundColor: '#ffffff', borderColor: '#dce5df', studioMinWidth: 240, studioMinHeight: 460, studioCanvasMinWidth: 240, studioPanelWidth: 240, gridHeaderBackgroundColor: '#edf3ec', gridRowHeight: 37}),
        panels: {view: {right: ['filters']}, edit: {right: ['filters']}},
        initialState: {pages: [{id: 'audit', widgets: {records: {type: 'grid',
          sort: [{field: {id: `records.${target.dataset.kind === 'actions' ? 'occurred_at' : target.dataset.kind === 'campaign' ? 'day' : target.dataset.kind === 'cost_jobs' ? 'started_at' : 'created_at'}`}, direction: target.dataset.kind === 'campaign' ? 'asc' : 'desc'}],
          format: {title: {text: records.name, enabled: false}, subtitle: {enabled: false}, style: {columnWidth: 155, columnAutoSize: false, headerRow: {wrapText: true}}},
          dataMapping: {cols: records.fields.map(field => ({id: `records.${field.id}`}))}}},
          widgetLayout: {records: {xTrack: 0, yTrack: 0, xSpan: 24, ySpan: 26}},
          layout: {minWidth: 240, columns: 24, rowHeight: 16, pagePadding: 0, widgetPadding: 0, backgroundColor: '#ffffff', widgetBackgroundColor: '#ffffff', widgetBorderEnabled: false}}],
          selectedPageId: 'audit', panels: {filters: {collapsed: true}}},
        widgets: () => studio.createWidgets({overrides: [{id: 'grid', options: {createCellRenderer: window.HabitatStudioGrid.createCellRenderer(field => field.context?.evidenceLink ? params => sourceLink(params.value, field.context.linkText) : undefined)}}]}),
        onRenderStateChanged: event => {
          if (!failed && event.renderState === 'rendered') {
            if (fallback) fallback.hidden = true;
            target.dataset.studioState = 'ready';
          }
        },
        onErrorRaised: event => { if (event.fatal) showFallback(); },
      });
    } catch (_) { showFallback(); }
  });
})();
