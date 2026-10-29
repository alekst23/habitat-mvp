/* AG Studio is a presentation layer. Owner decisions remain on their existing routes. */
(() => {
  'use strict';
  const root = document.getElementById('operations');
  if (!root) return;
  const el = id => document.getElementById(id);
  const form = el('operations-filters');
  const timezone = 'America/New_York';
  const csrf = root.dataset.csrf;
  const money = new Intl.NumberFormat('en-US', {style: 'currency', currency: 'USD', minimumFractionDigits: 2, maximumFractionDigits: 6});
  const dateTime = new Intl.DateTimeFormat('en-US', {month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit', timeZone: timezone, timeZoneName: 'short'});
  const labels = {
    service_funding: 'Service funding', inference: 'Model / tool meter', compute_estimate: 'Compute estimate',
    merchant_purchase: 'Merchant payment', purchase_reservation: 'Purchase reservation',
    fixture: 'Scenario data', paypal_sandbox: 'PayPal Sandbox', provider_reported: 'Provider-reported usage',
    runtime_estimate: 'Runtime estimate', application_record: 'Application record', mixed: 'Mixed sources',
  };
  const label = value => labels[value] || String(value || '').replace(/_/g, ' ');
  const usd = value => Number.isFinite(value) ? money.format(value) : '—';
  let api = null;
  let snapshot = null;
  let agentNames = new Map();
  let stateVersion = null;
  let initialState = null;
  let stateLoadError = '';
  let loading = false;
  let preset = false;
  let saving = false;
  let ownerInteraction = false;
  let refreshSequence = 0;
  let appliedFilterQuery = null;
  let editing = false;
  let desktopState = null;
  const compactScreen = window.matchMedia('(max-width: 650px)');

  function safeHref(raw) {
    if (typeof raw !== 'string' || !/^\/(?!\/)/.test(raw)) return null;
    try {
      const url = new URL(raw, location.origin);
      if (url.origin !== location.origin || !/^\/(audit(?:\/|\?|$)|requests(?:\/|\?|$)|instances\/|agent-workspaces\/|commerce\/orders\/|workspace(?:\?|$))/.test(raw)) return null;
      if (url.pathname.startsWith('/audit') && snapshot?.filters) {
        for (const key of ['instance_id', 'date_from', 'date_to', 'status_purchases', 'status_deliverables']) {
          const value = snapshot.filters[key] || (key.startsWith('status_') ? form.elements[key]?.value : '');
          if (value) url.searchParams.set(key, value);
        }
      }
      return url.pathname + url.search + url.hash;
    } catch (_) { return null; }
  }

  function evidenceLink(raw, text = 'Open source →') {
    const href = safeHref(raw);
    const node = document.createElement(href ? 'a' : 'span');
    node.textContent = href ? text : 'Source unavailable';
    if (href) { node.href = href; node.className = 'operations-evidence-link'; }
    return node;
  }

  async function request(url, options = {}) {
    const response = await fetch(url, {credentials: 'same-origin', cache: 'no-store', ...options});
    if (response.redirected || response.status === 401) throw new Error('Your session has ended. Sign in again to refresh this view.');
    const body = await response.json().catch(() => null);
    if (!response.ok) {
      const error = new Error(response.status === 409 ? 'This layout was changed in another tab. Reload the page before saving so that its changes are preserved.' :
        body?.message || body?.detail || 'The request could not be completed. Try again.');
      error.status = response.status;
      throw error;
    }
    if (!body || typeof body !== 'object') throw new Error('The server returned an unreadable response. Try refreshing.');
    return body;
  }

  const textField = (id, name, extra = {}) => ({id, name, format: 'textFormat', ...extra});
  const numericField = (id, name, currency = true) => ({id, name, format: currency ? 'currencyFormat' : 'integerFormat',
    ...(currency ? {createValueFormatter: () => value => usd(value)} : {})});
  const dateField = (id, name) => ({id, name, format: 'dateTimeFormat', accessor: row => row[id] ? new Date(row[id]) : null,
    createValueFormatter: () => value => value instanceof Date && !Number.isNaN(value.getTime()) ? dateTime.format(value) : '—'});
  const evidenceField = () => textField('evidence_url', 'Source', {context: {evidenceLink: true}, description: 'Same-origin URL for the underlying owner record; follow it to review evidence or make an owner decision.'});
  const definitions = [
    {id: 'costs', name: 'Cost ledger', description: 'Recorded monetary entries in the selected period. Funding is not spending. Reservations are not settled expenses. Provenance identifies scenario, Sandbox, measured and estimated entries.',
      fields: [textField('id', 'Entry ID', {hide: true}), dateField('occurred_at', 'Recorded'), textField('agent_id', 'Agent ID', {hide: true}), textField('agent_name', 'Agent'), textField('job_id', 'Source job ID', {hide: true}), textField('category', 'Category'), textField('component_label', 'Resource'), textField('charge_kind', 'Accounting'), textField('coverage_note', 'Cost coverage'), numericField('amount_usd', 'Amount (USD)'), textField('status', 'Status'), textField('provenance', 'Source type'), textField('model', 'Model'), numericField('input_tokens', 'Input tokens', false), numericField('output_tokens', 'Output tokens', false), evidenceField()]},
    {id: 'jobs', name: 'Jobs and outcomes', description: 'Work scheduled in the selected period, its current status, review state, recorded usage and source evidence. An accepted output is an owner review decision, not proof of factual correctness.',
      fields: [textField('id', 'Job ID', {hide: true}), textField('agent_id', 'Agent ID', {hide: true}), textField('agent_name', 'Agent'), dateField('scheduled_at', 'Scheduled'), textField('status', 'Status'), textField('blocked_reason', 'Waiting reason'), textField('output_name', 'Expected output'), textField('review_status', 'Owner review'), numericField('settled_usd', 'Recorded usage (USD)'), numericField('estimated_usd', 'Estimated (USD)'), numericField('total_cost_usd', 'Recorded + estimated (USD)'), textField('components', 'Resources'), textField('coverage', 'Cost coverage'), numericField('inference_usd', 'Model + tool meter (USD)'), numericField('compute_estimate_usd', 'Compute estimate (USD)'), textField('provenance', 'Source type'), evidenceField()]},
    {id: 'attention', name: 'Needs owner attention', description: 'Current pending owner requests and output reviews for selected agents, regardless of the period filter. These are links to existing owner workflows, not approvals.',
      fields: [textField('id', 'Request ID', {hide: true}), textField('agent_id', 'Agent ID', {hide: true}), textField('agent_name', 'Agent'), textField('kind', 'Request kind'), textField('title', 'Request'), textField('status', 'Status'), dateField('created_at', 'Created'), evidenceField()]},
    {id: 'agents', name: 'Agent outcomes', description: 'One row per selected agent with period costs and outcomes. Recorded resource usage, estimates and merchant payments are separate categories. Funding and reservations are excluded from these amounts.',
      fields: [textField('agent_id', 'Agent ID', {hide: true}), textField('agent_name', 'Agent'), numericField('settled_usd', 'Recorded usage (USD)'), numericField('estimated_usd', 'Estimated (USD)'), numericField('inference_usd', 'Model + tool meter (USD)'), numericField('compute_estimate_usd', 'Compute estimate (USD)'), numericField('purchase_usd', 'Merchant payments (USD)'), numericField('job_count', 'Jobs', false), numericField('accepted_count', 'Accepted outputs', false), numericField('pending_count', 'Awaiting owner', false), evidenceField()]},
  ];

  function agentDisplayNames(agents) {
    const groups = new Map();
    for (const agent of agents) {
      const name = String(agent.name || 'Unnamed agent');
      if (!groups.has(name)) groups.set(name, []);
      groups.get(name).push(agent);
    }
    const result = new Map();
    // Reserve unique names first, including names that resemble an ID suffix.
    const used = new Set([...groups].filter(([, group]) => group.length === 1).map(([name]) => name));
    for (const [name, group] of [...groups].sort(([a], [b]) => a < b ? -1 : a > b ? 1 : 0)) {
      for (const agent of [...group].sort((a, b) => String(a.id).localeCompare(String(b.id)))) {
        let display = name;
        if (group.length > 1) {
          const id = String(agent.id);
          let length = Math.min(6, id.length);
          display = `${name} · ${id.slice(-length)}`;
          while (used.has(display) && length < id.length) display = `${name} · ${id.slice(-++length)}`;
          let collision = 2;
          while (used.has(display)) display = `${name} · ${id} (${collision++})`;
        }
        used.add(display);
        result.set(agent.id, display);
      }
    }
    return result;
  }

  function sourceData() {
    const qualifying = new Set(snapshot.agent_summary.filter(row =>
      row.accepted_count === 0 && ((row.inference_usd || 0) + (row.compute_estimate_usd || 0) + (row.purchase_usd || 0) > 0)).map(row => row.agent_id));
    const data = {costs: snapshot.costs, jobs: snapshot.jobs, attention: snapshot.attention, agents: snapshot.agent_summary};
    return {relationships: ['costs', 'jobs', 'attention'].map(table => ({id: `agent-${table}`, type: 'one-to-many',
      source: {tableId: 'agents', fieldId: 'agent_id'}, target: {tableId: table, fieldId: 'agent_id'}})),
      description: 'Owner operations. Agents is the unique agent dimension; jobs, costs and attention join to it by agent_id. Period filters constrain jobs and costs. Attention is current, including older unresolved requests. Never sum service funding with expenses or reservations with settled charges.',
      sources: definitions.map(definition => ({...definition, data: data[definition.id]
      .filter(row => !preset || qualifying.has(row.agent_id))
      .map(row => ({...row, agent_name: agentNames.get(row.agent_id) || row.agent_name,
        ...('category' in row ? {category: label(row.category)} : {}),
        ...('provenance' in row ? {provenance: label(row.provenance)} : {}),
        ...('status' in row ? {status: label(row.status)} : {}),
        ...('review_status' in row ? {review_status: ['completed', 'draft'].includes(row.review_status) ? `${label(row.review_status)} · not reviewed` : label(row.review_status)} : {})}))}))};
  }

  const fields = (source, ids) => ids.map(id => ({id: `${source}.${id}`}));
  const format = (title, subtitle) => ({title: {text: title, enabled: true}, subtitle: {text: subtitle, enabled: true}, crossFilter: 'filter',
    style: {columnWidth: 155, columnAutoSize: false, headerRow: {wrapText: true}}});

  function starterState() {
    const state = {pages: [{id: 'operations', widgets: {
      attention: {type: 'habitat-attention', format: format('Needs your attention', 'Current requests · includes earlier unresolved work'),
        dataMapping: {items: fields('attention', ['id', 'agent_name', 'kind', 'title', 'status', 'evidence_url'])}},
      spending: {type: 'column-chart-grouped', format: {title: {text: 'Spending by agent', enabled: true}, subtitle: {text: 'Select an agent bar to filter the connected records', enabled: true}, crossFilter: 'filter',
        style: {theme: {common: {legend: {enabled: true, position: 'bottom'}}}, custom: {valueAxis: {title: {enabled: true, text: 'USD'}}}}},
        dataMapping: {categoryKey: fields('agents', ['agent_name']), valueKey: ['settled_usd', 'estimated_usd', 'purchase_usd'].map(id => ({id: `agents.${id}`, aggregation: 'sum'}))}},
      jobs: {type: 'grid', format: format('Jobs & outcomes', 'Open the source job to see its controls, evidence and output'),
        dataMapping: {cols: fields('jobs', ['agent_name', 'output_name', 'status', 'review_status', 'settled_usd', 'estimated_usd', 'components', 'evidence_url'])}},
      ledger: {type: 'grid', format: format('Follow every resource entry', 'Funding and reservations are shown separately from expenses'),
        dataMapping: {cols: fields('costs', ['occurred_at', 'agent_name', 'component_label', 'amount_usd', 'charge_kind', 'status', 'evidence_url'])}},
    }, widgetLayout: {
      attention: {xTrack: 0, yTrack: 0, xSpan: 8, ySpan: 19},
      spending: {xTrack: 8, yTrack: 0, xSpan: 16, ySpan: 19},
      jobs: {xTrack: 0, yTrack: 19, xSpan: 24, ySpan: 23},
      ledger: {xTrack: 0, yTrack: 42, xSpan: 24, ySpan: 24},
    }, layout: {minWidth: 280, columns: 24, rowHeight: 16, pagePadding: 10, widgetPadding: 10,
      backgroundColor: '#f7f9f5', widgetBackgroundColor: '#ffffff', widgetBorderEnabled: true, widgetBorderRadius: 9,
      widgetBorderColor: '#dce5df', widgetBorderWidth: 1}}], selectedPageId: 'operations',
      panels: {edit: {collapsed: true}, data: {collapsed: true}, filters: {collapsed: true}}};
    return state;
  }

  function responsiveState(state) {
    if (!compactScreen.matches) return state;
    const result = JSON.parse(JSON.stringify(state));
    for (const page of result.pages || []) {
      let row = 0;
      for (const [id, position] of Object.entries(page.widgetLayout || {}).sort((a, b) => a[1].yTrack - b[1].yTrack || a[1].xTrack - b[1].xTrack)) {
        page.widgetLayout[id] = {...position, xTrack: 0, xSpan: 24, yTrack: row};
        row += position.ySpan;
      }
      page.layout = {...page.layout, columns: 24, minWidth: 280};
    }
    return result;
  }

  function preserveDesktopLayout(state) {
    if (!desktopState) return state;
    const result = JSON.parse(JSON.stringify(state));
    for (const page of result.pages || []) {
      const reference = desktopState.pages?.find(item => item.id === page.id);
      if (!reference) continue;
      let nextRow = Math.max(0, ...Object.values(reference.widgetLayout || {}).map(position => position.yTrack + position.ySpan));
      const positions = {};
      for (const id of Object.keys(page.widgets || {})) {
        if (reference.widgetLayout?.[id]) positions[id] = {...reference.widgetLayout[id]};
        else {
          const position = page.widgetLayout?.[id] || {xTrack: 0, xSpan: 24, ySpan: 20};
          positions[id] = {...position, xTrack: 0, yTrack: nextRow, xSpan: 24};
          nextRow += position.ySpan;
        }
      }
      page.widgetLayout = positions;
      page.layout = {...page.layout, columns: reference.layout?.columns || 24, minWidth: reference.layout?.minWidth || 280};
    }
    return result;
  }

  function setEditing(value) {
    editing = value && !compactScreen.matches;
    api?.setProperty('mode', editing ? 'edit' : 'view');
    el('operations-edit').textContent = editing ? 'Done editing' : 'Edit layout';
    el('operations-edit').setAttribute('aria-pressed', String(editing));
    el('operations-edit').disabled = compactScreen.matches || !api;
    el('operations-edit').title = compactScreen.matches ? 'Open on a wider screen to arrange widgets. Mobile saves preserve the desktop arrangement.' : '';
    el('operations-save').textContent = compactScreen.matches ? 'Save view' : 'Save layout';
  }

  function clearChartSelection() {
    if (!api) return;
    const state = api.getState();
    if (!(state.pages || []).some(page => page.crossFilter)) return;
    api.setState({...state, pages: state.pages.map(page => {
      const {crossFilter, ...rest} = page;
      return rest;
    })});
  }

  class AttentionWidget {
    init(params) {
      this.element = document.createElement('div');
      this.element.className = 'operations-attention';
      this.generation = 0;
      return this.refresh(params);
    }
    getGui() { return this.element; }
    async refresh(params) {
      const generation = ++this.generation;
      const mapped = params.dataMapping.items || [];
      params.widgetApi.setDisplayState('loading');
      try {
        const {results} = await params.widgetApi.getData({fields: mapped});
        if (generation !== this.generation) return;
        const read = (row, id) => { const field = mapped.find(item => item.fieldId === `attention.${id}`); return field ? row[field.key] : ''; };
        this.element.replaceChildren();
        if (!results.rows.length) {
          const empty = document.createElement('p');
          empty.className = 'operations-empty';
          empty.textContent = 'Nothing needs your response in this view. Change the filters to explore other activity.';
          this.element.append(empty);
        }
        for (const row of results.rows) {
          const item = evidenceLink(read(row, 'evidence_url'), '');
          item.className = 'operations-attention-item';
          const kind = document.createElement('span');
          kind.className = 'operations-attention-kind';
          kind.textContent = label(read(row, 'kind')) || 'Owner review';
          const title = document.createElement('strong');
          title.textContent = read(row, 'title') || 'Review this request';
          const details = document.createElement('small');
          details.textContent = `${read(row, 'agent_name')} · ${read(row, 'status')}`;
          item.replaceChildren(kind, title, details);
          this.element.append(item);
        }
        params.widgetApi.setDisplayState('displayed');
      } catch (_) {
        if (generation !== this.generation) return;
        this.element.replaceChildren(evidenceLink('/requests', 'Open Requests to review current items →'));
        params.widgetApi.setDisplayState('displayed');
      }
    }
    destroy() { ++this.generation; }
  }

  function mountStudio() {
    if (!window.agStudio?.createStudio) throw new Error('The dashboard library could not load. Use Audit history below, or refresh the page.');
    const studio = window.agStudio;
    if (root.dataset.licenseKey) studio.AgStudioLicenseManager.setLicenseKey(root.dataset.licenseKey);
    desktopState = initialState || starterState();
    const props = {
      studioId: 'habitat-owner-operations', mode: 'view', data: sourceData(), initialState: responsiveState(desktopState),
      theme: studio.studioTheme.withParams({fontFamily: 'Arial, sans-serif', fontSize: 12, textColor: '#254d3c',
        backgroundColor: '#ffffff', borderColor: '#dce5df', studioMinWidth: 280, studioMinHeight: 500, studioCanvasMinWidth: 280,
        studioPanelWidth: 240, studioWidgetTitleFontSize: 15, studioWidgetTitleFontWeight: 600,
        studioWidgetTitleTextColor: '#254d3c', studioWidgetSubtitleTextColor: '#64736a', studioWidgetSubtitleFontSize: 11,
        gridHeaderBackgroundColor: '#edf3ec', gridRowHeight: 37, chartPaletteFills1Color: '#356249',
        chartPaletteFills2Color: '#9cba83', chartPaletteFills3Color: '#d7b27c', chartPaletteStrokes1Color: '#356249',
        chartPaletteStrokes2Color: '#9cba83', chartPaletteStrokes3Color: '#d7b27c'}),
      panels: {edit: {left: ['edit', 'data'], right: ['filters']}, view: {right: ['filters']}},
      widgets: defaults => studio.createWidgets({
        additionalTypes: [{id: 'habitat-attention', label: 'Needs owner attention', comp: AttentionWidget,
          dataMapping: {items: {type: 'fieldset', supportedRoles: ['category', 'temporal', 'numeric'], required: true}},
          formatShape: defaults.widgets.find(widget => widget.id === 'grid').formatShape,
          form: params => params.createDefaults({dataMappingItems: [{key: 'items', label: 'Request fields'}]}),
          defaultSize: {width: 350, height: 300}, minSize: {width: 200, height: 160}}],
        overrides: [{id: 'grid', options: {createCellRenderer: window.HabitatStudioGrid.createCellRenderer(field => field.context?.evidenceLink ? params => evidenceLink(params.value) : undefined)}}],
        menu: [{label: 'Habitat', widgetIds: ['habitat-attention']}, ...defaults.menu],
      }),
      onStateUpdated: () => {
        // The public event has no cause/source field. Only report edits after an
        // actual dashboard interaction, never after asynchronous schema hydration.
        if (!ownerInteraction) return;
        ownerInteraction = false;
        if (!saving) el('operations-layout-status').textContent = 'View changed. Save to keep it for your next visit.';
      },
    };
    el('operations-studio').replaceChildren();
    api = studio.createStudio(el('operations-studio'), props);
    setEditing(false);
    el('operations-save').disabled = stateVersion === null;
    el('operations-reset').disabled = stateVersion === null;
    el('operations-layout-status').textContent = stateLoadError || (initialState ? 'Your saved layout is restored.' : 'Starter layout · four connected views of your agents.');
  }

  function renderSummary() {
    const current = snapshot.current;
    const totals = snapshot.totals;
    el('metric-credit').textContent = usd(current.service_credit_usd);
    el('metric-held').textContent = usd(current.held_usd);
    el('metric-budget').textContent = usd(current.budget_remaining_usd);
    el('metric-inference').textContent = usd(snapshot.cost_summary ? snapshot.cost_summary.settled_micro_usd / 1000000 : totals.inference_usd);
    el('metric-compute').textContent = usd(snapshot.cost_summary ? snapshot.cost_summary.estimated_micro_usd / 1000000 : totals.compute_estimate_usd);
    el('metric-purchases').textContent = usd(totals.purchase_usd);
    el('metric-work').textContent = `${totals.job_count} / ${totals.accepted_count}`;
    const outputs = el('operations-outputs');
    outputs.replaceChildren();
    for (const output of (snapshot.outputs || []).slice(0, 4)) {
      const article = document.createElement('article');
      const title = evidenceLink(output.evidence_url, label(output.output_name));
      const context = document.createElement('p');
      context.className = 'field-hint';
      context.textContent = `${agentNames.get(output.agent_id) || output.agent_name} · ${label(output.status)} · ${dateTime.format(new Date(output.created_at))}`;
      article.append(title, context);
      outputs.append(article);
    }
    if (!outputs.children.length) {
      const empty = document.createElement('p');
      empty.className = 'muted';
      empty.textContent = 'No saved outputs in this period. Check Actions for progress or choose a wider date range.';
      outputs.append(empty);
    }
    const selected = el('operations-agent').value;
    const options = [new Option('All agents', '')];
    for (const agent of snapshot.agents) options.push(new Option(agentNames.get(agent.id), agent.id));
    el('operations-agent').replaceChildren(...options);
    el('operations-agent').value = selected;
    el('operations-period-label').textContent = el('operations-from').value || el('operations-to').value ?
      `${el('operations-from').value || 'Earliest record'} — ${el('operations-to').value || 'Today'}` : 'All recorded activity';
    const asOf = new Date(snapshot.as_of);
    el('operations-status').textContent = `Updated ${Number.isNaN(asOf.getTime()) ? 'just now' : dateTime.format(asOf)} · ${snapshot.agent_summary.length} agent${snapshot.agent_summary.length === 1 ? '' : 's'}`;
  }

  async function readState() {
    try {
      const saved = await request('/audit/studio/state');
      initialState = saved.state;
      stateVersion = saved.version;
      stateLoadError = '';
    } catch (error) {
      stateLoadError = `Your saved layout could not be loaded. Reload the page before saving. ${error.message}`;
      el('operations-layout-status').textContent = stateLoadError;
    }
  }

  async function refresh() {
    if (loading) return;
    loading = true;
    const sequence = ++refreshSequence;
    el('operations-refresh').disabled = true;
    form.querySelector('[type=submit]').disabled = true;
    el('operations-status').textContent = snapshot ? 'Refreshing… Your last successful snapshot remains visible.' : 'Loading your workspace…';
    const params = new URLSearchParams(new FormData(form));
    params.set('timezone', timezone);
    for (const control of form.elements) control.disabled = true;
    try {
      const data = await request(`/audit/studio/data?${params}`);
      if (sequence !== refreshSequence) return;
      if (!data.current || !data.totals || !['agents', 'costs', 'jobs', 'attention', 'agent_summary'].every(key => Array.isArray(data[key]))) {
        throw new Error('This dashboard snapshot is incomplete. The last successful view has been preserved.');
      }
      const filtersChanged = appliedFilterQuery !== null && appliedFilterQuery !== params.toString();
      snapshot = data;
      // The owner-wide list keeps labels stable when the active agent filter changes.
      agentNames = agentDisplayNames(snapshot.agents);
      renderSummary();
      el('operations-error').hidden = true;
      appliedFilterQuery = params.toString();
      const url = new URL(location.href);
      url.search = params.toString();
      history.replaceState(null, '', url);
      for (const link of document.querySelectorAll('[data-audit-view]')) {
        const view = link.dataset.auditView;
        const target = new URL(view === 'operations' ? '/audit/studio' : '/audit', location.origin);
        for (const key of ['instance_id', 'date_from', 'date_to', 'status_purchases', 'status_deliverables']) {
          if (params.get(key)) target.searchParams.set(key, params.get(key));
        }
        if (view !== 'operations') target.searchParams.set('view', view);
        if (params.get(`status_${view}`)) target.searchParams.set('status', params.get(`status_${view}`));
        link.href = target.pathname + target.search;
      }
      if (!api) {
        try { mountStudio(); }
        catch (error) {
          el('operations-studio').hidden = true;
          el('operations-fallback').hidden = false;
          throw error;
        }
      } else {
        api.setProperty('data', sourceData());
        if (filtersChanged) clearChartSelection();
      }

    } catch (error) {
      el('operations-error').textContent = error.message;
      el('operations-error').hidden = false;
      el('operations-status').textContent = snapshot ? 'Refresh failed. Showing the last successful snapshot; its values may be out of date.' : 'No dashboard data loaded.';
    } finally {
      loading = false;
      el('operations-refresh').disabled = false;
      for (const control of form.elements) control.disabled = false;
    }
  }

  async function saveLayout(reset = false) {
    if (!api || stateVersion === null || saving) return;
    saving = true;
    el('operations-save').disabled = true;
    el('operations-reset').disabled = true;
    try {
      const result = await request('/audit/studio/state', {method: 'PUT', headers: {'Content-Type': 'application/json', 'X-CSRF-Token': csrf},
        body: JSON.stringify({state: reset ? null : compactScreen.matches ? preserveDesktopLayout(api.getState()) : api.getState(), expected_version: stateVersion})});
      stateVersion = result.version;
      ownerInteraction = false;
      desktopState = reset ? starterState() : result.state;
      if (reset) {
        preset = false;
        el('operations-preset').setAttribute('aria-pressed', 'false');
        api.setProperty('data', sourceData());
        api.setState(responsiveState(desktopState));
      }
      el('operations-layout-status').textContent = reset ? 'Starter layout restored. Your saved custom layout was cleared.' :
        compactScreen.matches ? 'View saved. Your desktop widget arrangement is preserved.' : 'Layout saved to your workspace.';
    } catch (error) {
      el('operations-layout-status').textContent = error.message;
      if (error.status === 409) stateVersion = null;
    } finally {
      saving = false;
      el('operations-save').disabled = stateVersion === null;
      el('operations-reset').disabled = stateVersion === null;
    }
  }

  const query = new URLSearchParams(location.search);
  for (const name of ['date_from', 'date_to']) form.elements[name].value = query.get(name) || '';
  if (query.get('instance_id')) {
    if (![...el('operations-agent').options].some(option => option.value === query.get('instance_id')))
      el('operations-agent').add(new Option('Selected agent', query.get('instance_id')));
    el('operations-agent').value = query.get('instance_id');
  }
  form.addEventListener('submit', event => { event.preventDefault(); refresh(); });
  el('operations-refresh').addEventListener('click', refresh);
  el('operations-clear').addEventListener('click', () => {
    form.reset();
    for (const key of ['status_purchases', 'status_deliverables']) {
      if (form.elements[key]) form.elements[key].value = '';
    }
    el('operations-agent').value = '';
    el('operations-from').value = '';
    el('operations-to').value = '';
    refresh();
  });
  el('operations-save').addEventListener('click', () => saveLayout());
  el('operations-edit').addEventListener('click', () => setEditing(!editing));
  el('operations-reset').addEventListener('click', () => saveLayout(true));
  el('operations-preset').addEventListener('click', () => {
    if (!api || !snapshot) return;
    preset = !preset;
    el('operations-preset').setAttribute('aria-pressed', String(preset));
    api.setProperty('data', sourceData());
    clearChartSelection();
    el('operations-layout-status').textContent = preset ? 'Preset applied to dashboard widgets: costs with no accepted output. Summary cards still show all selected agents. This is a predefined rule, not an AI answer.' : 'Preset cleared. Dashboard widgets show all selected agents.';
  });
  el('operations-studio').addEventListener('pointerdown', () => { ownerInteraction = true; }, {passive: true});
  el('operations-studio').addEventListener('keydown', () => { ownerInteraction = true; });
  compactScreen.addEventListener('change', () => {
    if (!api) return;
    if (compactScreen.matches) {
      desktopState = api.getState();
      api.setState(responsiveState(desktopState));
    } else {
      desktopState = preserveDesktopLayout(api.getState());
      api.setState(desktopState);
    }
    setEditing(false);
  });
  // Preserve Studio while the browser caches this page for Back navigation.
  window.addEventListener('pagehide', event => { if (!event.persisted) api?.destroy(); });
  window.addEventListener('pageshow', event => { if (event.persisted) refresh(); });
  readState().then(refresh);
})();
