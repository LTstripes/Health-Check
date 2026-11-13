(() => {
  'use strict';
  const listing = document.querySelector('[data-lab-listing]');
  if (listing) {
    const tabs = document.querySelector('nav[aria-label="Разделы анализов"]');
    const selectPanel = () => {
      const id = ['#lab-reports', '#lab-add'].includes(location.hash) ? location.hash : '#lab-analytes';
      if (tabs) for (const link of tabs.querySelectorAll('a')) {
        if (link.hash === id) link.setAttribute('aria-current', 'page');
        else link.removeAttribute('aria-current');
      }
    };
    selectPanel();
    window.addEventListener('hashchange', selectPanel);
    const filters = listing.querySelector('[data-lab-filters]');
    const search = listing.querySelector('[data-lab-search]');
    const history = listing.querySelector('[data-lab-history]');
    const rows = Array.from(listing.querySelectorAll('[data-lab-analyte]'));
    const normalize = text => text.trim().toLocaleLowerCase('ru-RU');
    const filter = () => {
      const query = normalize(search.value);
      let shown = 0;
      for (const row of rows) {
        row.hidden = !normalize(row.dataset.labName).includes(query)
          || (history.checked && Number(row.dataset.labCount) < 2);
        if (!row.hidden) shown++;
      }
      for (const group of listing.querySelectorAll('[data-lab-group]')) {
        group.hidden = !group.querySelector('[data-lab-analyte]:not([hidden])');
      }
      listing.querySelector('[data-lab-filter-status]').textContent = `Показано: ${shown} из ${rows.length}`;
      const empty = listing.querySelector('[data-lab-no-matches]');
      if (empty) empty.hidden = shown > 0;
    };
    search.addEventListener('input', filter);
    history.addEventListener('change', filter);
    filter();
    filters.hidden = false;
  }
  for (const chart of document.querySelectorAll('[data-lab-chart]')) {
    const output = chart.querySelector('[data-lab-chart-value]');
    for (const point of chart.querySelectorAll('[data-lab-point]')) {
      const show = () => { output.textContent = point.dataset.labPoint; };
      point.addEventListener('focus', show);
      point.addEventListener('pointerenter', show);
      point.addEventListener('click', show);
    }
  }
})();
