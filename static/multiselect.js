/* v110: accessible checkbox dropdown for categoric filters with native URLSearchParams multi-values. */
(() => {
  function init(select) {
    if (select.dataset.pctReady) return;
    select.dataset.pctReady = '1';
    select.multiple = true;
    select.classList.add('pct-native-multiple');
    const label = select.closest('label');
    if (!label) return;
    const title = label.childNodes[0]?.textContent?.trim() || select.getAttribute('aria-label') || select.name;
    const wrap = document.createElement('div');
    wrap.className = 'pct-filter-wrap';
    const caption = document.createElement('span');
    caption.className = 'pct-filter-label';
    caption.textContent = title;
    const details = document.createElement('details');
    details.className = 'pct-multiselect';
    const summary = document.createElement('summary');
    summary.setAttribute('aria-label', `Filter ${title}; select multiple`);
    const choices = document.createElement('div');
    choices.className = 'pct-filter-popover';
    choices.setAttribute('role', 'group');
    choices.setAttribute('aria-label', title);
    details.append(summary, choices);
    label.replaceWith(wrap);
    wrap.append(caption, select, details);
    function sync() {
      const selected = [...select.selectedOptions].filter(option => option.value);
      summary.textContent = selected.length === 0 ? 'All' : selected.length <= 2 ? selected.map(o => o.textContent).join(', ') : `${selected.length} selected`;
      summary.title = selected.length ? selected.map(o => o.textContent).join(', ') : `All ${title.toLowerCase()}`;
      const checklist = choices.querySelectorAll('input[data-pct-value]');
      checklist.forEach(input => {input.checked = selected.some(option => option.value === input.dataset.pctValue);});
    }
    function build() {
      choices.replaceChildren();
      const helper = document.createElement('div');
      helper.className = 'pct-filter-helper';
      helper.textContent = 'Select any combination · none selected = all';
      choices.append(helper);
      for (const option of select.options) {
        if (!option.value) continue;
        const line = document.createElement('label');
        line.className = 'pct-filter-option';
        const box = document.createElement('input');
        box.type = 'checkbox';
        box.dataset.pctValue = option.value;
        box.checked = option.selected;
        line.append(box, document.createTextNode(option.textContent));
        box.addEventListener('change', () => {
          const chosen = [...select.options].find(o => o.value === box.dataset.pctValue);
          if (chosen) chosen.selected = box.checked;
          for (const o of select.options) if (!o.value) o.selected = false;
          sync();
          select.dispatchEvent(new Event('change', {bubbles:true}));
        });
        choices.append(line);
      }
      sync();
    }
    new MutationObserver(build).observe(select, {childList:true});
    select.addEventListener('change', sync);
    select.form?.addEventListener('reset', () => setTimeout(sync, 0));
    document.addEventListener('click', event => {if (!details.contains(event.target)) details.open = false;});
    build();
  }
  document.querySelectorAll('select[data-multiselect]').forEach(init);
  window.pctMultiselect = {init};
})();
