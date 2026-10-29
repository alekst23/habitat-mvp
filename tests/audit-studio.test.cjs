const assert = require('node:assert/strict');
const { readFileSync } = require('node:fs');
const { resolve } = require('node:path');
const test = require('node:test');
const vm = require('node:vm');

function mount(kind, rows, options = {}) {
  const target = { id: 'audit-table', hidden: true, dataset: { kind, source: 'rows', fallback: 'fallback' }, replaceChildren() {} };
  const fallback = { hidden: false };
  const nodes = { rows: { textContent: JSON.stringify(rows) }, fallback };
  let props;
  const studio = options.missing ? undefined : {
    studioTheme: { withParams: value => value }, createWidgets: value => value,
    createStudio: (_target, value) => { props = value; if (options.throw) throw Error('Unavailable'); return {}; },
  };
  const context = {
    window: { agStudio: studio }, URL, URLSearchParams, Intl, Date, Number,
    location: { origin: 'http://127.0.0.1:4173', search: '?instance_id=agent-1&date_from=2026-10-01&date_to=2026-10-28&status_deliverables=draft' },
    document: { querySelectorAll: () => [target], getElementById: id => nodes[id], createElement: tag => ({ tag }) },
  };
  vm.runInNewContext(readFileSync(resolve(__dirname, '../backend/aicl/web/static/studio-grid.js'), 'utf8'), context);
  vm.runInNewContext(readFileSync(resolve(__dirname, '../backend/aicl/web/static/audit-studio.js'), 'utf8'), context);
  return { target, fallback, props };
}

test('audit Studio formats recorded units without changing amounts and confines source navigation', () => {
  const costs = mount('costs', [{ created_at: '2026-10-28T13:09:13Z', amount_usd: 0.000001, category: 'inference_usage', evidence_url: '/audit/jobs/run-1#step-1' }]);
  const source = costs.props.data.sources[0];
  const field = id => source.fields.find(item => item.id === id);
  assert.equal(field('amount_usd').createValueFormatter()(source.data[0].amount_usd), '$0.000001');
  assert.match(field('created_at').createValueFormatter()(field('created_at').accessor(source.data[0])), /9:09 AM EDT/);
  assert.equal(costs.fallback.hidden, false);
  costs.props.onRenderStateChanged({ renderState: 'rendered' });
  assert.equal(costs.fallback.hidden, true);
  assert.equal(costs.target.dataset.studioState, 'ready');
  assert.equal(costs.props.mode, 'view');
  assert.equal(costs.props.enableFilterEditingInViewMode, true);
  assert.equal(costs.props.ai, undefined);

  const widgets = costs.props.widgets();
  const render = widgets.overrides[0].options.createCellRenderer(field('evidence_url'));
  const link = render({ value: '/audit/jobs/run-1#step-1' });
  assert.equal(link.tag, 'a');
  const url = new URL(link.href, 'http://127.0.0.1:4173');
  assert.equal(url.pathname, '/audit/jobs/run-1');
  assert.equal(url.hash, '#step-1');
  assert.equal(url.searchParams.get('instance_id'), 'agent-1');
  assert.equal(url.searchParams.get('date_from'), '2026-10-01');
  assert.equal(url.searchParams.get('status_deliverables'), 'draft');
  for (const value of ['https://evil.example/', '//evil.example/', '/\\evil.example/', 'javascript:alert(1)', '/audit/../outside']) {
    assert.equal(render({ value }).tag, 'span', value);
  }

  const campaign = mount('campaign', [{ day: 1, spend_minor: 125, cpc_minor: 5, cpi_minor: null, run_id: 'run-1' }]);
  const metrics = campaign.props.data.sources[0];
  const spend = metrics.fields.find(item => item.id === 'spend_usd');
  assert.equal(metrics.data[0].spend_usd, 1.25);
  assert.equal(spend.createValueFormatter()(metrics.data[0].spend_usd), '$1.25');
  assert.equal(metrics.data[0].cpc_usd, 0.05);
  assert.equal(metrics.data[0].cpi_usd, null);
  assert.equal(metrics.data[0].evidence_url, '/audit/jobs/run-1');
});

test('source tables survive missing, rejected, and asynchronously failed Studio initialization', () => {
  for (const options of [{ missing: true }, { throw: true }]) {
    const result = mount('costs', [], options);
    assert.equal(result.target.hidden, true);
    assert.equal(result.fallback.hidden, false);
  }
  const result = mount('costs', []);
  result.props.onRenderStateChanged({ renderState: 'rendered' });
  result.props.onErrorRaised({ fatal: true });
  result.props.onRenderStateChanged({ renderState: 'rendered' });
  assert.equal(result.target.hidden, true);
  assert.equal(result.fallback.hidden, false);
  assert.equal(result.target.dataset.studioState, 'fallback');
});
