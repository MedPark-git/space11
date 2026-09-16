(function () {
  let openPicker = null;

  const fold = value => String(value || "").normalize("NFKC").toLocaleLowerCase();

  function close(picker, restoreFocus = false) {
    if (!picker || picker.destroyed) return;
    picker.wrapper.classList.remove("is-open");
    picker.input.setAttribute("aria-expanded", "false");
    picker.activeIndex = -1;
    if (openPicker === picker) openPicker = null;
    if (restoreFocus) picker.input.focus();
  }

  function closeAll() {
    if (openPicker) close(openPicker);
  }

  function open(picker) {
    if (openPicker && openPicker !== picker) close(openPicker);
    openPicker = picker;
    picker.wrapper.classList.add("is-open");
    picker.input.setAttribute("aria-expanded", "true");
    renderOptions(picker);
  }

  function selectedOptions(picker) {
    return [...picker.select.options].filter(option => option.selected && option.value !== "");
  }

  function renderChips(picker) {
    const selected = selectedOptions(picker);
    picker.chips.innerHTML = selected.map(option => `
      <span class="searchable-picker-chip">
        <span>${escapeHtml(option.textContent.trim())}</span>
        ${picker.select.disabled ? "" : `<button type="button" data-picker-remove="${escapeHtml(option.value)}" aria-label="${escapeHtml(option.textContent.trim())} 선택 해제">×</button>`}
      </span>`).join("");
    if (!picker.multiple && selected.length) picker.input.placeholder = selected[0].textContent.trim();
    else picker.input.placeholder = picker.originalPlaceholder;
  }

  function visibleOptions(picker) {
    const query = fold(picker.input.value.trim());
    return [...picker.select.options].filter(option => {
      if (!option.value || option.disabled || option.hidden) return false;
      if (option.selected && picker.multiple) return false;
      return !query || fold(option.textContent).includes(query) || fold(option.value).includes(query);
    });
  }

  function renderOptions(picker) {
    const rows = visibleOptions(picker);
    if (picker.activeIndex >= rows.length) picker.activeIndex = rows.length - 1;
    picker.list.innerHTML = rows.length ? rows.map((option, index) => `
      <button type="button" role="option" class="searchable-picker-option ${index === picker.activeIndex ? "is-active" : ""}"
        aria-selected="${option.selected ? "true" : "false"}" data-picker-value="${escapeHtml(option.value)}">
        ${escapeHtml(option.textContent.trim())}
      </button>`).join("") : '<div class="searchable-picker-empty">검색 결과가 없습니다.</div>';
  }

  function syncDisabled(picker) {
    const disabled = Boolean(picker.select.disabled);
    picker.input.disabled = disabled;
    picker.wrapper.classList.toggle("is-disabled", disabled);
    if (disabled) close(picker);
  }

  function selectValue(picker, value) {
    const option = [...picker.select.options].find(row => row.value === value);
    if (!option) return;
    if (picker.multiple) option.selected = true;
    else {
      picker.select.value = value;
      close(picker);
    }
    picker.input.value = "";
    renderChips(picker);
    renderOptions(picker);
    picker.select.dispatchEvent(new Event("change", { bubbles: true }));
    if (picker.multiple) picker.input.focus();
  }

  function enhance(select) {
    if (!select || select._searchablePicker) return select?._searchablePicker;
    const multiple = Boolean(select.multiple);
    const wrapper = document.createElement("div");
    wrapper.className = `searchable-picker ${multiple ? "is-multi" : "is-single"}`;
    const listId = `picker-${Math.random().toString(36).slice(2)}`;
    wrapper.innerHTML = `
      <div class="searchable-picker-control">
        <div class="searchable-picker-chips"></div>
        <input class="searchable-picker-input" type="search" autocomplete="off"
          role="combobox" aria-autocomplete="list" aria-expanded="false" aria-controls="${listId}">
        <button class="searchable-picker-toggle" type="button" aria-label="선택목록 열기">⌄</button>
      </div>
      <div id="${listId}" class="searchable-picker-list" role="listbox" ${multiple ? 'aria-multiselectable="true"' : ""}></div>`;
    select.insertAdjacentElement("afterend", wrapper);
    select.classList.add("searchable-picker-native");
    const picker = {
      select, wrapper, multiple,
      chips: wrapper.querySelector(".searchable-picker-chips"),
      input: wrapper.querySelector(".searchable-picker-input"),
      list: wrapper.querySelector(".searchable-picker-list"),
      activeIndex: -1,
      originalPlaceholder: select.dataset.placeholder || (multiple ? "검색하여 복수 선택" : "검색하여 선택"),
      destroyed: false,
    };
    select._searchablePicker = picker;
    picker.input.placeholder = picker.originalPlaceholder;
    syncDisabled(picker);

    picker.input.addEventListener("focus", () => open(picker));
    picker.input.addEventListener("input", () => { picker.activeIndex = -1; open(picker); });
    picker.input.addEventListener("keydown", event => {
      const rows = visibleOptions(picker);
      if (event.key === "Escape") { event.preventDefault(); close(picker); return; }
      if (event.key === "ArrowDown" || event.key === "ArrowUp") {
        event.preventDefault(); open(picker);
        const delta = event.key === "ArrowDown" ? 1 : -1;
        picker.activeIndex = rows.length ? (picker.activeIndex + delta + rows.length) % rows.length : -1;
        renderOptions(picker);
        picker.list.querySelector(".is-active")?.scrollIntoView({ block: "nearest" });
      }
      if (event.key === "Enter" && rows.length) {
        event.preventDefault();
        selectValue(picker, rows[Math.max(0, picker.activeIndex)]?.value);
      }
    });
    wrapper.querySelector(".searchable-picker-toggle").addEventListener("click", event => {
      event.stopPropagation();
      if (wrapper.classList.contains("is-open")) close(picker, true);
      else { open(picker); picker.input.focus(); }
    });
    picker.list.addEventListener("mousedown", event => event.preventDefault());
    picker.list.addEventListener("click", event => {
      const button = event.target.closest("[data-picker-value]");
      if (button) selectValue(picker, button.dataset.pickerValue);
    });
    picker.chips.addEventListener("click", event => {
      const button = event.target.closest("[data-picker-remove]");
      if (!button) return;
      const option = [...select.options].find(row => row.value === button.dataset.pickerRemove);
      if (option) option.selected = false;
      renderChips(picker); renderOptions(picker);
      select.dispatchEvent(new Event("change", { bubbles: true }));
      picker.input.focus();
    });
    select.addEventListener("change", () => renderChips(picker));
    new MutationObserver(() => { syncDisabled(picker); renderChips(picker); if (wrapper.classList.contains("is-open")) renderOptions(picker); })
      .observe(select, { childList: true, subtree: true, attributes: true, attributeFilter: ["selected", "disabled", "hidden"] });
    renderChips(picker);
    return picker;
  }

  function enhanceAll(root = document) {
    root.querySelectorAll("select[data-searchable]").forEach(enhance);
  }

  document.addEventListener("pointerdown", event => {
    if (openPicker && !openPicker.wrapper.contains(event.target)) close(openPicker);
  }, true);
  document.addEventListener("focusin", event => {
    if (openPicker && !openPicker.wrapper.contains(event.target)) close(openPicker);
  });
  document.addEventListener("keydown", event => {
    if (event.key === "Escape" && openPicker) close(openPicker);
  });
  document.addEventListener("close", event => {
    if (event.target instanceof HTMLDialogElement) closeAll();
  }, true);

  window.SearchablePicker = { enhance, enhanceAll, closeAll, refresh(select) {
    const picker = select?._searchablePicker || enhance(select);
    if (picker) { syncDisabled(picker); renderChips(picker); renderOptions(picker); }
  }};
  document.addEventListener("DOMContentLoaded", () => enhanceAll());
})();
