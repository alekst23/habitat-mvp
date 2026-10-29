const assert = require('node:assert/strict');
const {readFileSync} = require('node:fs');
const {resolve} = require('node:path');
const test = require('node:test');
const vm = require('node:vm');

function helper() {
  const context = {window: {}, queueMicrotask, document: {createElement: tag => ({tag})}};
  vm.runInNewContext(readFileSync(resolve(__dirname, '../backend/aicl/web/static/studio-grid.js'), 'utf8'), context);
  return context.window.HabitatStudioGrid;
}

function grid() {
  const listeners = new Map();
  const columns = ['amount', 'source'].map(id => ({width: 155, getColId: () => id, getActualWidth() { return this.width; }}));
  const state = {defaultColDef: {resizable: false, suppressMovable: true, suppressHeaderMenuButton: true}, destroyed: false, optionUpdates: 0, widthUpdates: 0};
  const emit = (name, event) => listeners.get(name)?.(event);
  const api = {
    isDestroyed: () => state.destroyed,
    getGridOption: name => state[name],
    setGridOption(name, value) { state.optionUpdates++; state[name] = value; },
    addEventListener: (name, listener) => listeners.set(name, listener),
    getColumns: () => columns,
    setColumnWidths(widths) {
      state.widthUpdates++;
      for (const {key, newWidth} of widths) columns.find(column => column.getColId() === key).width = newWidth;
      emit('columnResized', {source: 'api', columns});
    },
  };
  return {api, state, columns, resize(id, width, source) {
    const column = columns.find(column => column.getColId() === id);
    column.width = width;
    emit('columnResized', {source, columns: [column], finished: true});
  }};
}

test('Studio renderer enables native sort/resize once without changing typed data, formatting or safe source rendering', async () => {
  const {createCellRenderer} = helper();
  const current = grid();
  const renderer = createCellRenderer(field => field.id === 'source' ? params => ({tag: 'a', href: params.value}) : undefined);
  const cell = renderer({id: 'amount'})({api: current.api, value: 0.000001, valueFormatted: '$0.000001'});
  assert.equal(cell.textContent, '$0.000001');
  assert.equal(current.state.optionUpdates, 0, 'do not update a grid while it is rendering');
  const link = renderer({id: 'source'})({api: current.api, value: '/audit/jobs/source-run'});
  assert.equal(link.href, '/audit/jobs/source-run');
  const evidence = renderer({id: 'description'})({api: current.api, value: '<script>untrusted()</script>'});
  assert.equal(evidence.textContent, '<script>untrusted()</script>');
  assert.equal(evidence.innerHTML, undefined);
  await Promise.resolve();
  assert.deepEqual({...current.state.defaultColDef}, {resizable: true, sortable: true, suppressMovable: true, suppressHeaderMenuButton: true});
  assert.equal(current.state.optionUpdates, 1);
});

test('dragged widths survive Studio refresh without fighting untouched columns or leaking to another grid', async () => {
  const render = helper().createCellRenderer()({id: 'amount'});
  const first = grid();
  const second = grid();
  render({api: first.api, value: 1});
  render({api: second.api, value: 2});
  await Promise.resolve();
  first.resize('amount', 290, 'uiColumnResized');
  first.api.setColumnWidths([{key: 'amount', newWidth: 155}, {key: 'source', newWidth: 180}]);
  await Promise.resolve();
  await Promise.resolve();
  assert.equal(first.columns[0].width, 290);
  assert.equal(first.columns[1].width, 180);
  assert.equal(first.state.widthUpdates, 2, 'one restoration, no resize loop');
  assert.equal(second.columns[0].width, 155);
  first.resize('amount', 310, 'uiColumnResized');
  first.resize('amount', 155, 'api');
  first.state.destroyed = true;
  await Promise.resolve();
  assert.equal(first.state.widthUpdates, 2, 'pending callbacks do not touch a destroyed grid');
});
