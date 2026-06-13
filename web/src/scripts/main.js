import PinyinMatchModule from 'pinyin-match';
import { inject } from '@vercel/analytics';
import { injectSpeedInsights } from '@vercel/speed-insights';

const PinyinMatch = PinyinMatchModule?.default || PinyinMatchModule;

try {
    inject();
    injectSpeedInsights();
} catch (error) {
    console.warn('[tg_suoyin] analytics/speed-insights init failed:', error);
}

function safeGetStorage(key) {
    try {
        return window.localStorage.getItem(key);
    } catch (error) {
        console.warn('[tg_suoyin] localStorage get failed:', error);
        return null;
    }
}

function safeSetStorage(key, value) {
    try {
        window.localStorage.setItem(key, value);
        return true;
    } catch (error) {
        console.warn('[tg_suoyin] localStorage set failed:', error);
        return false;
    }
}

function readDirectoryData() {
    const payload = document.getElementById('directory-data');
    if (!payload?.textContent) return { sections: [], allItems: [], ads: { items: [], positions: {} } };

    try {
        const data = JSON.parse(payload.textContent);
        return {
            sections: Array.isArray(data.sections) ? data.sections : [],
            allItems: Array.isArray(data.allItems) ? data.allItems : [],
            ads: data.ads || { items: [], positions: {} },
        };
    } catch (error) {
        console.error('[tg_suoyin] failed to parse directory data:', error);
        return { sections: [], allItems: [], ads: { items: [], positions: {} } };
    }
}

const sidebar = document.getElementById('sidebar');
const sidebarOverlay = document.getElementById('sidebar-overlay');
const menuBtn = document.getElementById('menu-btn');
const closeSidebarBtn = document.getElementById('close-sidebar-btn');
const themeToggle = document.getElementById('theme-toggle');
const searchInput = document.getElementById('search-input');
const toast = document.getElementById('toast');
const backToTopBtn = document.getElementById('back-to-top');
const progressBar = document.getElementById('progress-bar');
const emptyState = document.getElementById('empty-state');
const contentContainer = document.getElementById('content-container');
const activeSection = document.getElementById('active-section');
const activeSectionTitle = document.getElementById('active-section-title');
const activeSectionMeta = document.getElementById('active-section-meta');
const activeGrid = document.getElementById('active-grid');
const directoryData = readDirectoryData();
const sections = Array.isArray(directoryData.sections) ? directoryData.sections : [];
const allItems = Array.isArray(directoryData.allItems) ? directoryData.allItems : [];
const adsByPosition = directoryData.ads?.positions || {};
const searchInlineAds = adsByPosition.search_inline || [];
let currentSectionId = activeSection?.dataset.currentId || 'featured';
let toastTimeout;

function showToast(msg) {
    if (!toast) return;
    toast.textContent = msg;
    toast.classList.add('show');
    clearTimeout(toastTimeout);
    toastTimeout = setTimeout(() => toast.classList.remove('show'), 2000);
}

function hashText(value) {
    let hash = 2166136261;
    for (let i = 0; i < value.length; i += 1) {
        hash ^= value.charCodeAt(i);
        hash = Math.imul(hash, 16777619);
    }
    return hash >>> 0;
}

function getAvatarColorClass(value) {
    return `avatar-color-${hashText(value || '?') % 6}`;
}

function getTelegramUsername(url) {
    if (!url || !url.includes('t.me/')) return '';
    const parts = url.split('t.me/');
    return parts[1]?.split('/')[0]?.split('?')[0] || '';
}

function setHighlightedText(target, text, matchPositions) {
    if (!target) return;
    target.textContent = '';

    if (!matchPositions || !Array.isArray(matchPositions)) {
        target.textContent = text;
        return;
    }

    const start = Math.max(0, Math.min(text.length, matchPositions[0]));
    const end = Math.max(start, Math.min(text.length - 1, matchPositions[1]));

    target.appendChild(document.createTextNode(text.substring(0, start)));

    const mark = document.createElement('mark');
    mark.textContent = text.substring(start, end + 1);
    target.appendChild(mark);

    target.appendChild(document.createTextNode(text.substring(end + 1)));
}

function createCopyIcon() {
    const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
    svg.setAttribute('width', '14');
    svg.setAttribute('height', '14');
    svg.setAttribute('viewBox', '0 0 24 24');
    svg.setAttribute('fill', 'none');
    svg.setAttribute('stroke', 'currentColor');
    svg.setAttribute('stroke-width', '2');
    svg.setAttribute('stroke-linecap', 'round');
    svg.setAttribute('stroke-linejoin', 'round');

    const rect = document.createElementNS('http://www.w3.org/2000/svg', 'rect');
    rect.setAttribute('x', '9');
    rect.setAttribute('y', '9');
    rect.setAttribute('width', '13');
    rect.setAttribute('height', '13');
    rect.setAttribute('rx', '2');
    rect.setAttribute('ry', '2');

    const path = document.createElementNS('http://www.w3.org/2000/svg', 'path');
    path.setAttribute('d', 'M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1');

    svg.append(rect, path);
    return svg;
}

function createCard(item, matches = {}) {
    const title = item.title || '';
    const desc = item.desc || '';
    const url = item.url || '';
    const username = getTelegramUsername(url);
    const firstLetter = title ? title.substring(0, 1).toUpperCase() : '?';
    const article = document.createElement('article');

    article.className = 'card';
    article.dataset.title = title;
    article.dataset.desc = desc;
    article.dataset.url = url;
    article.dataset.category = [item.categoryFullName, item.categoryKeywords, item.typeName].filter(Boolean).join(' ');

    const header = document.createElement('div');
    header.className = 'card-header';

    const icon = document.createElement('div');
    icon.className = `card-icon ${getAvatarColorClass(firstLetter)}`;
    icon.setAttribute('aria-hidden', 'true');
    if (username) {
        const img = document.createElement('img');
        img.src = `https://unavatar.io/telegram/${username}`;
        img.loading = 'lazy';
        img.alt = username;
        img.addEventListener('error', () => {
            icon.textContent = firstLetter;
        });
        icon.appendChild(img);
    } else {
        icon.textContent = firstLetter;
    }

    const titleWrap = document.createElement('div');
    titleWrap.className = 'card-title-wrap';

    const titleLink = document.createElement('a');
    titleLink.href = `/p/${item.id}`;
    titleLink.className = 'card-title';
    titleLink.title = title;
    setHighlightedText(titleLink, title, matches.title);

    const meta = document.createElement('div');
    meta.className = 'card-meta';

    const tag = document.createElement('span');
    tag.className = 'tag';
    tag.textContent = item.typeName || '资源';

    const count = document.createElement('span');
    count.textContent = `👥 ${item.countStr || '-'}`;
    meta.append(tag, count);
    titleWrap.append(titleLink, meta);
    header.append(icon, titleWrap);

    const descEl = document.createElement('div');
    descEl.className = 'card-desc';
    descEl.title = desc;
    setHighlightedText(descEl, desc || '没有描述', matches.desc);

    const actions = document.createElement('div');
    actions.className = 'card-actions';

    const directLink = document.createElement('a');
    directLink.className = 'card-action card-action-primary';
    directLink.href = url;
    directLink.target = '_blank';
    directLink.rel = 'noopener noreferrer';
    directLink.textContent = '直达';

    const detailLink = document.createElement('a');
    detailLink.className = 'card-action';
    detailLink.href = `/p/${item.id}`;
    detailLink.textContent = '详情';

    const copyBtn = document.createElement('button');
    copyBtn.className = 'card-action card-copy-btn';
    copyBtn.type = 'button';
    copyBtn.setAttribute('aria-label', '复制链接');
    copyBtn.dataset.url = url;
    copyBtn.append(createCopyIcon(), document.createTextNode('复制'));

    actions.append(directLink, detailLink, copyBtn);
    article.append(header, descEl, actions);
    return article;
}

function createAdCard(ad) {
    const article = document.createElement('article');
    article.className = 'card ad-result-card';

    const label = document.createElement('div');
    label.className = 'ad-label';
    label.textContent = '广告';

    const title = document.createElement('a');
    title.href = ad.url || '#';
    title.target = '_blank';
    title.rel = 'sponsored noopener noreferrer';
    title.className = 'card-title';
    title.textContent = ad.title || '推荐';

    const desc = document.createElement('div');
    desc.className = 'card-desc';
    desc.textContent = ad.description || '推广内容';

    const actions = document.createElement('div');
    actions.className = 'card-actions';

    const link = document.createElement('a');
    link.className = 'card-action card-action-primary';
    link.href = ad.url || '#';
    link.target = '_blank';
    link.rel = 'sponsored noopener noreferrer';
    link.textContent = '查看';

    actions.append(link);
    article.append(label, title, desc, actions);
    return article;
}

function renderCards(items, matchMap = new Map(), options = {}) {
    if (!activeGrid) return;
    const fragment = document.createDocumentFragment();
    const inlineAds = options.withAds ? searchInlineAds : [];
    const interval = 8;

    items.forEach((item, index) => {
        fragment.appendChild(createCard(item, matchMap.get(item.id) || {}));
        if (inlineAds.length > 0 && (index + 1) % interval === 0 && index + 1 < items.length) {
            const ad = inlineAds[Math.floor(index / interval) % inlineAds.length];
            fragment.appendChild(createAdCard(ad));
        }
    });
    activeGrid.replaceChildren(fragment);
}

function setActiveNav(id) {
    document.querySelectorAll('.nav-item').forEach((item) => {
        item.classList.toggle('active', item.dataset.id === id);
    });
}

function updateUrl({ sectionId, query, replace = false }) {
    const url = new URL(window.location);
    if (query) {
        url.searchParams.set('q', query);
        url.searchParams.delete('c');
    } else if (sectionId && sectionId !== 'featured') {
        url.searchParams.set('c', sectionId);
        url.searchParams.delete('q');
    } else {
        url.searchParams.delete('c');
        url.searchParams.delete('q');
    }

    const method = replace ? 'replaceState' : 'pushState';
    window.history[method]({}, '', url);
}

function setSectionHeader(title, count, subtitle = '') {
    if (activeSectionTitle) activeSectionTitle.textContent = title;
    if (activeSectionMeta) {
        activeSectionMeta.textContent = subtitle || `(${count})`;
    }
}

function renderSection(id, options = {}) {
    const section = sections.find((candidate) => candidate.id === id) || sections[0];
    if (!section) return;

    currentSectionId = section.id;
    if (activeSection) activeSection.dataset.currentId = section.id;
    setActiveNav(section.id);
    setSectionHeader(section.fullName || section.name, section.items?.length || 0);
    renderCards(section.items || []);
    if (emptyState) emptyState.style.display = 'none';
    if (activeSection) activeSection.style.display = '';
    if (searchInput && options.clearSearch) searchInput.value = '';
    if (options.updateUrl) updateUrl({ sectionId: section.id });
    if (options.scroll) {
        const top = activeSection
            ? activeSection.getBoundingClientRect().top + window.pageYOffset - 80
            : 0;
        window.scrollTo({ top, behavior: 'smooth' });
    }
}

function getMatches(item, query) {
    const title = item.title || '';
    const desc = item.desc || '';
    const url = item.url || '';
    const category = [item.categoryFullName, item.categoryKeywords, item.typeName].filter(Boolean).join(' ');
    const matchTitle = PinyinMatch.match(title, query);
    const matchDesc = PinyinMatch.match(desc, query);
    const matchCategory = category.toLowerCase().includes(query);
    const matchUrl = url.toLowerCase().includes(query);

    if (!matchTitle && !matchDesc && !matchCategory && !matchUrl) return null;
    return { title: matchTitle, desc: matchDesc };
}

function renderSearch(rawQuery, options = {}) {
    const query = rawQuery.trim().toLowerCase();
    if (!query) {
        renderSection(currentSectionId, { updateUrl: options.updateUrl, clearSearch: false });
        return;
    }

    const matchMap = new Map();
    const results = allItems.filter((item) => {
        const matches = getMatches(item, query);
        if (!matches) return false;
        matchMap.set(item.id, matches);
        return true;
    });

    setActiveNav('');
    setSectionHeader('搜索结果', results.length, `“${rawQuery.trim()}” · ${results.length} 个资源`);
    renderCards(results, matchMap, { withAds: true });
    if (emptyState) emptyState.style.display = results.length ? 'none' : 'block';
    if (activeSection) activeSection.style.display = results.length ? '' : 'none';
    if (options.updateUrl) updateUrl({ query: rawQuery.trim(), replace: true });
}

function initTheme() {
    const savedTheme = safeGetStorage('theme');
    const prefersDark = window.matchMedia('(prefers-color-scheme: dark)').matches;

    document.body.classList.toggle('dark', savedTheme === 'dark' || (!savedTheme && prefersDark));

    themeToggle?.addEventListener('click', () => {
        document.body.classList.toggle('dark');
        const isDark = document.body.classList.contains('dark');
        safeSetStorage('theme', isDark ? 'dark' : 'light');
    });
}

function initSidebar() {
    function openSidebar() {
        sidebar?.classList.add('open');
        sidebarOverlay?.classList.add('open');
        document.body.style.overflow = 'hidden';
    }

    function closeSidebar() {
        sidebar?.classList.remove('open');
        sidebarOverlay?.classList.remove('open');
        document.body.style.overflow = '';
    }

    menuBtn?.addEventListener('click', openSidebar);
    closeSidebarBtn?.addEventListener('click', closeSidebar);
    sidebarOverlay?.addEventListener('click', closeSidebar);

    document.querySelectorAll('.nav-item').forEach((item) => {
        item.addEventListener('click', () => {
            const id = item.dataset.id || 'featured';
            renderSection(id, { updateUrl: true, clearSearch: true, scroll: true });
            if (window.innerWidth <= 768) closeSidebar();
        });
    });
}

function initSearch() {
    searchInput?.addEventListener('input', (event) => {
        renderSearch(event.target.value || '', { updateUrl: true });
    });
}

async function copyUrl(url) {
    if (navigator.clipboard && navigator.clipboard.writeText) {
        await navigator.clipboard.writeText(url);
        return true;
    }

    const textarea = document.createElement('textarea');
    textarea.value = url;
    textarea.style.position = 'fixed';
    textarea.style.opacity = '0';
    document.body.appendChild(textarea);
    textarea.select();
    const copied = document.execCommand('copy');
    document.body.removeChild(textarea);
    return copied;
}

function initInteractions() {
    contentContainer?.addEventListener('click', async (event) => {
        const target = event.target;
        if (!(target instanceof Element)) return;

        const btn = target.closest('.card-copy-btn');
        if (!btn) return;

        event.preventDefault();
        const url = btn.getAttribute('data-url') || '';
        try {
            showToast((await copyUrl(url)) ? '已复制链接' : '复制失败');
        } catch {
            showToast('复制失败');
        }
    });
}

function initScrollFeatures() {
    window.addEventListener('scroll', () => {
        backToTopBtn?.classList.toggle('show', window.scrollY > 500);

        if (progressBar) {
            const winScroll = document.body.scrollTop || document.documentElement.scrollTop;
            const height = document.documentElement.scrollHeight - document.documentElement.clientHeight;
            progressBar.style.width = height > 0 ? `${(winScroll / height) * 100}%` : '0';
        }
    });

    backToTopBtn?.addEventListener('click', () => {
        window.scrollTo({ top: 0, behavior: 'smooth' });
    });
}

function initRouting() {
    const params = new URLSearchParams(window.location.search);
    const cat = params.get('c');
    const query = params.get('q');

    if (cat) {
        renderSection(cat, { updateUrl: false, clearSearch: false });
    }

    if (query && searchInput) {
        searchInput.value = query;
        renderSearch(query, { updateUrl: false });
    }
}

function init() {
    const initTasks = [
        ['theme', initTheme],
        ['sidebar', initSidebar],
        ['search', initSearch],
        ['interactions', initInteractions],
        ['scrollFeatures', initScrollFeatures],
        ['routing', initRouting],
    ];

    initTasks.forEach(([name, task]) => {
        try {
            task();
        } catch (error) {
            console.error(`[rectg] init failed: ${name}`, error);
        }
    });
}

if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
} else {
    init();
}
