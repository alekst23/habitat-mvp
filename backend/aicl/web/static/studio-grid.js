/* Shared presentation behavior for AG Studio's built-in grid widgets. */
(() => {
  'use strict';
  const grids = new WeakMap();

  function enableColumns(api) {
    if (!api || grids.has(api)) return;
    const state = {widths: new Map(), pending: false};
    grids.set(api, state);

    const restoreWidths = () => {
      if (state.pending) return;
      state.pending = true;
      queueMicrotask(() => {
        state.pending = false;
        if (api.isDestroyed()) return;
        const widths = (api.getColumns() || []).flatMap(column => {
          const width = state.widths.get(column.getColId());
          return width != null && column.getActualWidth() !== width
            ? [{key: column.getColId(), newWidth: width}] : [];
        });
        if (widths.length) api.setColumnWidths(widths);
      });
    };

    // Studio reapplies its initial width when the widget refreshes or changes size.
    // Keep only widths the owner has dragged, within this grid's lifetime. There is
    // no cross-owner browser storage and no access to Studio's private internals.
    api.addEventListener('columnResized', event => {
      if (event.source === 'uiColumnResized') {
        for (const column of event.columns || (event.column ? [event.column] : [])) {
          state.widths.set(column.getColId(), column.getActualWidth());
        }
      } else if (state.widths.size) restoreWidths();
    });

    // AG Studio 3.0.0 disables resize in its built-in grid and exposes no resize
    // option. Its supported createCellRenderer hook supplies the public AG Grid
    // API. Defer the option update until the current cell render has finished.
    queueMicrotask(() => {
      if (api.isDestroyed()) return;
      api.setGridOption('defaultColDef', {...api.getGridOption('defaultColDef'), resizable: true, sortable: true});
    });
  }

  window.HabitatStudioGrid = Object.freeze({
    createCellRenderer: createCustomRenderer => field => {
      const customRenderer = createCustomRenderer?.(field);
      return params => {
        enableColumns(params.api);
        if (customRenderer) return customRenderer(params);
        // A DOM text node preserves Studio's formatter and never interprets audit
        // evidence as HTML. Sorting continues to use the original typed values.
        const cell = document.createElement('span');
        cell.textContent = String(params.valueFormatted ?? params.value ?? '');
        return cell;
      };
    },
  });
})();
