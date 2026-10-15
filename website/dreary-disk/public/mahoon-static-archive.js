(() => {
  const homeSearch = document.getElementById('mSearch');
  homeSearch?.addEventListener('keydown', (event) => {
    if (event.key === 'Enter' && homeSearch.value.trim()) {
      event.preventDefault();
      location.assign('/search?q=' + encodeURIComponent(homeSearch.value.trim()));
    }
  });
  const configElement = document.getElementById('archiveConfig');
  if (!configElement) return;
  const config = JSON.parse(configElement.textContent);
  const grid = document.getElementById('archiveGrid');
  const search = document.getElementById('archiveSearch');
  const more = document.getElementById('archiveMore');
  const count = document.getElementById('archiveCount');
  const total = document.getElementById('archiveTotal');
  const empty = document.getElementById('archiveEmpty');
  const pageSize = Number(config.pageSize || 20);
  let offset = Number(config.initialNextOffset || grid.children.length);
  let generation = 0;
  let indexPromise;
  const pages = new Map();
  const number = new Intl.NumberFormat('fa-IR');
  const normalize = (value) => String(value || '').replace(/[۰-۹٠-٩]/g,
    (digit) => String('۰۱۲۳۴۵۶۷۸۹'.includes(digit) ? '۰۱۲۳۴۵۶۷۸۹'.indexOf(digit) : '٠١٢٣٤٥٦٧٨٩'.indexOf(digit)))
    .replace(/[يى]/g, 'ی').replace(/ك/g, 'ک').replace(/\u200c/g, ' ').replace(/\s+/g, ' ').trim().toLowerCase();
  document.querySelectorAll('[data-archive-link]').forEach((link) => {
    const active = normalize(link.dataset.archiveLink) === normalize(config.mode === 'category' ? config.category : 'همه مطالب');
    link.classList.toggle('is-active', active);
    if (active) link.setAttribute('aria-current', 'page');
  });

  async function index() {
    indexPromise ||= fetch('/search/search-index.json').then(async (response) => {
      if (!response.ok) throw new Error('Static search index could not be loaded');
      const data = await response.json();
      if (data.contract !== 'STATIC_SEARCH_CONTRACT_V2' || !Array.isArray(data.records)) {
        throw new Error('Static search index is invalid');
      }
      return data.records.map((record, position) => {
        const url = new URL(record.url, location.origin);
        if (!Number.isInteger(record.id) || url.origin !== location.origin || !url.pathname.startsWith('/post/')) {
          throw new Error('Static search record is invalid');
        }
        return { ...record, path: url.pathname, page: Math.floor(position / pageSize) + 1 };
      });
    }).catch((error) => { indexPromise = null; throw error; });
    return indexPromise;
  }

  async function card(record) {
    const path = record.archivePath || (record.page === 1 ? '/posts/' : '/posts/page/' + record.page);
    if (!pages.has(path)) {
      pages.set(path, fetch(path).then(async (response) => {
        if (!response.ok) throw new Error('Static archive page could not be loaded');
        return new DOMParser().parseFromString(await response.text(), 'text/html');
      }).catch((error) => { pages.delete(path); throw error; }));
    }
    const documentPage = await pages.get(path);
    const article = [...documentPage.querySelectorAll('#archiveGrid article')].find((item) =>
      new URL(item.querySelector('a').getAttribute('href'), location.origin).pathname === record.path);
    if (!article) throw new Error('Static archive card is missing');
    return article.cloneNode(true);
  }

  async function load(reset) {
    const current = ++generation;
    more.disabled = true;
    try {
      const records = await index();
      const query = normalize(search.value);
      const categoryRecords = config.mode === 'category' ? records.filter((record) =>
        normalize(record.category) === normalize(config.category) || (record.tags || []).some((tag) =>
          (config.category_tags || []).includes(tag))).map((record, position) => {
            const page = Math.floor(position / pageSize) + 1;
            return { ...record, archivePath: '/category/' + encodeURIComponent(config.category)
              + (page === 1 ? '/' : '/page/' + page) };
          }) : records;
      const filtered = categoryRecords.filter((record) => !query || (/^\d+$/.test(query) ? String(record.id) === query
        : normalize(record.normalized_search_text).includes(query)));
      const start = reset ? 0 : offset;
      const cards = await Promise.all(filtered.slice(start, start + pageSize).map(card));
      if (current !== generation) return;
      if (reset) grid.replaceChildren();
      grid.append(...cards);
      offset = start + cards.length;
      more.hidden = offset >= filtered.length;
      count.textContent = `نمایش ${number.format(offset)} مطلب از ${number.format(filtered.length)}`;
      total.textContent = number.format(filtered.length) + ' مطلب';
      empty.textContent = filtered.length === 0 ? 'نتیجه‌ای پیدا نشد.' : '';
      empty.hidden = filtered.length > 0;
    } catch {
      if (current !== generation) return;
      count.textContent = 'خطا در دریافت مطالب';
      empty.textContent = 'دریافت مطالب انجام نشد.';
      empty.hidden = false;
    } finally {
      if (current === generation) more.disabled = false;
    }
  }

  let timer;
  search.addEventListener('input', () => {
    clearTimeout(timer);
    timer = setTimeout(() => load(true), 300);
  });
  more.addEventListener('click', () => load(false));
  const query = new URLSearchParams(location.search).get('q');
  if (query) { search.value = query; load(true); }
})();
