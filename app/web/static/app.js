let latestData = null;
let currentUrl = null;
let isIngesting = false;
let currentQueryController = null;
let currentOverviewController = null;
let _summaryAbortController = null;
let _summaryFetchId = 0;
let latestHistoryArchive = [];
let historyViewStatus = {};  // date -> viewed_at | null
let currentBoardSlug = null;
let availableBoards = [];
let availablePromptTemplates = [];
let overlayFocusStack = [];

const SUMMARY_LOADING_TEXT = 'AI 编辑正在努力生成今日简报，这可能需要几十秒...';
const SUMMARY_CACHE_KEY = 'argos_summary_cache';
const OVERLAY_FOCUSABLE_SELECTOR = [
    'button:not([disabled])',
    '[href]',
    'input:not([disabled])',
    'select:not([disabled])',
    'textarea:not([disabled])',
    '[tabindex]:not([tabindex="-1"])'
].join(', ');
const OVERLAY_DIALOG_LABELS = {
    'persona-panel': '偏好设置',
    'history-modal': '历史简报归档',
    'catchup-modal': '精炼补读',
    'magazine-modal': '本周深度周刊',
    'insights-modal': '跨天话题洞察',
    'sources-modal': '信息源管理',
    'refresh-modal': '重新调教简报',
    'stats-modal': '数据统计',
    'board-modal': '板块管理',
    'saved-modal': '我的收藏',
    'rag-panel': '深度追问'
};

const ICONS = {
    external: '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6M15 3h6v6M10 14L21 3"/></svg>',
    ask: '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/></svg>',
    like: '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M14 9V5a3 3 0 0 0-3-3l-4 9v11h11.28a2 2 0 0 0 2-1.7l1.38-9a2 2 0 0 0-2-2.3zM7 22H4a2 2 0 0 1-2-2v-7a2 2 0 0 1 2-2h3"/></svg>',
    dislike: '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M10 15v4a3 3 0 0 0 3 3l4-9V2H5.72a2 2 0 0 0-2 1.7l-1.38 9a2 2 0 0 0 2 2.3zm7-13h3a2 2 0 0 1 2 2v7a2 2 0 0 1-2 2h-3"/></svg>',
    favorite: '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polygon points="12 2 15.09 8.26 22 9.27 17 14.14 18.18 21.02 12 17.77 5.82 21.02 7 14.14 2 9.27 8.91 8.26 12 2"/></svg>',
    readLater: '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M19 21l-7-5-7 5V5a2 2 0 0 1 2-2h10a2 2 0 0 1 2 2z"/></svg>'
};

// url -> Set of saved statuses ("favorite" | "read_later")
let savedStatusMap = {};

document.addEventListener('DOMContentLoaded', async () => {
    _initTheme();
    _primeBoardSlugFromStorage();
    setupOverlayExperience();
    setupBoardFormExperience();

    // Render any same-day cache before non-critical bootstrap work.
    const cached = _loadCachedSummary();
    if (cached) {
        _renderSummaryData(cached);
    }

    const promptTemplatesPromise = loadPromptTemplates();

    setupRagPanel();
    setupHistoryPanel();
    _refreshCatchupBadge();
    loadSavedState();

    await initBoards();
    fetchSummary();
    await promptTemplatesPromise;
});

function _initTheme() {
    let saved = null;
    try { saved = localStorage.getItem('argos-theme'); } catch (_) {}
    const prefersDark = window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)').matches;
    const isLight = saved ? saved === 'light' : !prefersDark;
    if (isLight) {
        document.documentElement.classList.add('light-mode');
    }
    _updateThemeIcon();
}

function toggleTheme() {
    const isLight = document.documentElement.classList.toggle('light-mode');
    try { localStorage.setItem('argos-theme', isLight ? 'light' : 'dark'); } catch (_) {}
    _updateThemeIcon();
}

function _updateThemeIcon() {
    const isLight = document.documentElement.classList.contains('light-mode');
    const sun = document.getElementById('theme-icon-sun');
    const moon = document.getElementById('theme-icon-moon');
    if (sun) sun.style.display = isLight ? 'none' : 'inline-block';
    if (moon) moon.style.display = isLight ? 'inline-block' : 'none';
}

function setupOverlayExperience() {
    Object.entries(OVERLAY_DIALOG_LABELS).forEach(([id, label]) => {
        const element = document.getElementById(id);
        if (!element) return;
        element.setAttribute('role', 'dialog');
        element.setAttribute('aria-modal', 'true');
        element.setAttribute('aria-label', label);
    });

    document.addEventListener('keydown', handleOverlayEscape);
    syncOverlayState();
}

function _primeBoardSlugFromStorage() {
    try {
        const saved = localStorage.getItem('argos_board');
        if (saved) {
            currentBoardSlug = saved;
        }
    } catch (_) {
        currentBoardSlug = null;
    }
}

function rememberOverlayTrigger(container = null) {
    const active = document.activeElement;
    if (active instanceof HTMLElement && (!container || !container.contains(active))) {
        overlayFocusStack.push(active);
    } else {
        overlayFocusStack.push(null);
    }
}

function restoreOverlayTrigger() {
    while (overlayFocusStack.length > 0) {
        const trigger = overlayFocusStack.pop();
        if (trigger && trigger.isConnected) {
            _focusElement(trigger);
            return;
        }
    }
}

function _focusElement(element) {
    if (!element || typeof element.focus !== 'function') return;
    const runFocus = () => {
        if (element.isConnected) {
            try {
                element.focus({ preventScroll: true });
            } catch (_) {
                element.focus();
            }
        }
    };
    runFocus();
    requestAnimationFrame(runFocus);
    setTimeout(runFocus, 0);
}

function focusOverlayElement(container, preferredSelector = null) {
    if (!container) return;
    const preferred = preferredSelector ? container.querySelector(preferredSelector) : null;
    const fallback = container.querySelector(OVERLAY_FOCUSABLE_SELECTOR);
    const target = preferred || fallback;
    _focusElement(target);
}

function isOverlayOpen(element) {
    return !!(element && element.classList.contains('active'));
}

function isRagPanelOpen() {
    const panel = document.getElementById('rag-panel');
    return !!(panel && panel.classList.contains('open'));
}

function syncOverlayState() {
    const hasOpenModal = !!document.querySelector('.modal-overlay.active');
    document.body.classList.toggle('is-overlay-open', hasOpenModal || isRagPanelOpen());
}

function openOverlay(element, preferredSelector = null) {
    if (!element || isOverlayOpen(element)) return;
    rememberOverlayTrigger(element);
    element.classList.add('active');
    syncOverlayState();
    focusOverlayElement(element, preferredSelector);
}

function closeOverlay(element, { restoreFocus = true } = {}) {
    if (!element || !isOverlayOpen(element)) return;
    element.classList.remove('active');
    syncOverlayState();
    if (restoreFocus) {
        restoreOverlayTrigger();
    }
}

function toggleOverlay(element, preferredSelector = null) {
    if (!element) return false;
    if (isOverlayOpen(element)) {
        closeOverlay(element);
        return false;
    }
    openOverlay(element, preferredSelector);
    return true;
}

function openRagOverlay(preferredSelector = '#rag-close-btn') {
    const panel = document.getElementById('rag-panel');
    const overlay = document.getElementById('rag-overlay');
    if (!panel || !overlay) return;
    if (!panel.classList.contains('open')) {
        rememberOverlayTrigger(panel);
    }
    overlay.classList.add('visible');
    panel.classList.add('open');
    syncOverlayState();
    focusOverlayElement(panel, preferredSelector);
}

function closeRagOverlay({ restoreFocus = true } = {}) {
    const panel = document.getElementById('rag-panel');
    const overlay = document.getElementById('rag-overlay');
    if (panel) panel.classList.remove('open');
    if (overlay) overlay.classList.remove('visible');
    syncOverlayState();
    if (restoreFocus) {
        restoreOverlayTrigger();
    }
}

function handleOverlayEscape(event) {
    if (event.key !== 'Escape') return;
    if (dismissTopOverlay()) {
        event.preventDefault();
        event.stopPropagation();
    }
}

function dismissTopOverlay() {
    const dismissOrder = [
        ['saved-modal', toggleSavedPanel],
        ['board-modal', closeBoardModal],
        ['refresh-modal', closeRefreshModal],
        ['stats-modal', toggleStatsPanel],
        ['sources-modal', toggleSourcesPanel],
        ['insights-modal', toggleInsightsPanel],
        ['magazine-modal', toggleMagazinePanel],
        ['catchup-modal', toggleCatchupPanel],
        ['history-modal', toggleHistoryPanel],
        ['persona-panel', togglePersonaPanel]
    ];

    for (const [id, closeFn] of dismissOrder) {
        const element = document.getElementById(id);
        if (isOverlayOpen(element)) {
            closeFn();
            return true;
        }
    }

    if (isRagPanelOpen()) {
        closeRagPanel();
        return true;
    }

    return false;
}

function clearElement(element) {
    if (!element) return;
    while (element.firstChild) {
        element.removeChild(element.firstChild);
    }
}

function showLoadingState(message = SUMMARY_LOADING_TEXT) {
    const loadingState = document.getElementById('loading-state');
    clearElement(loadingState);
    loadingState.style.display = 'flex';

    const spinner = document.createElement('div');
    spinner.className = 'spinner';

    const text = document.createElement('p');
    text.textContent = message;

    loadingState.appendChild(spinner);
    loadingState.appendChild(text);
}

function showErrorState(message, retryHandler) {
    const loadingState = document.getElementById('loading-state');
    clearElement(loadingState);
    loadingState.style.display = 'flex';

    const box = document.createElement('div');
    box.className = 'error-message';

    const text = document.createElement('p');
    text.textContent = `获取简报失败: ${message}`;

    const retryButton = document.createElement('button');
    retryButton.className = 'retry-btn';
    retryButton.type = 'button';
    retryButton.textContent = '重试';
    retryButton.addEventListener('click', retryHandler);

    box.appendChild(text);
    box.appendChild(retryButton);
    loadingState.appendChild(box);
}

function computeSourceStats(items) {
    const stats = {};
    for (const item of items || []) {
        const source = item.source || '未知来源';
        stats[source] = (stats[source] || 0) + 1;
    }
    return stats;
}

async function initBoards() {
    try {
        const res = await fetch('/api/v1/boards');
        availableBoards = await res.json();
        
        const container = document.getElementById('board-tabs');
        if (availableBoards.length === 0) {
            currentBoardSlug = null;
            return;
        }

        // Determine initial active board from localStorage or first default
        const saved = localStorage.getItem('argos_board');
        if (saved && availableBoards.find(b => b.slug === saved)) {
            currentBoardSlug = saved;
        } else {
            const def = availableBoards.find(b => b.is_default);
            currentBoardSlug = def ? def.slug : availableBoards[0].slug;
        }

        container.style.display = 'flex';
        renderBoardTabs();
    } catch (e) {
        currentBoardSlug = null;
        console.error("Failed to initialize boards", e);
    }
}

function renderBoardTabs() {
    const container = document.getElementById('board-tabs');
    let html = '';
    for (let i = 0; i < availableBoards.length; i++) {
        const b = availableBoards[i];
        const isActive = b.slug === currentBoardSlug ? 'active' : '';
        html += `<div class="board-tab-wrapper ${isActive}" draggable="true" data-slug="${b.slug}" data-index="${i}">
            <button class="board-tab ${isActive}" onclick="switchBoard('${b.slug}')">
                ${b.icon} ${b.name}
            </button>
            <button class="board-edit-btn" onclick="openBoardModal('${b.slug}')" title="设置此板块">⚙️</button>
        </div>`;
    }
    html += `<button class="board-add-btn" onclick="openBoardModal()" title="新建板块">➕ 添加板块</button>`;
    container.innerHTML = html;
    
    _setupBoardDragAndDrop(container);
}

function _setupBoardDragAndDrop(container) {
    let draggedItem = null;

    const items = container.querySelectorAll('.board-tab-wrapper');
    items.forEach(item => {
        item.addEventListener('dragstart', (e) => {
            draggedItem = item;
            e.dataTransfer.effectAllowed = 'move';
            item.classList.add('dragging');
        });

        item.addEventListener('dragend', () => {
            item.classList.remove('dragging');
            draggedItem = null;
        });

        item.addEventListener('dragover', (e) => {
            e.preventDefault();
            e.dataTransfer.dropEffect = 'move';
            if (item !== draggedItem) {
                const rect = item.getBoundingClientRect();
                const mid = rect.left + rect.width / 2;
                if (e.clientX < mid) {
                    item.parentNode.insertBefore(draggedItem, item);
                } else {
                    item.parentNode.insertBefore(draggedItem, item.nextSibling);
                }
            }
        });

        item.addEventListener('drop', async (e) => {
            e.preventDefault();
            // Collect new order
            const wrappers = container.querySelectorAll('.board-tab-wrapper');
            const newOrder = [];
            wrappers.forEach((w, index) => {
                newOrder.push({
                    slug: w.dataset.slug,
                    display_order: index
                });
            });
            
            // Optimistically update local array
            const boardMap = {};
            availableBoards.forEach(b => boardMap[b.slug] = b);
            availableBoards = newOrder.map(o => {
                const b = boardMap[o.slug];
                b.display_order = o.display_order;
                return b;
            });
            
            // Send requests to backend
            try {
                await Promise.all(newOrder.map(o => 
                    fetch(`/api/v1/boards/${o.slug}`, {
                        method: 'PATCH',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ display_order: o.display_order })
                    })
                ));
            } catch (err) {
                console.error('Failed to save new board order', err);
            }
        });
    });
}

function switchBoard(slug) {
    if (slug === currentBoardSlug) return;
    currentBoardSlug = slug;
    localStorage.setItem('argos_board', slug);
    renderBoardTabs();
    
    // Close panels if open
    closeOverlay(document.getElementById('persona-panel'), { restoreFocus: false });
    closeOverlay(document.getElementById('insights-modal'), { restoreFocus: false });
    
    // Try to show cached data for new board immediately
    latestData = null;
    const cached = _loadCachedSummary();
    if (cached) {
        _renderSummaryData(cached);
    } else {
        // No cache — immediately show loading so user sees the switch happened
        const contentState = document.getElementById('content-state');
        if (contentState) contentState.style.display = 'none';
        showLoadingState();
    }
    fetchSummary();
}

// ==========================================
// Board Management Logic
// ==========================================

let wizardMessages = [];           // conversation history
let wizardLastConfig = null;       // most recent suggested config
let wizardIsLoading = false;
let wizardTopic = '';              // derived topic for feed-fix requests
let wizardBrokenFeeds = new Set(); // broken feed URLs not yet replaced

async function loadPromptTemplates() {
    try {
        const res = await fetch('/api/v1/boards/prompts/templates');
        if (res.ok) {
            const data = await res.json();
            availablePromptTemplates = data.templates || [];
            _populatePromptDropdown();
        }
    } catch (e) {
        console.error('Failed to load prompt templates', e);
    }
}

function _populatePromptDropdown() {
    const select = document.getElementById('board-prompt-key');
    if (!select || availablePromptTemplates.length === 0) return;
    
    select.innerHTML = '';
    for (const tpl of availablePromptTemplates) {
        const opt = document.createElement('option');
        opt.value = tpl;
        opt.textContent = tpl + (tpl === 'daily_briefing' ? ' (默认)' : '');
        select.appendChild(opt);
    }
}

function toggleAdvancedSettings(btn) {
    btn.classList.toggle('open');
    const panel = document.getElementById('board-advanced-settings');
    if (panel.style.display === 'none') {
        panel.style.display = 'block';
    } else {
        panel.style.display = 'none';
    }
}

const PRESET_TEMPLATES = {
    python_dev: {
        slug: 'python-dev',
        name: 'Python 开发',
        icon: '❖',
        source_type: 'github',
        source_config: { repos: [{owner: 'python', repo: 'cpython'}, {owner: 'pallets', repo: 'flask'}] },
        system_prompt: '你是一个资深的 Python 开发者，请帮我总结这些 Python 相关的最新动态。'
    },
    ai_research: {
        slug: 'ai-research',
        name: 'AI 研究',
        icon: '❖',
        source_type: 'hackernews',
        source_config: { fetch_top_stories: 40, min_score: 150 },
        system_prompt: '请从 HN 热帖中筛选出与 AI、大模型、机器学习相关的论文和项目进行总结。'
    },
    indie_hacker: {
        slug: 'indie-hacker',
        name: '独立开发者',
        icon: '❖',
        source_type: 'reddit',
        source_config: { subreddits: [{subreddit: 'SaaS', sort: 'hot', min_score: 50}], fetch_comments: 10 },
        system_prompt: '关注独立开发、SaaS、产品营销相关的讨论，总结出有价值的商业洞察。'
    }
};

const BOARD_SOURCE_TYPE_META = {
    rss: { label: 'RSS 订阅源' },
    pure_llm: { label: '纯 LLM 生成' },
    hackernews: { label: 'Hacker News 热帖' },
    reddit: { label: 'Reddit 社区' },
    github: { label: 'GitHub 动态' },
    multi: { label: '混合数据源' }
};
let boardFormBaseline = '';
let boardFormDirty = false;
let boardHasSavedVersion = false;

function applyPresetTemplate(presetKey) {
    const tpl = PRESET_TEMPLATES[presetKey];
    if (!tpl) return;
    
    wizardLastConfig = tpl;
    applyWizardConfig();
}

function setupBoardFormExperience() {
    const form = document.getElementById('board-form');
    if (!form || form.dataset.enhanced === 'true') return;

    const refreshSummary = (event) => {
        if (!(event.target instanceof HTMLElement)) return;
        clearBoardFormFeedback();
        syncBoardFormState({ fromInput: true });
        if (event.target.id !== 'board-source-type') {
            renderBoardConfigSummary();
        }
    };

    form.addEventListener('input', refreshSummary);
    form.addEventListener('change', refreshSummary);
    form.dataset.enhanced = 'true';
    renderBoardConfigSummary();
}

function openBoardAdvancedSettings() {
    const panel = document.getElementById('board-advanced-settings');
    const toggleBtn = document.querySelector('.section-toggle-btn');
    if (panel) panel.style.display = 'block';
    if (toggleBtn) toggleBtn.classList.add('open');
}

function setBoardFormFeedback(type, message) {
    const feedback = document.getElementById('board-form-feedback');
    if (!feedback) return;
    feedback.className = `board-form-feedback board-form-feedback--${type}`;
    feedback.textContent = message;
    feedback.style.display = 'block';
    feedback.setAttribute('role', type === 'error' ? 'alert' : 'status');
}

function clearBoardFormFeedback() {
    const feedback = document.getElementById('board-form-feedback');
    if (!feedback) return;
    feedback.textContent = '';
    feedback.style.display = 'none';
    feedback.className = 'board-form-feedback';
    feedback.setAttribute('role', 'status');
}

function getBoardFieldValue(id, fallback = '') {
    return document.getElementById(id)?.value ?? fallback;
}

function captureBoardFormFingerprint() {
    const sourceType = getBoardFieldValue('board-source-type', 'rss');
    return JSON.stringify({
        slug: getBoardFieldValue('board-slug').trim(),
        name: getBoardFieldValue('board-name').trim(),
        icon: getBoardFieldValue('board-icon').trim(),
        sourceType,
        source: {
            rssFeeds: getBoardFieldValue('board-rss-feeds').trim(),
            llmItems: getBoardFieldValue('board-llm-items', '5').trim(),
            llmStyle: getBoardFieldValue('board-llm-style').trim(),
            hnTop: getBoardFieldValue('board-hn-top', '30').trim(),
            hnScore: getBoardFieldValue('board-hn-score', '100').trim(),
            redditSubs: getBoardFieldValue('board-reddit-subs').trim(),
            redditComments: getBoardFieldValue('board-reddit-comments', '5').trim(),
            githubRepos: getBoardFieldValue('board-github-repos').trim(),
            githubUsers: getBoardFieldValue('board-github-users').trim(),
            multiJson: getBoardFieldValue('board-multi-json').trim(),
        },
        promptKey: getBoardFieldValue('board-prompt-key', 'daily_briefing').trim(),
        outputLanguage: getBoardFieldValue('board-output-language', 'auto').trim(),
        prompt: getBoardFieldValue('board-prompt').trim(),
        schedule: getBoardFieldValue('board-schedule').trim(),
        notifyChannels: getBoardFieldValue('board-notify').trim(),
        perspectives: getBoardFieldValue('board-perspectives').trim(),
    });
}

function updateBoardPreviewHint() {
    const hint = document.getElementById('board-preview-hint');
    if (!hint) return;
    if (!boardHasSavedVersion) {
        hint.textContent = '当前试运行会基于表单里的临时配置，不会写入数据库。确认效果后再保存即可。';
        return;
    }
    if (boardFormDirty) {
        hint.textContent = '当前试运行会读取表单里的最新修改，但不会自动保存到数据库。';
        return;
    }
    hint.textContent = '当前试运行会基于表单里的最新配置，不会自动保存到数据库。';
}

function resetBoardFormState({ hasSavedVersion = false } = {}) {
    boardHasSavedVersion = hasSavedVersion;
    boardFormBaseline = captureBoardFormFingerprint();
    boardFormDirty = false;
    updateBoardPreviewHint();
}

function syncBoardFormState({ fromInput = false } = {}) {
    const nextDirty = captureBoardFormFingerprint() !== boardFormBaseline;
    const dirtyChanged = nextDirty !== boardFormDirty;
    boardFormDirty = nextDirty;
    updateBoardPreviewHint();

    if (dirtyChanged && boardFormDirty && fromInput) {
        const previewResult = document.getElementById('board-preview-result');
        if (previewResult?.style.display !== 'none') {
            hideBoardPreviewResult();
            setBoardFormFeedback('info', '你已修改配置，上一份试运行结果已失效。重新试运行即可验证当前表单。');
        }
    }

    return boardFormDirty;
}

function splitBoardLines(raw) {
    return String(raw || '')
        .split('\n')
        .map((value) => value.trim())
        .filter(Boolean);
}

function splitBoardNotifyChannels(raw) {
    return String(raw || '')
        .split(/[,\n，]/)
        .map((value) => value.trim())
        .filter(Boolean);
}

function parseBoardJson(raw, label) {
    const trimmed = String(raw || '').trim();
    if (!trimmed) {
        return { ok: true, value: null };
    }
    try {
        return { ok: true, value: JSON.parse(trimmed) };
    } catch {
        return { ok: false, error: `${label} JSON 格式不正确，请先修正。` };
    }
}

function parseBoardGithubRepos(raw) {
    const repos = [];
    const invalidLines = [];
    splitBoardLines(raw).forEach((line) => {
        const parts = line.split('/').map((value) => value.trim());
        if (parts.length !== 2 || !parts[0] || !parts[1]) {
            invalidLines.push(line);
            return;
        }
        repos.push({ owner: parts[0], repo: parts[1] });
    });
    return { repos, invalidLines };
}

function parseBoardRedditSubreddits(raw) {
    return splitBoardLines(raw).map((line) => {
        const parts = line.split(/\s+/);
        if (!parts[0]) return null;
        return {
            subreddit: parts[0],
            sort: parts[1] || 'hot',
            min_score: parseInt(parts[2], 10) || 10,
        };
    }).filter(Boolean);
}

function mergeBoardSummaryState(current, next) {
    const rank = { ready: 0, attention: 1, invalid: 2 };
    return (rank[next] || 0) > (rank[current] || 0) ? next : current;
}

function buildBoardFormPayload({ forPreview = false } = {}) {
    const isEdit = document.getElementById('board-is-edit').value === 'true';
    const originalSlug = document.getElementById('board-original-slug').value.trim();

    const slugRaw = document.getElementById('board-slug').value.trim();
    const nameRaw = document.getElementById('board-name').value.trim();
    const iconRaw = document.getElementById('board-icon').value.trim();
    const sourceType = document.getElementById('board-source-type').value;
    const prompt = document.getElementById('board-prompt').value.trim();
    const promptKey = document.getElementById('board-prompt-key').value;
    const schedule = document.getElementById('board-schedule').value.trim();
    const notifyChannels = document.getElementById('board-notify').value.trim();

    if (slugRaw && !/^[a-z0-9_-]+$/.test(slugRaw)) {
        setBoardFormFeedback('error', '标识符只允许小写字母、数字、下划线和横线。');
        document.getElementById('board-slug')?.focus();
        return null;
    }

    let perspectives = null;
    const perspectivesRaw = document.getElementById('board-perspectives').value.trim();
    if (perspectivesRaw) {
        const parsed = parseBoardJson(perspectivesRaw, '多视角配置');
        if (!parsed.ok) {
            openBoardAdvancedSettings();
            setBoardFormFeedback('error', parsed.error);
            document.getElementById('board-perspectives')?.focus();
            return null;
        }
        perspectives = parsed.value;
    }

    const sourceConfig = _collectSourceConfig(sourceType);
    if (sourceConfig === null) return null;

    const placeholderFields = [];
    const slug = slugRaw || (forPreview ? (originalSlug || 'preview-board') : slugRaw);
    const name = nameRaw || (forPreview ? '预览板块' : nameRaw);
    const icon = iconRaw || '❖';

    if (forPreview) {
        if (!slugRaw) placeholderFields.push('标识符');
        if (!nameRaw) placeholderFields.push('显示名称');
    }

    const outputLanguage = getBoardFieldValue('board-output-language', 'auto').trim();

    const payload = {
        slug,
        name,
        icon,
        source_type: sourceType,
        system_prompt: prompt || null,
        source_config: sourceConfig,
        prompt_key: promptKey,
        output_language: outputLanguage,
        schedule,
        notify_channels: notifyChannels,
        perspectives,
    };

    if (forPreview) {
        payload.original_slug = isEdit ? originalSlug : null;
        payload.perspective = 'overview';
    }

    return {
        isEdit,
        originalSlug,
        payload,
        meta: {
            placeholderFields,
        }
    };
}

function setBoardButtonBusyState(button, isBusy, busyText) {
    if (!button) return;
    if (!button.dataset.defaultText) {
        button.dataset.defaultText = button.textContent;
    }
    button.disabled = isBusy;
    button.textContent = isBusy ? busyText : button.dataset.defaultText;
}

function setBoardActionState({ saving = false, deleting = false, previewing = false } = {}) {
    const saveBtn = document.getElementById('board-save-btn');
    const previewBtn = document.getElementById('board-preview-btn');
    const deleteBtn = document.getElementById('board-delete-btn');

    setBoardButtonBusyState(saveBtn, saving, '保存中...');
    setBoardButtonBusyState(previewBtn, previewing, '运行中...');
    setBoardButtonBusyState(deleteBtn, deleting, '删除中...');

    if (previewBtn) previewBtn.disabled = saving || deleting || previewing;
    if (deleteBtn) deleteBtn.disabled = saving || deleting || previewing;
    if (saveBtn) saveBtn.disabled = saving || deleting || previewing;
}

function applyBoardRecordToForm(board) {
    if (!board) return;
    document.getElementById('board-slug').value = board.slug || '';
    document.getElementById('board-name').value = board.name || '';
    document.getElementById('board-icon').value = board.icon || '❖';
    document.getElementById('board-source-type').value = board.source_type || 'rss';
    document.getElementById('board-prompt').value = board.system_prompt || '';
    document.getElementById('board-prompt-key').value = board.prompt_key || 'daily_briefing';
    document.getElementById('board-output-language').value = board.output_language || 'auto';
    document.getElementById('board-schedule').value = board.schedule || '';
    document.getElementById('board-notify').value = board.notify_channels || '';

    const perspectives = board.perspectives || {};
    document.getElementById('board-perspectives').value = Object.keys(perspectives).length > 0
        ? JSON.stringify(perspectives)
        : '';

    _populateSourceConfigForm(board.source_type, board.source_config || {});
    toggleBoardSourceConfig();
}

function setBoardModalToEditState(board) {
    const title = document.getElementById('board-modal-title');
    const isEditInput = document.getElementById('board-is-edit');
    const originalSlugInput = document.getElementById('board-original-slug');
    const deleteBtn = document.getElementById('board-delete-btn');
    const previewBtn = document.getElementById('board-preview-btn');
    const modeTabs = document.getElementById('board-mode-tabs');

    title.textContent = '设置板块';
    isEditInput.value = 'true';
    originalSlugInput.value = board?.slug || '';
    document.getElementById('board-slug').disabled = true;

    if (previewBtn) previewBtn.style.display = 'inline-block';
    if (deleteBtn) {
        deleteBtn.style.display = board?.is_default ? 'none' : 'inline-block';
    }
    if (modeTabs) modeTabs.style.display = 'none';

    switchBoardMode('manual');
}

function renderBoardConfigSummary() {
    const container = document.getElementById('board-config-summary');
    const sourceType = document.getElementById('board-source-type');
    if (!container || !sourceType) return;

    const type = sourceType.value || 'rss';
    const typeMeta = BOARD_SOURCE_TYPE_META[type] || { label: type };
    const isEdit = document.getElementById('board-is-edit')?.value === 'true';
    const checklist = [];
    const notes = [];
    let state = 'ready';
    let headline = '';

    const promptRaw = document.getElementById('board-prompt')?.value.trim() || '';
    const scheduleRaw = document.getElementById('board-schedule')?.value.trim() || '';
    const notifyChannels = splitBoardNotifyChannels(document.getElementById('board-notify')?.value || '');
    const perspectivesRaw = document.getElementById('board-perspectives')?.value || '';
    const perspectivesParsed = parseBoardJson(perspectivesRaw, '多视角配置');

    switch (type) {
        case 'rss': {
            const feeds = splitBoardLines(document.getElementById('board-rss-feeds')?.value || '');
            if (feeds.length === 0) {
                state = 'attention';
                headline = '还没有填写 RSS 地址。';
                checklist.push('至少填写 1 个订阅地址，每行一个。');
            } else {
                headline = `已配置 ${feeds.length} 个 RSS 源。`;
                checklist.push(`优先抓取：${feeds.slice(0, 2).join('、')}${feeds.length > 2 ? ' 等' : ''}`);
            }
            break;
        }
        case 'pure_llm': {
            const itemsRaw = document.getElementById('board-llm-items')?.value || '';
            const items = parseInt(itemsRaw, 10);
            const style = document.getElementById('board-llm-style')?.value.trim() || '';
            if (!Number.isFinite(items) || items < 1 || items > 15) {
                state = 'invalid';
                headline = '每日生成条数需要在 1 到 15 之间。';
            } else {
                headline = `每天生成 ${items} 条内容${style ? `，风格偏向“${style}”` : ''}。`;
                checklist.push(style ? '已提供风格描述，生成方向更稳定。' : '风格描述可选，留空会使用默认语气。');
            }
            break;
        }
        case 'hackernews': {
            const top = parseInt(document.getElementById('board-hn-top')?.value || '', 10);
            const score = parseInt(document.getElementById('board-hn-score')?.value || '', 10);
            if (!Number.isFinite(top) || top < 1 || top > 100 || !Number.isFinite(score) || score < 0) {
                state = 'invalid';
                headline = '热帖数量或最低分数超出允许范围。';
            } else {
                headline = `将抓取前 ${top} 条热帖，过滤掉低于 ${score} 分的内容。`;
                checklist.push('适合追踪高热度技术话题与讨论。');
            }
            break;
        }
        case 'reddit': {
            const subreddits = parseBoardRedditSubreddits(document.getElementById('board-reddit-subs')?.value || '');
            const comments = parseInt(document.getElementById('board-reddit-comments')?.value || '', 10);
            if (subreddits.length === 0) {
                state = 'attention';
                headline = '还没有填写 subreddit。';
                checklist.push('至少填写 1 行 subreddit，例如 LocalLLaMA hot 50。');
            } else {
                headline = `已配置 ${subreddits.length} 个 subreddit，每帖抓取 ${Number.isFinite(comments) ? comments : 0} 条评论。`;
                checklist.push(`当前包含：${subreddits.slice(0, 3).map((item) => item.subreddit).join('、')}${subreddits.length > 3 ? ' 等' : ''}`);
            }
            break;
        }
        case 'github': {
            const { repos, invalidLines } = parseBoardGithubRepos(document.getElementById('board-github-repos')?.value || '');
            const users = splitBoardLines(document.getElementById('board-github-users')?.value || '');
            const trackedCount = repos.length + users.length;
            if (trackedCount === 0) {
                state = 'attention';
                headline = '还没有填写需要追踪的仓库或用户。';
                checklist.push('至少填写 1 个仓库或 GitHub 用户名。');
            } else {
                headline = `已追踪 ${repos.length} 个仓库、${users.length} 个用户。`;
                if (repos.length > 0) {
                    checklist.push(`仓库示例：${repos.slice(0, 2).map((repo) => `${repo.owner}/${repo.repo}`).join('、')}${repos.length > 2 ? ' 等' : ''}`);
                }
                if (users.length > 0) {
                    checklist.push(`用户示例：${users.slice(0, 3).join('、')}${users.length > 3 ? ' 等' : ''}`);
                }
            }
            if (invalidLines.length > 0) {
                state = mergeBoardSummaryState(state, 'attention');
                checklist.push(`有 ${invalidLines.length} 行仓库地址格式不正确，保存时会被忽略。`);
            }
            break;
        }
        case 'multi': {
            const multiRaw = document.getElementById('board-multi-json')?.value || '';
            const parsed = parseBoardJson(multiRaw, '混合数据源配置');
            if (!multiRaw.trim()) {
                state = 'attention';
                headline = '还没有填写混合数据源 JSON。';
                checklist.push('请按 JSON 结构配置各个子数据源。');
            } else if (!parsed.ok) {
                state = 'invalid';
                headline = '混合数据源 JSON 目前无法解析。';
                checklist.push(parsed.error);
            } else {
                const sources = parsed.value && typeof parsed.value === 'object' ? Object.keys(parsed.value) : [];
                headline = `已配置 ${sources.length} 个子数据源。`;
                checklist.push(`当前子源：${sources.join('、') || '暂无'}`);
            }
            break;
        }
        default:
            headline = '请继续完善当前板块配置。';
    }

    if (promptRaw) {
        checklist.push(`已覆盖默认系统提示词（${promptRaw.length} 字）。`);
    }
    if (scheduleRaw) {
        checklist.push(`已设置单独调度：${scheduleRaw}。`);
    }
    const outputLang = document.getElementById('board-output-language')?.value || 'auto';
    if (outputLang !== 'auto') {
        const langLabel = outputLang === 'zh' ? '中文' : outputLang === 'en' ? 'English' : outputLang;
        checklist.push(`输出语言：${langLabel}。`);
    }
    if (notifyChannels.length > 0) {
        checklist.push(`通知渠道：${notifyChannels.join('、')}。`);
    }
    if (perspectivesRaw.trim()) {
        if (!perspectivesParsed.ok) {
            state = mergeBoardSummaryState(state, 'invalid');
            checklist.push(perspectivesParsed.error);
        } else {
            const activePerspectives = perspectivesParsed.value?.active;
            const count = Array.isArray(activePerspectives) ? activePerspectives.length : Object.keys(perspectivesParsed.value || {}).length;
            checklist.push(`已配置多视角：${count} 项。`);
        }
    }

    if (boardHasSavedVersion) {
        notes.push(boardFormDirty ? '当前有未保存修改，可以直接试运行这份表单，但结果不会自动保存。' : '当前配置已保存，也可以继续试运行当前表单验证效果。');
    } else {
        notes.push('未保存时也可以直接试运行当前表单；确认效果后再保存即可。');
    }
    notes.push('如果摘要状态显示“需修正”，先处理 JSON 或数量字段，再执行保存。');

    const badgeMap = {
        ready: '已就绪',
        attention: '待补充',
        invalid: '需修正'
    };

    container.className = `board-config-summary board-config-summary--${state}`;
    container.innerHTML = `
        <div class="board-config-summary__top">
            <span class="board-config-summary__title">${escapeHtml(typeMeta.label)}</span>
            <span class="board-config-summary__badge">${badgeMap[state] || badgeMap.ready}</span>
        </div>
        <p class="board-config-summary__headline">${escapeHtml(headline || '请继续完善当前板块配置。')}</p>
        ${checklist.length > 0 ? `<ul class="board-config-summary__list">${checklist.map((item) => `<li>${escapeHtml(item)}</li>`).join('')}</ul>` : ''}
        <p class="board-config-summary__note">${escapeHtml(notes.join(' '))}</p>
    `;
}

function switchBoardMode(mode) {
    // Toggle active tab
    document.querySelectorAll('#board-mode-tabs .board-mode-tab').forEach(btn => {
        btn.classList.toggle('active', btn.dataset.mode === mode);
    });
    const wizardPanel = document.getElementById('board-wizard-panel');
    const form = document.getElementById('board-form');
    if (mode === 'wizard') {
        wizardPanel.style.display = 'block';
        form.style.display = 'none';
    } else {
        wizardPanel.style.display = 'none';
        form.style.display = 'block';
        renderBoardConfigSummary();
    }
}

function resetWizard() {
    wizardMessages = [];
    wizardLastConfig = null;
    wizardIsLoading = false;
    wizardTopic = '';
    wizardBrokenFeeds = new Set();
    const messagesDiv = document.getElementById('wizard-messages');
    if (messagesDiv) {
        messagesDiv.innerHTML = `<div class="wizard-msg wizard-msg--ai">告诉我你想要一个什么样的板块，比如：<br>"我想每天学 5 个英语商务单词"，<br>"汇总国内外顶级 AI 实验室的最新论文"，<br>"每天给我一条冷门心理学知识"...</div>`;
    }
    const applyRow = document.getElementById('wizard-apply-row');
    if (applyRow) applyRow.style.display = 'none';
    const input = document.getElementById('wizard-input');
    if (input) { input.value = ''; input.disabled = false; }
    const btn = document.getElementById('wizard-submit-btn');
    if (btn) { btn.disabled = false; btn.textContent = '发送'; }
}

function appendWizardMsg(role, content) {
    const container = document.getElementById('wizard-messages');
    const div = document.createElement('div');
    div.className = `wizard-msg wizard-msg--${role}`;
    if (role === 'ai' && typeof marked !== 'undefined') {
        div.innerHTML = marked.parse(content);
    } else {
        div.textContent = content;
    }
    container.appendChild(div);
    container.scrollTop = container.scrollHeight;
    return div;
}

async function submitWizard(event) {
    event.preventDefault();
    if (wizardIsLoading) return;
    const input = document.getElementById('wizard-input');
    const text = input.value.trim();
    if (!text) return;

    // Append user message
    appendWizardMsg('user', text);
    wizardMessages.push({ role: 'user', content: text });
    input.value = '';

    // Loading state
    wizardIsLoading = true;
    const btn = document.getElementById('wizard-submit-btn');
    btn.disabled = true;
    btn.textContent = '思考中...';
    const loadingMsg = appendWizardMsg('ai', '🧠 正在为你设计板块...');

    try {
        const res = await fetch('/api/v1/boards/wizard', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ messages: wizardMessages }),
        });
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        const data = await res.json();

        // Remove loading placeholder
        loadingMsg.remove();

        // Show AI reply
        appendWizardMsg('ai', data.reply || '（无回复）');
        wizardMessages.push({ role: 'assistant', content: data.reply || '' });

        if (data.ready && data.config) {
            wizardLastConfig = data.config;
            // Derive a topic string for later feed-fix requests.
            wizardTopic = `${data.config.name || ''} ${data.config.system_prompt || ''}`.trim();
            // Summary preview
            const cfg = data.config;
            const typeLabels = { rss: 'RSS 订阅源', pure_llm: '纯 LLM 生成', hackernews: 'Hacker News', reddit: 'Reddit', github: 'GitHub', multi: '混合数据源' };
            const sc = cfg.source_config || {};
            const isRss = cfg.source_type === 'rss' && Array.isArray(sc.feeds) && sc.feeds.length > 0;
            let sourceDetail = '';
            if (cfg.source_type === 'reddit' && sc.subreddits) {
                sourceDetail = `- Subreddits: ${sc.subreddits.map(s => s.subreddit || s).join(', ')}`;
            } else if (cfg.source_type === 'github') {
                const parts = [];
                if (sc.repos) parts.push(`repos: ${sc.repos.map(r => r.owner + '/' + r.repo).join(', ')}`);
                if (sc.users) parts.push(`users: ${sc.users.join(', ')}`);
                if (parts.length) sourceDetail = `- ${parts.join('; ')}`;
            }
            const preview = `**推荐配置：**
- 名称：${cfg.icon} ${cfg.name}
- 标识：\`${cfg.slug}\`
- 类型：${typeLabels[cfg.source_type] || cfg.source_type}
${sourceDetail}`;
            appendWizardMsg('ai', preview);

            // RSS feeds: render per-URL validation status and auto-fix broken ones.
            if (isRss) {
                const validation = Array.isArray(data.feed_validation) ? data.feed_validation : null;
                renderWizardFeedStatus(sc.feeds, validation);
                if (validation && validation.some(v => !v.ok)) {
                    const broken = validation.filter(v => !v.ok).map(v => v.url);
                    fixWizardFeeds(broken);
                }
            }
            document.getElementById('wizard-apply-row').style.display = 'flex';
        } else {
            wizardLastConfig = null;
            document.getElementById('wizard-apply-row').style.display = 'none';
        }
    } catch (e) {
        loadingMsg.remove();
        appendWizardMsg('ai', `❌ 出错了：${e.message}`);
    } finally {
        wizardIsLoading = false;
        btn.disabled = false;
        btn.textContent = '发送';
        input.focus();
    }
}

function renderWizardFeedStatus(feeds, validation) {
    const container = document.getElementById('wizard-messages');
    const byUrl = {};
    (validation || []).forEach(v => { byUrl[v.url] = v; });

    // Track broken feeds so applyWizardConfig can drop unresolved ones.
    wizardBrokenFeeds = new Set(
        (validation || []).filter(v => !v.ok).map(v => v.url)
    );

    const card = document.createElement('div');
    card.className = 'wizard-msg wizard-msg--ai wizard-feed-status';
    const title = document.createElement('div');
    title.className = 'wizard-feed-title';
    title.textContent = 'RSS 源检测结果';
    card.appendChild(title);

    feeds.forEach(url => {
        const v = byUrl[url];
        const row = document.createElement('div');
        let state = 'pending', icon = '…', meta = '检测中';
        if (v && v.ok) { state = 'ok'; icon = '✓'; meta = `${v.article_count}篇`; }
        else if (v) { state = 'fail'; icon = '✗'; meta = v.error || '失败'; }
        row.className = `wizard-feed-row wizard-feed-row--${state}`;
        const iconEl = document.createElement('span');
        iconEl.className = 'wizard-feed-icon';
        iconEl.textContent = icon;
        const urlEl = document.createElement('span');
        urlEl.className = 'wizard-feed-url';
        urlEl.textContent = url;
        const metaEl = document.createElement('span');
        metaEl.className = 'wizard-feed-meta';
        metaEl.textContent = meta;
        row.append(iconEl, urlEl, metaEl);
        card.appendChild(row);
    });
    container.appendChild(card);
    container.scrollTop = container.scrollHeight;
    return card;
}

async function fixWizardFeeds(brokenUrls) {
    const loading = appendWizardMsg('ai', `🔧 正在为 ${brokenUrls.length} 个失效源寻找可用替代...`);
    try {
        const res = await fetch('/api/v1/boards/wizard/fix-feeds', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ topic: wizardTopic || '通用资讯', broken_urls: brokenUrls }),
        });
        loading.remove();
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        const data = await res.json();
        renderWizardAlternatives(Array.isArray(data.alternatives) ? data.alternatives : []);
    } catch (e) {
        loading.remove();
        appendWizardMsg('ai', `⚠️ 替代源获取失败：${e.message}。你可以稍后在「信息源管理」里手动调整。`);
    }
}

function renderWizardAlternatives(alternatives) {
    const container = document.getElementById('wizard-messages');
    const hasAny = alternatives.some(a => (a.suggestions || []).some(s => s.ok));
    if (!hasAny) {
        appendWizardMsg('ai', '未能找到可用的替代源，失效源在应用时会被自动移除，你可稍后手动补充。');
        return;
    }

    alternatives.forEach(alt => {
        const usable = (alt.suggestions || []).filter(s => s.ok);
        if (usable.length === 0) return;

        const card = document.createElement('div');
        card.className = 'wizard-msg wizard-msg--ai wizard-alt-card';
        const head = document.createElement('div');
        head.className = 'wizard-alt-head';
        const orig = document.createElement('span');
        orig.className = 'wizard-alt-original';
        orig.textContent = alt.original;
        head.append(document.createTextNode('❌ '), orig, document.createTextNode(' 的替代建议：'));
        card.appendChild(head);

        usable.forEach(s => {
            const row = document.createElement('div');
            row.className = 'wizard-alt-row';
            const info = document.createElement('span');
            info.className = 'wizard-alt-info';
            info.textContent = `✓ ${s.url} (${s.article_count}篇)`;
            const btn = document.createElement('button');
            btn.className = 'wizard-alt-accept-btn';
            btn.textContent = '采用';
            btn.addEventListener('click', () => acceptWizardAlternative(alt.original, s.url, row, card));
            row.append(info, btn);
            card.appendChild(row);
        });
        container.appendChild(card);
    });
    container.scrollTop = container.scrollHeight;
}

function acceptWizardAlternative(originalUrl, newUrl, rowEl, cardEl) {
    if (!wizardLastConfig || !wizardLastConfig.source_config) return;
    const feeds = wizardLastConfig.source_config.feeds || [];
    const idx = feeds.indexOf(originalUrl);
    if (idx !== -1) {
        feeds[idx] = newUrl;
    } else if (!feeds.includes(newUrl)) {
        feeds.push(newUrl);
    }
    wizardLastConfig.source_config.feeds = feeds;
    // This original is now resolved — remove it from the broken set.
    wizardBrokenFeeds.delete(originalUrl);

    // Lock this card's buttons and mark accepted row.
    cardEl.querySelectorAll('.wizard-alt-accept-btn').forEach(b => { b.disabled = true; });
    rowEl.classList.add('wizard-alt-row--accepted');
    const tag = document.createElement('span');
    tag.className = 'wizard-alt-accepted-tag';
    tag.textContent = '已采用';
    rowEl.appendChild(tag);
}

function applyWizardConfig() {
    if (!wizardLastConfig) return;
    const cfg = wizardLastConfig;
    // Drop any RSS feeds still known to be broken and not replaced.
    if (cfg.source_type === 'rss' && cfg.source_config && Array.isArray(cfg.source_config.feeds) && wizardBrokenFeeds.size) {
        cfg.source_config.feeds = cfg.source_config.feeds.filter(u => !wizardBrokenFeeds.has(u));
    }
    document.getElementById('board-slug').value = cfg.slug || '';
    document.getElementById('board-slug').disabled = false;
    document.getElementById('board-name').value = cfg.name || '';
    document.getElementById('board-icon').value = cfg.icon || '❖';
    document.getElementById('board-source-type').value = cfg.source_type || 'rss';
    document.getElementById('board-prompt').value = cfg.system_prompt || '';
    
    if (cfg.schedule) document.getElementById('board-schedule').value = cfg.schedule;
    if (cfg.notify_channels) document.getElementById('board-notify').value = cfg.notify_channels;
    
    _populateSourceConfigForm(cfg.source_type, cfg.source_config || {});
    toggleBoardSourceConfig();
    switchBoardMode('manual');
    syncBoardFormState();
    renderBoardConfigSummary();
    setBoardFormFeedback('info', 'AI 推荐配置已经填入表单，你可以继续微调后再保存。');
}

function _populateSourceConfigForm(sourceType, sc) {
    // Reset all config fields
    const feedsEl = document.getElementById('board-rss-feeds');
    if (feedsEl) feedsEl.value = '';
    const llmItems = document.getElementById('board-llm-items');
    if (llmItems) llmItems.value = '5';
    const llmStyle = document.getElementById('board-llm-style');
    if (llmStyle) llmStyle.value = '';
    const hnTop = document.getElementById('board-hn-top');
    if (hnTop) hnTop.value = '30';
    const hnScore = document.getElementById('board-hn-score');
    if (hnScore) hnScore.value = '100';
    const redditSubs = document.getElementById('board-reddit-subs');
    if (redditSubs) redditSubs.value = '';
    const redditComments = document.getElementById('board-reddit-comments');
    if (redditComments) redditComments.value = '5';
    const ghRepos = document.getElementById('board-github-repos');
    if (ghRepos) ghRepos.value = '';
    const ghUsers = document.getElementById('board-github-users');
    if (ghUsers) ghUsers.value = '';
    const multiJson = document.getElementById('board-multi-json');
    if (multiJson) multiJson.value = '';

    if (!sc) return;

    switch (sourceType) {
        case 'rss':
            if (sc.feeds && feedsEl) feedsEl.value = sc.feeds.join('\n');
            break;
        case 'pure_llm':
            if (sc.items_per_day && llmItems) llmItems.value = sc.items_per_day;
            if (sc.style && llmStyle) llmStyle.value = sc.style;
            break;
        case 'hackernews':
            if (sc.fetch_top_stories && hnTop) hnTop.value = sc.fetch_top_stories;
            if (sc.min_score !== undefined && hnScore) hnScore.value = sc.min_score;
            break;
        case 'reddit':
            if (sc.subreddits && redditSubs) {
                redditSubs.value = sc.subreddits.map(s => {
                    const parts = [s.subreddit || s];
                    if (s.sort) parts.push(s.sort);
                    if (s.min_score) parts.push(s.min_score);
                    return parts.join(' ');
                }).join('\n');
            }
            if (sc.fetch_comments !== undefined && redditComments) redditComments.value = sc.fetch_comments;
            break;
        case 'github':
            if (sc.repos && ghRepos) ghRepos.value = sc.repos.map(r => `${r.owner}/${r.repo}`).join('\n');
            if (sc.users && ghUsers) ghUsers.value = sc.users.join('\n');
            break;
        case 'multi':
            if (multiJson) multiJson.value = JSON.stringify(sc.sources || sc, null, 2);
            break;
    }
}

function openBoardModal(slug = null) {
    const modal = document.getElementById('board-modal');
    if (!modal) return;
    const title = document.getElementById('board-modal-title');
    const isEditInput = document.getElementById('board-is-edit');
    const deleteBtn = document.getElementById('board-delete-btn');
    const previewBtn = document.getElementById('board-preview-btn');
    const originalSlugInput = document.getElementById('board-original-slug');
    const modeTabs = document.getElementById('board-mode-tabs');
    
    // reset form and wizard state
    document.getElementById('board-form').reset();
    document.getElementById('board-advanced-settings').style.display = 'none';
    clearBoardFormFeedback();
    hideBoardPreviewResult();
    setBoardActionState();
    const toggleBtn = document.querySelector('.section-toggle-btn');
    if (toggleBtn) toggleBtn.classList.remove('open');
    resetWizard();

    if (slug) {
        const b = availableBoards.find(x => x.slug === slug);
        if (b) {
            setBoardModalToEditState(b);
            applyBoardRecordToForm(b);
            resetBoardFormState({ hasSavedVersion: true });
        } else {
            title.textContent = '设置板块';
            isEditInput.value = 'true';
            originalSlugInput.value = slug;
            deleteBtn.style.display = 'inline-block';
            previewBtn.style.display = 'inline-block';
            modeTabs.style.display = 'none';
            switchBoardMode('manual');
            resetBoardFormState({ hasSavedVersion: true });
        }
    } else {
        // Add mode - start with wizard
        title.textContent = '新建板块';
        isEditInput.value = 'false';
        originalSlugInput.value = '';
        deleteBtn.style.display = 'none';
        previewBtn.style.display = 'inline-block';
        modeTabs.style.display = 'flex';
        document.getElementById('board-slug').disabled = false;
        document.getElementById('board-source-type').value = 'rss';
        toggleBoardSourceConfig();
        switchBoardMode('wizard');
        resetBoardFormState({ hasSavedVersion: false });
    }
    
    renderBoardConfigSummary();
    openOverlay(modal, slug ? '#board-name' : '#wizard-input');
}

function closeBoardModal() {
    const modal = document.getElementById('board-modal');
    clearBoardFormFeedback();
    hideBoardPreviewResult();
    setBoardActionState();
    closeOverlay(modal);
}

function toggleBoardSourceConfig() {
    const type = document.getElementById('board-source-type').value;
    document.querySelectorAll('.board-source-config').forEach(el => {
        el.style.display = 'none';
    });
    const panel = document.getElementById('board-cfg-' + type);
    if (panel) panel.style.display = 'block';
    renderBoardConfigSummary();
}

function hideBoardPreviewResult() {
    const previewResult = document.getElementById('board-preview-result');
    const previewContent = document.getElementById('board-preview-content');
    if (previewResult) previewResult.style.display = 'none';
    if (previewContent) previewContent.innerHTML = '';
}

function setBoardPreviewLoading(message) {
    const previewResult = document.getElementById('board-preview-result');
    const previewContent = document.getElementById('board-preview-content');
    if (!previewResult || !previewContent) return;
    previewResult.style.display = 'block';
    previewContent.innerHTML = `<p class="board-preview-empty">${escapeHtml(message)}</p>`;
}

function renderBoardPreviewResult(data) {
    const previewResult = document.getElementById('board-preview-result');
    const previewContent = document.getElementById('board-preview-content');
    if (!previewResult || !previewContent) return;

    const overview = data?.overview ? renderMarkdownSafe(data.overview) : '<p class="board-preview-empty">暂未返回总览文本。</p>';
    const statsEntries = Object.entries(data?.source_stats || {});
    const topNews = Array.isArray(data?.top_news) ? data.top_news : [];

    const statsHtml = statsEntries.length > 0
        ? statsEntries.map(([label, value]) => `
            <div class="board-preview-stat">
                <span class="board-preview-stat__label">${escapeHtml(label)}</span>
                <span class="board-preview-stat__value">${escapeHtml(value)}</span>
            </div>
        `).join('')
        : '<p class="board-preview-empty">暂无抓取统计。</p>';

    const itemsHtml = topNews.length > 0
        ? topNews.map((item, index) => {
            const headline = item?.headline || `未命名内容 ${index + 1}`;
            const category = item?.category || 'general';
            const source = item?.source || 'unknown';
            const points = Array.isArray(item?.key_points) ? item.key_points.filter(Boolean) : [];
            const tags = Array.isArray(item?.tags) ? item.tags.filter(Boolean) : [];
            const link = item?.original_link || '';
            const safeLink = isSafeHttpUrlString(link) ? link : '';

            return `
                <article class="board-preview-item">
                    <div class="board-preview-item__head">
                        <div>
                            <h5 class="board-preview-item__title">${index + 1}. ${escapeHtml(headline)}</h5>
                        </div>
                        <div class="board-preview-item__meta">
                            <span class="board-preview-pill">${escapeHtml(category)}</span>
                            <span class="board-preview-pill">${escapeHtml(source)}</span>
                            ${tags.slice(0, 3).map((tag) => `<span class="board-preview-pill">#${escapeHtml(tag)}</span>`).join('')}
                        </div>
                    </div>
                    ${points.length > 0 ? `<ul class="board-preview-item__points">${points.map((point) => `<li>${escapeHtml(point)}</li>`).join('')}</ul>` : '<p class="board-preview-empty">这条内容没有返回要点摘要。</p>'}
                    <div class="board-preview-item__footer">
                        <span class="board-preview-empty">来源链接</span>
                        ${safeLink ? `<a class="board-preview-link" href="${escapeHtml(safeLink)}" target="_blank" rel="noopener noreferrer">打开原文</a>` : '<span class="board-preview-empty">无可用链接</span>'}
                    </div>
                </article>
            `;
        }).join('')
        : '<p class="board-preview-empty">本次试运行没有返回推荐内容。</p>';

    previewResult.style.display = 'block';
    previewContent.innerHTML = `
        <section class="board-preview-section">
            <div class="board-preview-section__title">总览</div>
            <div class="board-preview-overview">${overview}</div>
        </section>
        <section class="board-preview-section">
            <div class="board-preview-section__title">抓取统计</div>
            <div class="board-preview-stats">${statsHtml}</div>
        </section>
        <section class="board-preview-section">
            <div class="board-preview-section__title">内容列表 ${topNews.length > 0 ? `(${topNews.length})` : ''}</div>
            <div class="board-preview-items">${itemsHtml}</div>
        </section>
    `;
}

async function readResponseError(response, fallback = '请求失败') {
    try {
        const data = await response.json();
        return data?.detail || data?.message || fallback;
    } catch {
        return fallback;
    }
}

function _collectSourceConfig(sourceType, { silent = false } = {}) {
    switch (sourceType) {
        case 'rss': {
            return { feeds: splitBoardLines(document.getElementById('board-rss-feeds').value) };
        }
        case 'pure_llm': {
            const items = parseInt(document.getElementById('board-llm-items').value) || 5;
            const style = document.getElementById('board-llm-style').value.trim();
            return { items_per_day: items, style };
        }
        case 'hackernews': {
            const top = parseInt(document.getElementById('board-hn-top').value) || 30;
            const score = parseInt(document.getElementById('board-hn-score').value) || 0;
            return { fetch_top_stories: top, min_score: score };
        }
        case 'reddit': {
            const subreddits = parseBoardRedditSubreddits(document.getElementById('board-reddit-subs').value);
            const comments = parseInt(document.getElementById('board-reddit-comments').value) || 5;
            return { subreddits, fetch_comments: comments };
        }
        case 'github': {
            const { repos } = parseBoardGithubRepos(document.getElementById('board-github-repos').value);
            const users = splitBoardLines(document.getElementById('board-github-users').value);
            return { repos, users };
        }
        case 'multi': {
            const raw = document.getElementById('board-multi-json').value.trim();
            const parsed = parseBoardJson(raw, '混合数据源配置');
            if (!parsed.ok) {
                if (!silent) {
                    setBoardFormFeedback('error', parsed.error);
                    document.getElementById('board-multi-json')?.focus();
                }
                return null;
            }
            return { sources: parsed.value || {} };
        }
        default:
            return {};
    }
}

async function saveBoard(event) {
    event.preventDefault();
    clearBoardFormFeedback();
    setBoardActionState({ saving: true });
    const built = buildBoardFormPayload();
    if (!built) {
        setBoardActionState();
        return;
    }
    const { isEdit, originalSlug, payload } = built;
    
    try {
        const url = isEdit ? `/api/v1/boards/${originalSlug}` : '/api/v1/boards';
        const method = isEdit ? 'PATCH' : 'POST';
        
        const res = await fetch(url, {
            method: method,
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload)
        });
        
        if (!res.ok) {
            throw new Error(await readResponseError(res, '保存失败'));
        }

        const savedBoard = await res.json();
        hideBoardPreviewResult();
        if (!isEdit) {
            currentBoardSlug = savedBoard.slug; // Switch to new board
            localStorage.setItem('argos_board', savedBoard.slug);
        }
        await initBoards();
        if (!isEdit) {
            fetchSummary();
        }

        setBoardModalToEditState(savedBoard);
        applyBoardRecordToForm(savedBoard);
        resetBoardFormState({ hasSavedVersion: true });
        renderBoardConfigSummary();
        setBoardFormFeedback(
            'success',
            isEdit
                ? '板块配置已保存。你可以继续微调，也可以直接试运行当前表单。'
                : '板块已创建并保存。现在可以继续微调，或直接试运行当前表单。'
        );
    } catch (e) {
        setBoardFormFeedback('error', `保存板块出错：${e.message}`);
    } finally {
        setBoardActionState();
    }
}

async function deleteBoard() {
    const slug = document.getElementById('board-original-slug').value;
    if (!confirm('确定要删除此板块吗？归档记录也会一起清理。')) return;
    clearBoardFormFeedback();
    setBoardActionState({ deleting: true });
    
    try {
        const res = await fetch(`/api/v1/boards/${slug}`, {
            method: 'DELETE'
        });
        if (!res.ok) {
            throw new Error(await readResponseError(res, '删除失败'));
        }
        
        closeBoardModal();
        currentBoardSlug = null;
        localStorage.removeItem('argos_board');
        await initBoards();
        fetchSummary();
    } catch (e) {
        setBoardFormFeedback('error', `删除板块出错：${e.message}`);
    } finally {
        setBoardActionState();
    }
}

async function previewBoard() {
    clearBoardFormFeedback();
    const built = buildBoardFormPayload({ forPreview: true });
    if (!built) {
        return;
    }

    if (built.meta.placeholderFields.length > 0) {
        setBoardFormFeedback('info', `本次试运行会为 ${built.meta.placeholderFields.join('、')} 使用临时占位值，仅用于预览当前效果。`);
    }

    setBoardActionState({ previewing: true });
    setBoardPreviewLoading('正在执行抓取与 LLM 分析（基于当前表单配置）... 这可能需要几十秒。');
    
    try {
        const res = await fetch('/api/v1/boards/preview', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(built.payload)
        });
        if (!res.ok) {
            throw new Error(await readResponseError(res, '预览失败'));
        }
        const data = await res.json();
        renderBoardPreviewResult(data || {});
    } catch (e) {
        setBoardFormFeedback('error', `试运行失败：${e.message}`);
        setBoardPreviewLoading(`试运行失败：${e.message}`);
    } finally {
        setBoardActionState();
    }
}

async function fetchSummary(force = false, date = null) {
    let url = '/api/v1/summary';
    const params = [];
    if (force) params.push('force=true');
    if (date) params.push(`date=${encodeURIComponent(date)}`);
    if (currentBoardSlug) params.push(`board=${encodeURIComponent(currentBoardSlug)}`);
    
    if (params.length > 0) {
        url += '?' + params.join('&');
    }
    
    await fetchSummaryWithUrl(url);
}

function _loadCachedSummary() {
    try {
        const raw = sessionStorage.getItem(SUMMARY_CACHE_KEY + '_' + (currentBoardSlug || 'default'));
        if (!raw) return null;
        const cached = JSON.parse(raw);
        // Only use cache if it's from today
        const today = new Date().toISOString().slice(0, 10);
        if (cached.date !== today) return null;
        return cached;
    } catch { return null; }
}

function _saveCachedSummary(data) {
    try {
        sessionStorage.setItem(
            SUMMARY_CACHE_KEY + '_' + (currentBoardSlug || 'default'),
            JSON.stringify(data)
        );
    } catch { /* sessionStorage full, ignore */ }
}

function _clearCachedSummary() {
    try {
        sessionStorage.removeItem(SUMMARY_CACHE_KEY + '_' + (currentBoardSlug || 'default'));
    } catch { /* ignore */ }
}

function _renderSummaryData(data) {
    const loadingState = document.getElementById('loading-state');
    const contentState = document.getElementById('content-state');
    const dateHeader = document.getElementById('summary-date');
    const overviewText = document.getElementById('summary-overview');
    const refreshBtn = document.getElementById('refresh-btn');

    data.source_stats = data.source_stats || computeSourceStats(data.top_news || []);
    latestData = data;

    const dateObj = new Date(data.date);
    const options = { weekday: 'long', year: 'numeric', month: 'long', day: 'numeric' };
    dateHeader.textContent = dateObj.toLocaleDateString('zh-CN', options);
    overviewText.textContent = data.overview || '';

    renderHome();
    renderRecReport();
    fetchSystemMetrics();

    loadingState.style.display = 'none';
    contentState.style.display = 'block';
    if (refreshBtn) refreshBtn.style.display = 'inline-flex';
}

async function fetchSummaryWithUrl(url) {
    // Cancel any in-flight summary fetch (prevents stale board data flickering)
    if (_summaryAbortController) {
        _summaryAbortController.abort();
    }
    _summaryAbortController = new AbortController();
    const thisFetchId = ++_summaryFetchId;

    const loadingState = document.getElementById('loading-state');
    const contentState = document.getElementById('content-state');
    const refreshBtn = document.getElementById('refresh-btn');
    const hasCachedData = !!latestData;

    try {
        // Only show full loading spinner if we have NO cached data to show
        if (!hasCachedData) {
            showLoadingState();
            contentState.style.display = 'none';
            if (refreshBtn) refreshBtn.style.display = 'none';
        }

        const response = await fetch(url, { signal: _summaryAbortController.signal });
        if (!response.ok) {
            throw new Error(`HTTP ${response.status}`);
        }

        const data = await response.json();

        // Discard response if a newer fetch has been started (board switched)
        if (thisFetchId !== _summaryFetchId) return;

        _renderSummaryData(data);
        _saveCachedSummary(data);
    } catch (error) {
        if (error.name === 'AbortError') return; // cancelled by newer fetch — ignore
        console.error('Failed to fetch summary:', error);
        // Only show error state if this is still the latest fetch and we have no cached data
        if (thisFetchId === _summaryFetchId && !hasCachedData) {
            showErrorState(error.message, () => fetchSummary());
        }
    }
}

function renderHome() {
    const container = document.getElementById('news-container');
    const overviewSection = document.querySelector('.overview-section');
    const viewControls = document.getElementById('view-controls');

    if (!latestData) return;

    clearElement(container);
    container.className = 'news-grid dashboard';
    overviewSection.style.display = 'block';
    viewControls.style.display = 'none';

    renderSourceStats(latestData.source_stats || computeSourceStats(latestData.top_news));
    renderCategoryNav();

    (latestData.top_news || []).forEach((newsItem, index) => {
        container.appendChild(createNewsCard(newsItem, index));
    });

    window.scrollTo({ top: 0, behavior: 'smooth' });
}

function applyFeedbackState(likeButton, dislikeButton, sentiment) {
    if (!likeButton || !dislikeButton) return;
    likeButton.classList.toggle('active', sentiment === 1);
    dislikeButton.classList.toggle('active', sentiment === -1);
}

function updateFeedbackStateInData(url, sentiment) {
    if (!latestData || !Array.isArray(latestData.top_news)) return;
    const storedSentiment = sentiment === 1 || sentiment === -1 ? sentiment : null;

    for (const item of latestData.top_news) {
        if (item.original_link === url) {
            item.feedback_sentiment = storedSentiment;
        }
    }
}

function renderCategoryNav() {
    const nav = document.getElementById('category-nav');
    clearElement(nav);
    if (nav) nav.style.display = 'flex';

    if (!latestData || !latestData.top_news) return;

    const counts = latestData.top_news.reduce((acc, item) => {
        const category = item.category || '未分类';
        acc[category] = (acc[category] || 0) + 1;
        return acc;
    }, {});

    Object.keys(counts).sort().forEach((category) => {
        const entry = document.createElement('button');
        entry.type = 'button';
        entry.className = 'category-entry';
        entry.addEventListener('click', () => renderCategoryDetail(category));

        const label = document.createElement('span');
        label.textContent = category;

        const count = document.createElement('span');
        count.className = 'category-entry__count';
        count.textContent = String(counts[category]);

        entry.appendChild(label);
        entry.appendChild(count);
        nav.appendChild(entry);
    });
}

function createNewsCard(newsItem, index) {
    const safeLink = isSafeHttpUrlString(newsItem.original_link);
    const card = document.createElement('article');
    card.className = 'news-card fade-in';
    card.style.animationDelay = `${index * 0.05}s`;

    const header = document.createElement('div');
    header.className = 'card-header';

    const meta = document.createElement('div');
    meta.className = 'card-meta card-meta--split';

    const sourceLabel = document.createElement('span');
    sourceLabel.className = 'source-label';
    sourceLabel.textContent = newsItem.source || '未知来源';

    const categoryLabel = document.createElement('span');
    categoryLabel.className = 'category-badge';
    categoryLabel.textContent = newsItem.category || '未分类';

    meta.appendChild(sourceLabel);
    meta.appendChild(categoryLabel);

    // Personalized recommendation badge
    if (typeof newsItem.persona_score === 'number' && newsItem.persona_score > 0.5) {
        const recBadge = document.createElement('span');
        recBadge.className = 'persona-rec-badge';
        recBadge.textContent = '🎯 为你推荐';
        meta.appendChild(recBadge);
    }

    const headline = document.createElement('h2');
    headline.textContent = newsItem.headline || '未命名资讯';

    header.appendChild(meta);
    header.appendChild(headline);

    const body = document.createElement('div');
    body.className = 'card-body';

    const pointsList = document.createElement('ul');
    for (const point of newsItem.key_points || []) {
        const item = document.createElement('li');
        item.textContent = point;
        pointsList.appendChild(item);
    }
    body.appendChild(pointsList);

    if (Array.isArray(newsItem.tags) && newsItem.tags.length > 0) {
        const tagsContainer = document.createElement('div');
        tagsContainer.className = 'tags-container';
        for (const tag of newsItem.tags) {
            const badge = document.createElement('span');
            badge.className = 'tag-badge';
            badge.textContent = tag;
            tagsContainer.appendChild(badge);
        }
        body.appendChild(tagsContainer);
    }

    const footer = document.createElement('div');
    footer.className = 'card-footer';

    const readMore = document.createElement('a');
    readMore.className = 'read-more';
    readMore.textContent = '阅读原文';
    if (safeLink) {
        readMore.href = newsItem.original_link;
        readMore.target = '_blank';
        readMore.rel = 'noopener noreferrer';
    } else {
        readMore.href = '#';
        readMore.classList.add('is-disabled');
        readMore.addEventListener('click', (event) => event.preventDefault());
    }
    appendStaticIcon(readMore, ICONS.external);

    const actions = document.createElement('div');
    actions.className = 'card-actions';

    const feedbackContainer = document.createElement('div');
    feedbackContainer.className = 'feedback-container';

    const likeButton = document.createElement('button');
    likeButton.type = 'button';
    likeButton.className = 'feedback-btn like';
    likeButton.title = '感兴趣';
    likeButton.disabled = !safeLink;
    likeButton.innerHTML = ICONS.like;
    likeButton.addEventListener('click', () => sendFeedback(likeButton, newsItem.original_link, 1, newsItem));

    const dislikeButton = document.createElement('button');
    dislikeButton.type = 'button';
    dislikeButton.className = 'feedback-btn dislike';
    dislikeButton.title = '不感兴趣';
    dislikeButton.disabled = !safeLink;
    dislikeButton.innerHTML = ICONS.dislike;
    dislikeButton.addEventListener('click', () => sendFeedback(dislikeButton, newsItem.original_link, -1));

    applyFeedbackState(likeButton, dislikeButton, newsItem.feedback_sentiment || 0);

    feedbackContainer.appendChild(likeButton);
    feedbackContainer.appendChild(dislikeButton);

    const statuses = savedStatusMap[newsItem.original_link] || [];

    const favoriteButton = document.createElement('button');
    favoriteButton.type = 'button';
    favoriteButton.className = 'feedback-btn favorite';
    favoriteButton.title = '收藏';
    favoriteButton.disabled = !safeLink;
    favoriteButton.innerHTML = ICONS.favorite;
    favoriteButton.classList.toggle('active', statuses.includes('favorite'));
    favoriteButton.addEventListener('click', () => toggleSaved(favoriteButton, newsItem, 'favorite'));

    const readLaterButton = document.createElement('button');
    readLaterButton.type = 'button';
    readLaterButton.className = 'feedback-btn read-later';
    readLaterButton.title = '稍后阅读';
    readLaterButton.disabled = !safeLink;
    readLaterButton.innerHTML = ICONS.readLater;
    readLaterButton.classList.toggle('active', statuses.includes('read_later'));
    readLaterButton.addEventListener('click', () => toggleSaved(readLaterButton, newsItem, 'read_later'));

    feedbackContainer.appendChild(favoriteButton);
    feedbackContainer.appendChild(readLaterButton);

    const askButton = document.createElement('button');
    askButton.type = 'button';
    askButton.className = 'ask-btn';
    askButton.disabled = !safeLink;
    askButton.addEventListener('click', () => openRagPanel(newsItem.original_link, newsItem.headline || '未命名资讯'));
    appendStaticIcon(askButton, ICONS.ask);
    askButton.appendChild(document.createTextNode('深度追问'));

    actions.appendChild(feedbackContainer);
    actions.appendChild(askButton);

    footer.appendChild(readMore);
    footer.appendChild(actions);

    card.appendChild(header);
    card.appendChild(body);
    card.appendChild(footer);

    return card;
}

function renderCategoryDetail(categoryName) {
    const container = document.getElementById('news-container');
    const overviewSection = document.querySelector('.overview-section');
    const viewControls = document.getElementById('view-controls');

    clearElement(container);
    container.className = 'news-grid';
    overviewSection.style.display = 'none';
    viewControls.style.display = 'flex';

    const detailHeader = document.createElement('div');
    detailHeader.className = 'category-header';

    const title = document.createElement('span');
    title.className = 'category-title';
    title.textContent = categoryName;

    const line = document.createElement('div');
    line.className = 'category-line';

    detailHeader.appendChild(title);
    detailHeader.appendChild(line);
    container.appendChild(detailHeader);

    (latestData.top_news || [])
        .filter((item) => (item.category || '未分类') === categoryName)
        .forEach((newsItem, index) => {
            container.appendChild(createNewsCard(newsItem, index));
        });

    window.scrollTo({ top: 0, behavior: 'smooth' });
}

function showDashboard() {
    renderHome();
}

function renderSourceStats(stats) {
    const statsContainer = document.getElementById('stats-container');
    clearElement(statsContainer);

    if (!stats || Object.keys(stats).length === 0) {
        statsContainer.style.display = 'none';
        return;
    }
    statsContainer.style.display = 'flex';

    const label = document.createElement('h4');
    label.className = 'metrics-card-title';
    label.textContent = '来源分布 (今日)';
    statsContainer.appendChild(label);

    Object.keys(stats).sort().forEach((source) => {
        const pill = document.createElement('div');
        pill.className = 'source-pill';

        const name = document.createElement('span');
        name.className = 'source-pill__name';
        name.textContent = source;

        const count = document.createElement('span');
        count.className = 'source-pill__count';
        count.textContent = String(stats[source]);

        pill.appendChild(name);
        pill.appendChild(count);
        statsContainer.appendChild(pill);
    });
}

function openRefreshModal() {
    const modal = document.getElementById('refresh-modal');
    if (!modal) return;
    openOverlay(modal, '#refresh-preference');

    const preferenceInput = _getRefreshPreferenceInput();
    if (preferenceInput) {
        preferenceInput.value = '';
    }

    const savePersonaCheckbox = _getRefreshSavePersonaCheckbox();
    if (savePersonaCheckbox) {
        savePersonaCheckbox.checked = false;
    }
}

function closeRefreshModal() {
    const modal = document.getElementById('refresh-modal');
    closeOverlay(modal);
}

function confirmForceRefresh() {
    const preferenceInput = _getRefreshPreferenceInput();
    const savePersonaCheckbox = _getRefreshSavePersonaCheckbox();
    const preference = preferenceInput ? preferenceInput.value.trim() : '';
    const saveIt = !!(savePersonaCheckbox && savePersonaCheckbox.checked);
    closeRefreshModal();

    // Clear cache so force refresh shows loading state
    _clearCachedSummary();
    latestData = null;

    let url = '/api/v1/summary?force=true';
    if (preference) {
        url += `&preference=${encodeURIComponent(preference)}`;
        if (saveIt) {
            url += '&save_preference=true';
        }
    }

    fetchSummaryWithUrl(url);
}

function submitRefresh() {
    confirmForceRefresh();
}

function _getRefreshPreferenceInput() {
    return document.getElementById('refresh-preference') || document.getElementById('refresh-prompt');
}

function _getRefreshSavePersonaCheckbox() {
    return document.getElementById('save-preference-chk') || document.getElementById('refresh-save-persona');
}

function togglePersonaPanel() {
    const panel = document.getElementById('persona-panel');
    if (toggleOverlay(panel, '#pref-input-focus_topic')) {
        loadPersonaData();
        loadExplicitPreferences();
        loadPrefSuggestions();
    }
}

async function fetchSystemMetrics() {
    try {
        const response = await fetch('/api/v1/metrics');
        const data = await response.json();
        
        if (data.tokens) {
            document.getElementById('metric-tokens').textContent = data.tokens.total.toLocaleString();
        }
        if (data.latency) {
            document.getElementById('metric-p50').textContent = data.latency.p50_sec > 0 ? `${data.latency.p50_sec} s` : '--';
            document.getElementById('metric-p99').textContent = data.latency.p99_sec > 0 ? `${data.latency.p99_sec} s` : '--';
        }
    } catch (e) {
        console.error("Failed to load metrics", e);
    }
}

async function loadPersonaData() {
    try {
        let url = '/api/v1/persona';
        if (currentBoardSlug) url += `?board=${encodeURIComponent(currentBoardSlug)}`;
        const response = await fetch(url);
        if (response.ok) {
            renderPersonaInstructions(await response.json());
        }
    } catch (error) {
        console.error('Failed to load persona data:', error);
    }
}

function renderPersonaInstructions(personas) {
    const container = document.getElementById('persona-instructions');
    clearElement(container);

    if (!personas || personas.length === 0) {
        const empty = document.createElement('p');
        empty.className = 'empty-state-text';
        empty.textContent = '暂无长期偏好。重新生成时勾选“设为长期兴趣”即可添加。';
        container.appendChild(empty);
        return;
    }

    for (const persona of personas) {
        const item = document.createElement('div');
        item.className = 'persona-item';

        const text = document.createElement('span');
        text.textContent = persona.content;

        const removeButton = document.createElement('button');
        removeButton.type = 'button';
        removeButton.className = 'remove-btn';
        removeButton.title = '删除此偏好';
        removeButton.setAttribute('aria-label', '删除此偏好');
        removeButton.innerHTML = '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>';
        removeButton.addEventListener('click', () => removePersona(persona.id));

        item.appendChild(text);
        item.appendChild(removeButton);
        container.appendChild(item);
    }
}

function renderRecReport() {
    const reportContainer = document.getElementById('rec-report-container');
    if (!latestData || !latestData.recommendation_report || Object.keys(latestData.recommendation_report).length === 0) {
        if (reportContainer) reportContainer.style.display = 'none';
        return;
    }

    const report = latestData.recommendation_report;
    const totalEl = document.getElementById('stat-total');
    const passedEl = document.getElementById('stat-passed');
    const samplesList = document.getElementById('excluded-samples');

    if (reportContainer) reportContainer.style.display = 'block';
    if (totalEl) totalEl.textContent = report.total_fetched || 0;
    if (passedEl) passedEl.textContent = report.passed_count || (latestData.top_news ? latestData.top_news.length : 0);

    clearElement(samplesList);
    if (Array.isArray(report.excluded_samples)) {
        report.excluded_samples.forEach(title => {
            const li = document.createElement('li');
            li.textContent = title;
            samplesList.appendChild(li);
        });
    }
}

async function removePersona(id) {
    try {
        const response = await fetch(`/api/v1/persona/${id}`, { method: 'DELETE' });
        if (!response.ok) {
            throw new Error(`HTTP ${response.status}`);
        }
        await loadPersonaData();
    } catch (error) {
        console.error('Failed to delete persona:', error);
    }
}

async function sendFeedback(buttonElement, url, sentiment, newsItem) {
    const container = buttonElement.closest('.feedback-container');
    const likeButton = container ? container.querySelector('.feedback-btn.like') : null;
    const dislikeButton = container ? container.querySelector('.feedback-btn.dislike') : null;

    if (!likeButton || !dislikeButton) {
        return;
    }

    const currentSentiment = likeButton.classList.contains('active')
        ? 1
        : dislikeButton.classList.contains('active')
            ? -1
            : 0;
    const nextSentiment = currentSentiment === sentiment ? 0 : sentiment;

    applyFeedbackState(likeButton, dislikeButton, nextSentiment);
    likeButton.disabled = true;
    dislikeButton.disabled = true;

    try {
        const response = await fetch('/api/v1/rag/feedback', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ url, sentiment: nextSentiment })
        });

        if (!response.ok) {
            throw new Error(`HTTP ${response.status}`);
        }

        updateFeedbackStateInData(url, nextSentiment);

        // On a fresh positive like, offer the user a chance to declare WHY
        // (capturing abstract intent rather than literal subject).
        if (nextSentiment === 1 && currentSentiment !== 1 && newsItem) {
            showInterestReasonPopup(buttonElement, newsItem);
        }
    } catch (error) {
        console.error('Failed to submit feedback:', error);
        applyFeedbackState(likeButton, dislikeButton, currentSentiment);
    } finally {
        const disabled = !isSafeHttpUrlString(url);
        likeButton.disabled = disabled;
        dislikeButton.disabled = disabled;
    }
}

// ==========================================
// Saved Articles (Favorites / Read Later)
// ==========================================

async function loadSavedState() {
    try {
        const res = await fetch('/api/v1/saved/urls');
        if (res.ok) {
            savedStatusMap = await res.json() || {};
        }
    } catch (e) {
        console.error('Failed to load saved state', e);
    }
}

async function toggleSaved(buttonElement, newsItem, status) {
    const url = newsItem.original_link;
    if (!isSafeHttpUrlString(url)) return;

    const statuses = savedStatusMap[url] || [];
    const isActive = statuses.includes(status);
    const nextActive = !isActive;

    // Optimistic UI update
    buttonElement.classList.toggle('active', nextActive);
    buttonElement.disabled = true;

    try {
        if (nextActive) {
            const res = await fetch('/api/v1/saved', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    url,
                    status,
                    headline: newsItem.headline || '',
                    source: newsItem.source || '',
                    category: newsItem.category || '',
                    board: currentBoardSlug || '',
                })
            });
            if (!res.ok) throw new Error(`HTTP ${res.status}`);
            savedStatusMap[url] = Array.from(new Set([...statuses, status]));
        } else {
            const res = await fetch('/api/v1/saved', {
                method: 'DELETE',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ url, status })
            });
            if (!res.ok) throw new Error(`HTTP ${res.status}`);
            savedStatusMap[url] = statuses.filter((s) => s !== status);
            if (savedStatusMap[url].length === 0) delete savedStatusMap[url];
        }
    } catch (error) {
        console.error('Failed to toggle saved state:', error);
        buttonElement.classList.toggle('active', isActive);  // revert
    } finally {
        buttonElement.disabled = false;
    }
}

let currentSavedTab = 'favorite';

function toggleSavedPanel() {
    const panel = document.getElementById('saved-modal');
    if (toggleOverlay(panel)) {
        switchSavedTab(currentSavedTab);
    }
}

function switchSavedTab(status) {
    currentSavedTab = status;
    document.querySelectorAll('.saved-tab').forEach((tab) => {
        tab.classList.toggle('active', tab.dataset.status === status);
    });
    renderSavedList(status);
}

async function renderSavedList(status) {
    const container = document.getElementById('saved-list');
    if (!container) return;
    clearElement(container);

    const loading = document.createElement('p');
    loading.className = 'saved-placeholder';
    loading.textContent = '正在加载...';
    container.appendChild(loading);

    let items = [];
    try {
        const res = await fetch(`/api/v1/saved?status=${encodeURIComponent(status)}`);
        if (res.ok) {
            const data = await res.json();
            items = data.items || [];
        }
    } catch (e) {
        console.error('Failed to load saved list', e);
    }

    clearElement(container);

    if (items.length === 0) {
        const empty = document.createElement('p');
        empty.className = 'saved-placeholder';
        empty.textContent = status === 'favorite' ? '还没有收藏任何资讯。' : '还没有标记任何稍后阅读的资讯。';
        container.appendChild(empty);
        return;
    }

    items.forEach((item) => {
        const safeLink = isSafeHttpUrlString(item.url);
        const row = document.createElement('div');
        row.className = 'saved-item';

        const main = document.createElement('div');
        main.className = 'saved-item__main';

        const titleEl = document.createElement(safeLink ? 'a' : 'span');
        titleEl.className = 'saved-item__title';
        titleEl.textContent = item.headline || item.url;
        if (safeLink) {
            titleEl.href = item.url;
            titleEl.target = '_blank';
            titleEl.rel = 'noopener noreferrer';
        }

        const meta = document.createElement('div');
        meta.className = 'saved-item__meta';
        const metaParts = [];
        if (item.source) metaParts.push(item.source);
        if (item.category) metaParts.push(item.category);
        meta.textContent = metaParts.join(' · ');

        main.appendChild(titleEl);
        main.appendChild(meta);

        const removeBtn = document.createElement('button');
        removeBtn.type = 'button';
        removeBtn.className = 'saved-item__remove';
        removeBtn.title = '移除';
        removeBtn.textContent = '×';
        removeBtn.addEventListener('click', async () => {
            try {
                const res = await fetch('/api/v1/saved', {
                    method: 'DELETE',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ url: item.url, status })
                });
                if (!res.ok) throw new Error(`HTTP ${res.status}`);
                const remaining = (savedStatusMap[item.url] || []).filter((s) => s !== status);
                if (remaining.length === 0) delete savedStatusMap[item.url];
                else savedStatusMap[item.url] = remaining;
                row.remove();
                if (!container.querySelector('.saved-item')) {
                    renderSavedList(status);
                }
                // Refresh any visible cards' button state
                _syncSavedButtonsForUrl(item.url, status, false);
            } catch (e) {
                console.error('Failed to remove saved item', e);
            }
        });

        row.appendChild(main);
        row.appendChild(removeBtn);
        container.appendChild(row);
    });
}

function _syncSavedButtonsForUrl(url, status, active) {
    const cls = status === 'favorite' ? '.feedback-btn.favorite' : '.feedback-btn.read-later';
    document.querySelectorAll('.news-card').forEach((card) => {
        const link = card.querySelector('.read-more');
        if (link && link.href === url) {
            const btn = card.querySelector(cls);
            if (btn) btn.classList.toggle('active', active);
        }
    });
}

async function showInterestReasonPopup(anchorButton, newsItem) {
    // Remove any existing popup
    document.querySelectorAll('.interest-popup').forEach((el) => el.remove());

    const card = anchorButton.closest('.news-card');
    if (!card) return;

    const popup = document.createElement('div');
    popup.className = 'interest-popup';
    popup.innerHTML = `
        <div class="interest-popup__header">
            <span class="interest-popup__title">🎯 你为什么感兴趣？</span>
            <button type="button" class="interest-popup__close" aria-label="关闭">×</button>
        </div>
        <p class="interest-popup__hint">选一项，添加为长期偏好。会影响后续生成的简报。</p>
        <div class="interest-popup__options">
            <div class="interest-popup__loading">AI 正在为你提炼选项...</div>
        </div>
    `;
    card.appendChild(popup);

    const closeBtn = popup.querySelector('.interest-popup__close');
    closeBtn.addEventListener('click', () => popup.remove());

    // Auto-dismiss after 25s if untouched
    const dismissTimer = setTimeout(() => popup.remove(), 25000);

    let options = [];
    try {
        const res = await fetch('/api/v1/feedback/interest-options', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                headline: newsItem.headline || '',
                key_points: newsItem.key_points || [],
                tags: newsItem.tags || [],
            }),
        });
        if (res.ok) {
            const data = await res.json();
            options = Array.isArray(data.options) ? data.options : [];
        }
    } catch (error) {
        console.error('Failed to fetch interest options:', error);
    }

    const optionsContainer = popup.querySelector('.interest-popup__options');
    optionsContainer.innerHTML = '';
    if (options.length === 0) {
        optionsContainer.innerHTML = '<div class="interest-popup__empty">未能生成选项，可稍后在偏好面板手动添加。</div>';
        return;
    }

    options.forEach((opt) => {
        const chip = document.createElement('button');
        chip.type = 'button';
        chip.className = 'interest-chip';
        chip.textContent = opt;
        chip.addEventListener('click', async () => {
            chip.disabled = true;
            chip.classList.add('saving');
            try {
                let url = '/api/v1/feedback/save-reason';
                if (currentBoardSlug) url += `?board=${encodeURIComponent(currentBoardSlug)}`;
                const r = await fetch(url, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ content: opt }),
                });
                if (!r.ok) throw new Error(`HTTP ${r.status}`);
                clearTimeout(dismissTimer);
                popup.classList.add('saved');
                popup.querySelector('.interest-popup__options').innerHTML =
                    `<div class="interest-popup__success"><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round" style="margin-right: 0.3rem; vertical-align: middle;"><polyline points="20 6 9 17 4 12"></polyline></svg> 已添加：<strong>${opt}</strong></div>`;
                setTimeout(() => popup.remove(), 1500);
            } catch (error) {
                console.error('Failed to save interest reason:', error);
                chip.disabled = false;
                chip.classList.remove('saving');
            }
        });
        optionsContainer.appendChild(chip);
    });
}

function setupHistoryPanel() {
    const historyBtn = document.getElementById('history-btn');
    if (historyBtn) {
        // Just ensuring it's there
    }
}

function formatSummaryDate(date) {
    const dateObj = new Date(`${date}T00:00:00`);
    return dateObj.toLocaleDateString('zh-CN', {
        month: 'long',
        day: 'numeric',
        weekday: 'short'
    });
}

function createArchiveMeta(text, className) {
    const item = document.createElement('span');
    item.className = className;
    item.textContent = text;
    return item;
}

function renderHistoryInsights(weeklyRecap) {
    const statsContainer = document.getElementById('magazine-recap-stats');

    if (!statsContainer) return;

    clearElement(statsContainer);

    if (!weeklyRecap) {
        statsContainer.innerHTML = '<p class="magazine-placeholder">暂无近期的汇总数据。</p>';
        return;
    }

    const recapCard = document.createElement('div');
    recapCard.className = 'history-recap-card';
    recapCard.style.maxWidth = '100%'; 
    recapCard.style.margin = '0 auto';

    const badge = document.createElement('span');
    badge.className = 'history-recap-badge';
    badge.textContent = '本周概览';

    const title = document.createElement('h4');
    title.className = 'history-recap-title';
    title.textContent = `${formatSummaryDate(weeklyRecap.window_start)} - ${formatSummaryDate(weeklyRecap.window_end)}`;

    const summaryStats = document.createElement('div');
    summaryStats.className = 'history-insight-stats';
    summaryStats.appendChild(createArchiveMeta(`${weeklyRecap.days_covered || 0} 天`, 'history-chip history-chip--accent'));
    summaryStats.appendChild(createArchiveMeta(`${weeklyRecap.total_news || 0} 条资讯`, 'history-chip history-chip--accent'));

    (weeklyRecap.top_categories || []).slice(0, 3).forEach((item) => {
        summaryStats.appendChild(createArchiveMeta(`${item.name} × ${item.count}`, 'history-chip'));
    });

    (weeklyRecap.top_sources || []).slice(0, 2).forEach((item) => {
        summaryStats.appendChild(createArchiveMeta(`${item.name} × ${item.count}`, 'history-chip history-chip--source'));
    });

    const recapText = document.createElement('p');
    recapText.className = 'history-recap-text';
    recapText.textContent = weeklyRecap.recap_text || '本周已有多期简报，可快速查阅深度分析。';

    recapCard.appendChild(badge);
    recapCard.appendChild(title);
    recapCard.appendChild(summaryStats);
    recapCard.appendChild(recapText);
    
    statsContainer.appendChild(recapCard);
}

async function triggerWeeklyInsight() {
    const content = document.getElementById('weekly-insight-content');
    const genBtn = document.getElementById('gen-weekly-btn');

    if (!content || !genBtn) return;

    genBtn.style.opacity = '0.5';
    genBtn.disabled = true;
    genBtn.innerHTML = '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round" style="margin-right: 0.4rem; vertical-align: middle;"><polygon points="13 2 3 14 12 14 11 22 21 10 12 10 13 2"></polygon></svg> 汇总生成中...';
    
    clearElement(content);
    const loadingMsg = document.createElement('p');
    loadingMsg.className = 'generating-text';
    loadingMsg.id = 'insight-loading-status';
    loadingMsg.textContent = 'AI 正在提炼本周技术动态，请稍候...';
    content.appendChild(loadingMsg);

    try {
        let url = '/api/v1/history/weekly_insight';
        if (currentBoardSlug) url += `?board=${encodeURIComponent(currentBoardSlug)}`;
        const response = await fetch(url);
        
        if (!response.ok) throw new Error('Generation failed');
        
        const data = await response.json();
        
        clearElement(content);
        
        if (typeof marked !== 'undefined') {
            content.innerHTML = marked.parse(data.weekly_insight);
        } else {
            content.textContent = data.weekly_insight;
        }

    } catch (error) {
        clearElement(content);
        genBtn.style.opacity = '1';
        genBtn.disabled = false;
        genBtn.innerHTML = '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round" style="margin-right: 0.4rem; vertical-align: middle;"><polygon points="13 2 3 14 12 14 11 22 21 10 12 10 13 2"></polygon></svg> 生成本周深度汇总';
        
        const err = document.createElement('p');
        err.className = 'error-message';
        err.textContent = '周刊生成出了点意外，请稍后再试。';
        content.appendChild(err);
    }
}

function toggleHistoryPanel() {
    const panel = document.getElementById('history-modal');
    if (toggleOverlay(panel, '#history-unread-only')) {
        loadHistoryData('history');
    }
}

function toggleMagazinePanel() {
    const panel = document.getElementById('magazine-modal');
    if (toggleOverlay(panel, '#gen-weekly-btn')) {
        loadHistoryData('magazine');
    }
}

async function loadHistoryData(target = 'history') {
    const listContainer = document.getElementById('history-list');
    
    // Preliminary cleanup
    if (target === 'history' && listContainer) {
        clearElement(listContainer);
        const skeleton = document.createElement('p');
        skeleton.className = 'history-hint';
        skeleton.textContent = '正在加载历史记录...';
        listContainer.appendChild(skeleton);
    }

    try {
        let url = '/api/v1/history';
        if (currentBoardSlug) url += `?board=${encodeURIComponent(currentBoardSlug)}`;
        const response = await fetch(url);
        if (!response.ok) throw new Error('Failed to fetch history');

        const historyData = await response.json();
        latestHistoryArchive = Array.isArray(historyData.archive_items) ? historyData.archive_items : [];

        // Fetch viewed status for history items
        try {
            let cacheUrl = '/api/v1/cache';
            if (currentBoardSlug) cacheUrl += `?board=${encodeURIComponent(currentBoardSlug)}`;
            const cacheResp = await fetch(cacheUrl);
            if (cacheResp.ok) {
                const cacheData = await cacheResp.json();
                historyViewStatus = {};
                if (Array.isArray(cacheData.items)) {
                    cacheData.items.forEach(it => {
                        historyViewStatus[it.date] = it.viewed_at;
                    });
                }
            }
        } catch (_) { /* non-critical */ }

        // Dispatch to both
        renderHistoryInsights(historyData.weekly_recap || null);

        if (!listContainer) return;
        clearElement(listContainer);

        if (!latestHistoryArchive || latestHistoryArchive.length === 0) {
            const empty = document.createElement('p');
            empty.className = 'history-hint';
            empty.textContent = '暂无历史记录。';
            listContainer.appendChild(empty);
            return;
        }

        latestHistoryArchive.forEach((entry) => {
            const item = document.createElement('button');
            item.type = 'button';
            item.className = 'history-item';
            const isUnviewed = !historyViewStatus[entry.date];
            if (isUnviewed) item.classList.add('history-item--unviewed');
            if (latestData && latestData.date === entry.date) {
                item.classList.add('active');
            }

            const main = document.createElement('div');
            main.className = 'history-main';

            const topRow = document.createElement('div');
            topRow.className = 'history-top-row';

            const dateSpan = document.createElement('span');
            dateSpan.className = 'history-date';
            dateSpan.textContent = formatSummaryDate(entry.date);

            if (isUnviewed) {
                const dot = document.createElement('span');
                dot.className = 'unviewed-dot';
                dot.title = '未读';
                dateSpan.appendChild(dot);
            }

            const countSpan = createArchiveMeta(`${entry.news_count || 0} 条资讯`, 'history-count');
            topRow.appendChild(dateSpan);
            topRow.appendChild(countSpan);

            const preview = document.createElement('p');
            preview.className = 'history-preview';
            preview.textContent = entry.overview_preview || '暂无概要。';

            const meta = document.createElement('div');
            meta.className = 'history-meta';

            if (Array.isArray(entry.top_categories) && entry.top_categories.length > 0) {
                entry.top_categories.slice(0, 3).forEach((category) => {
                    meta.appendChild(createArchiveMeta(category, 'history-chip'));
                });
            }

            if (entry.source_stats && Object.keys(entry.source_stats).length > 0) {
                const topSource = Object.entries(entry.source_stats)
                    .sort((a, b) => b[1] - a[1])[0];
                if (topSource) {
                    meta.appendChild(createArchiveMeta(`${topSource[0]} × ${topSource[1]}`, 'history-chip history-chip--source'));
                }
            }

            main.appendChild(topRow);
            main.appendChild(preview);
            if (meta.childNodes.length > 0) {
                main.appendChild(meta);
            }

            const icon = document.createElement('span');
            icon.className = 'history-go';
            icon.innerHTML = '<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><line x1="5" y1="12" x2="19" y2="12"></line><polyline points="12 5 19 12 12 19"></polyline></svg>';

            item.appendChild(main);
            item.appendChild(icon);

            item.addEventListener('click', () => {
                toggleHistoryPanel();
                fetchSummary(false, entry.date);
            });

            listContainer.appendChild(item);
        });
    } catch (error) {
        console.error('History load error:', error);
        latestHistoryArchive = [];
        renderHistoryInsights(null);
        clearElement(listContainer);
        const err = document.createElement('p');
        err.className = 'history-hint';
        err.textContent = '加载失败，请重试。';
        listContainer.appendChild(err);
    }
}

function parseSseEvents(buffer) {
    const normalizedBuffer = buffer.replace(/\r\n/g, '\n').replace(/\r/g, '\n');
    const events = [];
    let remaining = normalizedBuffer;

    while (true) {
        const separatorIndex = remaining.indexOf('\n\n');
        if (separatorIndex === -1) {
            break;
        }

        const rawEvent = remaining.slice(0, separatorIndex);
        remaining = remaining.slice(separatorIndex + 2);

        const dataLines = rawEvent
            .split('\n')
            .filter((line) => line.startsWith('data:'))
            .map((line) => {
                const value = line.slice(5);
                return value.startsWith(' ') ? value.slice(1) : value;
            });

        if (dataLines.length > 0) {
            events.push(dataLines.join('\n'));
        }
    }

    return { events, buffer: remaining };
}

function setupRagPanel() {
    const overlay = document.getElementById('rag-overlay');
    const closeBtn = document.getElementById('rag-close-btn');
    const form = document.getElementById('rag-form');
    const input = document.getElementById('rag-input');

    overlay.addEventListener('click', closeRagPanel);
    closeBtn.addEventListener('click', closeRagPanel);

    form.addEventListener('submit', async (event) => {
        event.preventDefault();
        const question = input.value.trim();
        if (!question || !currentUrl || isIngesting) return;

        input.value = '';
        appendMessage('user', question);
        await runRagQuery(question);
    });
}

async function openRagPanel(url, headline) {
    const panelUrl = url;
    currentUrl = panelUrl;
    isIngesting = true;

    const messages = document.getElementById('rag-messages');
    const input = document.getElementById('rag-input');

    clearElement(messages);
    document.getElementById('rag-article-title').textContent = headline;
    openRagOverlay('#rag-close-btn');
    input.disabled = true;

    try {
        const historyRes = await fetch(`/api/v1/rag/history?url=${encodeURIComponent(panelUrl)}`);
        if (historyRes.ok) {
            const historyData = await historyRes.json();
            if (currentUrl !== panelUrl) {
                return;
            }
            if (Array.isArray(historyData.history) && historyData.history.length > 0) {
                historyData.history.forEach((message) => {
                    const role = message.role === 'assistant' ? 'ai' : message.role;
                    appendMessage(role, message.content);
                });
                appendMessage('system', '以上为之前的对话记录');
            }
        }
    } catch (error) {
        console.error('Failed to load history:', error);
    }

    if (currentUrl !== panelUrl) {
        return;
    }

    const overviewMessage = appendMessage('ai', '');
    setAiMessageText(overviewMessage, '正在生成更详细的文章概要...');

    if (currentOverviewController) {
        currentOverviewController.abort();
    }
    currentOverviewController = new AbortController();

    const overviewPromise = (async () => {
        let hasContent = false;
        let markdownContent = '**快速导读**\n\n';

        try {
            const response = await fetch('/api/v1/rag/overview', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ url: panelUrl }),
                signal: currentOverviewController.signal
            });

            if (!response.ok || !response.body) {
                throw new Error('详细概要生成失败，但你仍可继续提问。');
            }

            const reader = response.body.getReader();
            const decoder = new TextDecoder();
            let buffer = '';

            while (true) {
                const { done, value } = await reader.read();
                if (done) break;

                buffer += decoder.decode(value, { stream: true });
                const parsed = parseSseEvents(buffer);
                buffer = parsed.buffer;

                for (const token of parsed.events) {
                    if (token === '[DONE]') continue;
                    if (currentUrl !== panelUrl) {
                        return;
                    }

                    hasContent = true;
                    markdownContent += token;
                    renderAiMarkdown(overviewMessage, markdownContent);
                }
            }

            if (!hasContent && currentUrl === panelUrl) {
                throw new Error('详细概要生成失败，但你仍可继续提问。');
            }
        } catch (error) {
            if (error.name === 'AbortError' || currentUrl !== panelUrl) {
                return;
            }
            setAiMessageText(overviewMessage, error.message);
        } finally {
            if (currentOverviewController && currentOverviewController.signal.aborted) {
                currentOverviewController = null;
            } else if (currentOverviewController) {
                currentOverviewController = null;
            }
        }
    })();

    // --- Background-aware ingestion: check status first, skip loading if already done ---
    let alreadyIngested = false;
    try {
        const statusRes = await fetch(`/api/v1/rag/ingest_status?url=${encodeURIComponent(panelUrl)}`);
        if (statusRes.ok) {
            const statusData = await statusRes.json();
            if (statusData.status === 'done') {
                alreadyIngested = true;
            }
        }
    } catch (_) { /* ignore – will fall through to ingest */ }

    if (alreadyIngested) {
        const ingestMessage = appendMessage('system', '知识索引已就绪，你可以直接提问。');
        input.disabled = false;
        input.focus();
        isIngesting = false;
    } else {
        const ingestMessage = appendMessage('system', '正在阅读原文并建立知识索引，请稍候...');

        try {
            const response = await fetch('/api/v1/rag/ingest', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ url: panelUrl })
            });

            if (!response.ok) {
                throw new Error('文章索引失败，请检查该链接是否可访问。');
            }

            const data = await response.json();
            if (currentUrl !== panelUrl) {
                return;
            }
            ingestMessage.textContent = `原文已加载（共 ${data.chunks} 个段落块）。现在你可以继续追问了。`;

            // Show quality warning if extraction was problematic
            if (data.quality && data.quality.verdict !== 'good') {
                const qualityMsg = appendMessage('system', '');
                const detail = data.quality.details ? `（${data.quality.details}）` : '';
                if (data.quality.verdict === 'partial') {
                    qualityMsg.className = 'rag-msg rag-msg--system quality-warning';
                    qualityMsg.textContent = `⚠️ 内容解析不完整，回答可能有遗漏${detail}`;
                } else {
                    qualityMsg.className = 'rag-msg rag-msg--system quality-error';
                    qualityMsg.textContent = `❌ 内容提取质量很差，建议直接阅读原文${detail}`;
                }
            }

            input.disabled = false;
            input.focus();
        } catch (error) {
            if (currentUrl === panelUrl) {
                ingestMessage.textContent = error.message;
            }
        } finally {
            if (!currentUrl || currentUrl === panelUrl) {
                isIngesting = false;
            }
        }
    }

    await overviewPromise;
}

function closeRagPanel() {
    closeRagOverlay();
    if (currentQueryController) {
        currentQueryController.abort();
        currentQueryController = null;
    }
    if (currentOverviewController) {
        currentOverviewController.abort();
        currentOverviewController = null;
    }
    isIngesting = false;
    currentUrl = null;
}

async function runRagQuery(question) {
    const aiMessage = appendMessage('ai', '');
    const input = document.getElementById('rag-input');
    input.disabled = true;

    if (currentQueryController) {
        currentQueryController.abort();
    }
    currentQueryController = new AbortController();

    let citations = [];

    try {
        const response = await fetch('/api/v1/rag/query', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ url: currentUrl, question }),
            signal: currentQueryController.signal
        });

        if (!response.ok) {
            const errorData = await response.json().catch(() => ({}));
            const message = errorData.detail || `HTTP ${response.status}`;
            setAiMessageText(aiMessage, `错误: ${message}`);
            return;
        }

        const reader = response.body.getReader();
        const decoder = new TextDecoder();
        let buffer = '';
        let markdownContent = '';

        while (true) {
            const { done, value } = await reader.read();
            if (done) break;

            buffer += decoder.decode(value, { stream: true });
            const parsed = parseSseEvents(buffer);
            buffer = parsed.buffer;

            for (const token of parsed.events) {
                if (token === '[DONE]') continue;

                const metadataMatch = token.match(/\[METADATA\]([\s\S]*?)\[\/METADATA\]/);
                if (metadataMatch) {
                    try {
                        const metadata = JSON.parse(metadataMatch[1]);
                        if (metadata.type === 'scoring_explain') {
                            renderScoringExplain(aiMessage, metadata.scores || []);
                        }
                        if (metadata.citations) {
                            citations = metadata.citations;
                        }
                    } catch (error) {
                        console.error('Failed to parse metadata:', error);
                    }
                    continue;
                }

                markdownContent += token;
                renderAiMarkdown(aiMessage, markdownContent);
            }
        }

        if (citations.length > 0) {
            renderCitations(aiMessage, citations);
        }
    } catch (error) {
        if (error.name !== 'AbortError') {
            setAiMessageText(aiMessage, `连接错误: ${error.message}`);
        }
    } finally {
        if (currentQueryController && currentQueryController.signal.aborted) {
            currentQueryController = null;
        } else if (currentQueryController) {
            currentQueryController = null;
        }
        input.disabled = false;
        input.focus();
    }
}

function appendMessage(role, text) {
    const messages = document.getElementById('rag-messages');
    const message = document.createElement('div');
    message.className = `rag-msg rag-msg--${role}`;

    if (role === 'ai') {
        const content = document.createElement('div');
        content.className = 'rag-msg__content';
        message.appendChild(content);
        if (text) {
            setAiMessageText(message, text);
        }
    } else {
        message.textContent = text;
    }

    messages.appendChild(message);
    messages.scrollTop = messages.scrollHeight;
    return message;
}

function setAiMessageText(message, text) {
    const content = ensureAiContent(message);
    content.textContent = text;
}

function renderAiMarkdown(message, markdownText) {
    const content = ensureAiContent(message);
    content.innerHTML = renderMarkdownSafe(markdownText);
    scrollRagMessagesToBottom();
}

function ensureAiContent(message) {
    let content = message.querySelector('.rag-msg__content');
    if (!content) {
        content = document.createElement('div');
        content.className = 'rag-msg__content';
        message.appendChild(content);
    }
    return content;
}

function renderCitations(message, citations) {
    const existing = message.querySelector('.citation-sources');
    if (existing) existing.remove();
    if (!citations || citations.length === 0) return;

    const wrapper = document.createElement('div');
    wrapper.className = 'citation-sources';

    const heading = document.createElement('div');
    heading.className = 'citation-heading';
    heading.textContent = '📚 参考来源';
    wrapper.appendChild(heading);

    citations.forEach((cite) => {
        const card = document.createElement('div');
        card.className = 'citation-card';

        const badge = document.createElement('span');
        badge.className = 'citation-index';
        badge.textContent = `[${cite.index}]`;

        const text = document.createElement('span');
        text.className = 'citation-preview';
        text.textContent = cite.preview || '无预览';

        const src = document.createElement('span');
        src.className = `score-tag ${sourceLabel(cite.source || 'semantic').cls}`;
        src.textContent = sourceLabel(cite.source || 'semantic').text;

        card.appendChild(badge);
        card.appendChild(text);
        card.appendChild(src);
        wrapper.appendChild(card);
    });

    const content = ensureAiContent(message);
    content.appendChild(wrapper);
    scrollRagMessagesToBottom();
}

function renderScoringExplain(message, scores) {
    const existing = message.querySelector('.thinking-process');
    if (existing) {
        existing.remove();
    }

    if (!scores || scores.length === 0) {
        return;
    }

    const wrapper = document.createElement('div');
    wrapper.className = 'thinking-process';

    const details = document.createElement('details');
    const summary = document.createElement('summary');
    summary.textContent = '展开 AI 思考过程（基于两阶段检索 + 个性化重排）';

    const list = document.createElement('div');
    list.className = 'thinking-list';

    scores.forEach((score, index) => {
        const item = document.createElement('div');
        item.className = 'thinking-item';

        const rank = document.createElement('div');
        rank.className = 'thinking-rank';
        rank.textContent = `#${index + 1}`;

        const content = document.createElement('div');
        content.className = 'thinking-content';

        const preview = document.createElement('div');
        preview.className = 'thinking-preview';
        preview.textContent = score.preview || '无预览';

        const badges = document.createElement('div');
        badges.className = 'thinking-scores';

        badges.appendChild(createScoreTag(sourceLabel(score.source).cls, sourceLabel(score.source).text));
        badges.appendChild(createScoreTag('relevance', `相关性: ${score.cross_score}`));
        if (score.bonus > 0) {
            badges.appendChild(createScoreTag('bonus', `个性化: +${score.bonus}`));
        }
        if (score.penalty > 0) {
            badges.appendChild(createScoreTag('penalty', `负反馈: -${score.penalty}`));
        }
        badges.appendChild(createScoreTag('total', `总分: ${score.total}`));

        content.appendChild(preview);
        content.appendChild(badges);

        item.appendChild(rank);
        item.appendChild(content);
        list.appendChild(item);
    });

    details.appendChild(summary);
    details.appendChild(list);
    wrapper.appendChild(details);
    message.insertBefore(wrapper, ensureAiContent(message));
}

function createScoreTag(type, text) {
    const tag = document.createElement('span');
    tag.className = `score-tag ${type}`;
    tag.textContent = text;
    return tag;
}

function sourceLabel(source) {
    const mapping = {
        semantic: { text: '语义', cls: 'source-semantic' },
        keyword: { text: '关键词', cls: 'source-keyword' },
        hybrid: { text: '混合命中', cls: 'source-hybrid' }
    };
    return mapping[source] || mapping.semantic;
}

function renderMarkdownSafe(text) {
    const rawHtml = typeof marked !== 'undefined'
        ? marked.parse(text)
        : `<p>${escapeHtml(text).replace(/\n/g, '<br>')}</p>`;

    const template = document.createElement('template');
    template.innerHTML = rawHtml;

    template.content.querySelectorAll('script, style, iframe, object, embed, link, img, svg, math, form, input, textarea, button, meta, base').forEach((node) => node.remove());

    template.content.querySelectorAll('*').forEach((node) => {
        [...node.attributes].forEach((attr) => {
            const name = attr.name.toLowerCase();
            const value = attr.value || '';
            if (name.startsWith('on')) {
                node.removeAttribute(attr.name);
                return;
            }
            if ((name === 'href' || name === 'src') && value && !isSafeHttpUrlString(value)) {
                node.removeAttribute(attr.name);
                return;
            }
            if (name === 'style') {
                node.removeAttribute(attr.name);
            }
        });

        if (node.tagName === 'A') {
            const href = node.getAttribute('href') || '';
            if (!isSafeHttpUrlString(href)) {
                const textNode = document.createTextNode(node.textContent || href);
                node.replaceWith(textNode);
                return;
            }
            node.setAttribute('target', '_blank');
            node.setAttribute('rel', 'noopener noreferrer');
        }
    });

    return template.innerHTML;
}

function escapeHtml(text) {
    return String(text ?? '')
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#39;');
}

function isSafeHttpUrlString(value) {
    try {
        const url = new URL(value);
        return url.protocol === 'http:' || url.protocol === 'https:';
    } catch {
        return false;
    }
}

function appendStaticIcon(element, svgMarkup) {
    const wrapper = document.createElement('span');
    wrapper.className = 'icon-inline';
    wrapper.innerHTML = svgMarkup;
    wrapper.setAttribute('aria-hidden', 'true');
    element.appendChild(wrapper);
}

function scrollRagMessagesToBottom() {
    const messages = document.getElementById('rag-messages');
    messages.scrollTop = messages.scrollHeight;
}

// ---------------------------------------------------------------
// Insights Panel
// ---------------------------------------------------------------

function toggleInsightsPanel() {
    const modal = document.getElementById('insights-modal');
    if (toggleOverlay(modal, '#heatmap-days')) {
        fetchHeatmap();
    }
}

async function fetchHeatmap() {
    const days = document.getElementById('heatmap-days').value;
    const container = document.getElementById('heatmap-container');
    container.innerHTML = '<p class="heatmap-placeholder">加载中...</p>';
    try {
        let url = `/api/v1/insights/heatmap?days=${days}`;
        if (currentBoardSlug) url += `&board=${encodeURIComponent(currentBoardSlug)}`;
        const res = await fetch(url);
        const data = await res.json();
        renderHeatmap(data, container);
    } catch (e) {
        container.innerHTML = '<p class="heatmap-placeholder">加载失败</p>';
    }
}

function renderHeatmap(data, container) {
    if (!data.topics || data.topics.length === 0) {
        container.innerHTML = '<p class="heatmap-placeholder">暂无足够历史数据</p>';
        return;
    }
    const dates = data.dates || [];
    const maxCount = Math.max(...data.topics.flatMap(t => t.counts), 1);

    // Build header row
    let html = `<div class="heatmap-grid" style="--cols:${dates.length}">`;
    html += '<div class="heatmap-label"></div>';
    for (const d of dates) {
        const short = d.slice(5); // "04-21"
        html += `<div class="heatmap-date">${short}</div>`;
    }

    for (const topic of data.topics) {
        html += `<div class="heatmap-label" title="${topic.name} (${topic.total})">${topic.name}</div>`;
        for (const c of topic.counts) {
            const opacity = c === 0 ? 0 : Math.max(0.15, c / maxCount);
            html += `<div class="heatmap-cell" style="opacity:${opacity}" title="${c}"></div>`;
        }
    }
    html += '</div>';
    container.innerHTML = html;
}

async function fetchEntityTimeline() {
    const entity = document.getElementById('entity-input').value.trim();
    if (!entity) return;
    const container = document.getElementById('timeline-container');
    container.innerHTML = '<p class="timeline-placeholder">搜索中...</p>';
    try {
        let url = `/api/v1/insights/timeline?entity=${encodeURIComponent(entity)}&days=30`;
        if (currentBoardSlug) url += `&board=${encodeURIComponent(currentBoardSlug)}`;
        const res = await fetch(url);
        const data = await res.json();
        renderTimeline(data, container);
    } catch (e) {
        container.innerHTML = '<p class="timeline-placeholder">搜索失败</p>';
    }
}

function renderTimeline(data, container) {
    if (!data.items || data.items.length === 0) {
        container.innerHTML = `<p class="timeline-placeholder">近 ${data.days} 天内未找到与"${data.entity}"相关的报道</p>`;
        return;
    }
    let html = `<p class="timeline-summary">近 ${data.days} 天共 <strong>${data.total}</strong> 条与"${data.entity}"相关的报道</p>`;
    html += '<div class="timeline-list">';
    for (const item of data.items) {
        html += `<div class="timeline-item">
            <span class="timeline-date">${item.date}</span>
            <span class="timeline-cat">${item.category}</span>
            <a href="${item.link}" target="_blank" class="timeline-headline">${item.headline}</a>
            <span class="timeline-source">${item.source}</span>
        </div>`;
    }
    html += '</div>';
    container.innerHTML = html;
}

// ---------------------------------------------------------------
// Explicit Preference Tags
// ---------------------------------------------------------------

let _prefSuggestionData = { sources: [], topics: [] };

async function loadExplicitPreferences() {
    try {
        let url = '/api/v1/preferences';
        if (currentBoardSlug) url += `?board=${encodeURIComponent(currentBoardSlug)}`;
        const res = await fetch(url);
        const data = await res.json();
        for (const cat of ['focus_topic', 'block_topic', 'prefer_source', 'avoid_source']) {
            renderPrefTags(cat, data[cat] || []);
        }
        _refreshAllSuggestions();
    } catch (e) {
        console.error('Failed to load preferences', e);
    }
}

function renderPrefTags(category, items) {
    const container = document.getElementById(`pref-tags-${category}`);
    if (!container) return;
    if (items.length === 0) {
        container.innerHTML = '<span class="pref-empty">暂无</span>';
        return;
    }
    container.innerHTML = items.map(item =>
        `<span class="pref-tag pref-tag-${category}">${item.content}<button class="pref-del" onclick="deletePrefTag(${item.id})">&times;</button></span>`
    ).join('');
}

async function addPrefTag(category) {
    const input = document.getElementById(`pref-input-${category}`);
    const content = input.value.trim();
    if (!content) return;
    try {
        let url = '/api/v1/persona';
        if (currentBoardSlug) url += `?board=${encodeURIComponent(currentBoardSlug)}`;
        await fetch(url, {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({content, category}),
        });
        input.value = '';
        loadExplicitPreferences();
    } catch (e) {
        console.error('Failed to add preference', e);
    }
}

async function deletePrefTag(id) {
    try {
        await fetch(`/api/v1/persona/${id}`, {method: 'DELETE'});
        loadExplicitPreferences();
    } catch (e) {
        console.error('Failed to delete preference', e);
    }
}

async function loadPrefSuggestions() {
    // Source suggestions: all enabled sources from DB + any extra names seen in today's data
    try {
        const res = await fetch('/api/v1/admin/sources/health');
        const rows = await res.json();
        const dbNames = rows.filter(r => r.enabled).map(r => r.name).filter(Boolean);
        const todayNames = latestData
            ? Object.keys(latestData.source_stats || computeSourceStats(latestData.top_news || []))
            : [];
        const merged = Array.from(new Set([...dbNames, ...todayNames])).sort();
        _prefSuggestionData.sources = merged;
    } catch (e) {
        console.error('Failed to load source list', e);
        if (latestData) {
            const stats = latestData.source_stats || computeSourceStats(latestData.top_news || []);
            _prefSuggestionData.sources = Object.keys(stats).sort();
        }
    }

    // Topic suggestions: fetch from trending API
    try {
        let url = '/api/v1/insights/trending?top_n=15';
        if (currentBoardSlug) url += `&board=${encodeURIComponent(currentBoardSlug)}`;
        const res = await fetch(url);
        const data = await res.json();
        _prefSuggestionData.topics = (data.trending || []).map(t => t.topic).filter(Boolean);
    } catch (e) {
        console.error('Failed to load trending topics for suggestions', e);
    }

    _refreshAllSuggestions();
}

function _refreshAllSuggestions() {
    _renderSuggestions('focus_topic',  _prefSuggestionData.topics);
    _renderSuggestions('block_topic',  _prefSuggestionData.topics);
    _renderSuggestions('prefer_source', _prefSuggestionData.sources);
    _renderSuggestions('avoid_source',  _prefSuggestionData.sources);
}

function _getExistingPrefValues(category) {
    const container = document.getElementById(`pref-tags-${category}`);
    if (!container) return new Set();
    return new Set(
        Array.from(container.querySelectorAll('.pref-tag')).map(el =>
            el.textContent.replace(/×$/, '').trim()
        )
    );
}

function _renderSuggestions(category, allItems) {
    const container = document.getElementById(`pref-suggestions-${category}`);
    if (!container) return;
    const existing = _getExistingPrefValues(category);
    const filtered = allItems.filter(item => !existing.has(item)).slice(0, 8);
    if (filtered.length === 0) {
        container.innerHTML = '';
        return;
    }
    const label = '<span class="pref-suggestion-label">快速添加</span>';
    const chips = filtered.map(item => {
        const escaped = item.replace(/\\/g, '\\\\').replace(/'/g, "\\'");
        return `<button class="pref-suggestion-chip" onclick="quickAddPref('${category}','${escaped}')">${item}</button>`;
    }).join('');
    container.innerHTML = label + chips;
}

async function quickAddPref(category, content) {
    const input = document.getElementById(`pref-input-${category}`);
    if (input) input.value = content;
    await addPrefTag(category);
}

// ==========================================
// Insights Panel (Heatmap + Entity Timeline)
// ==========================================

function toggleInsightsPanel() {
    const modal = document.getElementById('insights-modal');
    if (toggleOverlay(modal, '#heatmap-days')) {
        fetchHeatmap();
    }
}

async function fetchHeatmap() {
    const container = document.getElementById('heatmap-container');
    if (!container) return;
    const daysSelect = document.getElementById('heatmap-days');
    const days = daysSelect ? daysSelect.value : 7;

    container.innerHTML = '<p class="heatmap-placeholder">正在加载话题热度...</p>';

    try {
        const res = await fetch(`/api/v1/insights/heatmap?days=${days}`);
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        const data = await res.json();
        renderHeatmap(data, container);
    } catch (e) {
        console.error('Failed to fetch heatmap', e);
        container.innerHTML = `<p class="heatmap-placeholder">加载失败: ${e.message}</p>`;
    }
}

function renderHeatmap(data, container) {
    container.innerHTML = '';

    const dates = data.dates || [];
    const topics = data.topics || [];

    if (dates.length === 0 || topics.length === 0) {
        container.innerHTML = '<p class="heatmap-placeholder">暂无足够数据生成热度图</p>';
        return;
    }

    // Topics are already sorted by total from backend; take top 20
    const sortedTopics = topics.slice(0, 20);

    // Find global max for color scaling
    let maxCount = 0;
    for (const t of sortedTopics) {
        for (const c of t.counts) {
            if (c > maxCount) maxCount = c;
        }
    }
    if (maxCount === 0) maxCount = 1;

    // Format short dates for header
    const shortDates = dates.map(d => {
        const parts = d.split('-');
        return `${parts[1]}/${parts[2]}`;
    });

    // Build grid
    const table = document.createElement('div');
    table.className = 'heatmap-grid';
    table.style.cssText = `display: grid; grid-template-columns: 160px repeat(${dates.length}, 1fr); gap: 3px; font-size: 0.78rem;`;

    // Header row
    const cornerCell = document.createElement('div');
    cornerCell.className = 'heatmap-corner';
    cornerCell.style.cssText = 'font-weight: 600; color: var(--text-secondary); padding: 6px 8px;';
    cornerCell.textContent = '话题 / 日期';
    table.appendChild(cornerCell);

    for (const sd of shortDates) {
        const headerCell = document.createElement('div');
        headerCell.className = 'heatmap-date-header';
        headerCell.style.cssText = 'text-align: center; font-weight: 600; color: var(--text-secondary); padding: 6px 4px;';
        headerCell.textContent = sd;
        table.appendChild(headerCell);
    }

    // Data rows
    for (const topic of sortedTopics) {
        const labelCell = document.createElement('div');
        labelCell.className = 'heatmap-label';
        labelCell.style.cssText = 'color: var(--text-primary); padding: 6px 8px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; display: flex; align-items: center;';
        labelCell.textContent = topic.name;
        labelCell.title = `${topic.name} (总计: ${topic.total})`;
        table.appendChild(labelCell);

        for (let i = 0; i < dates.length; i++) {
            const count = topic.counts[i] || 0;
            const intensity = count / maxCount;
            const cell = document.createElement('div');
            cell.className = 'heatmap-cell';

            let bg, color;
            if (count === 0) {
                bg = 'rgba(255,255,255,0.03)';
                color = 'transparent';
            } else if (intensity < 0.33) {
                bg = 'rgba(99, 102, 241, 0.15)';
                color = 'rgba(165, 180, 252, 0.9)';
            } else if (intensity < 0.66) {
                bg = 'rgba(99, 102, 241, 0.35)';
                color = '#fff';
            } else {
                bg = 'rgba(99, 102, 241, 0.7)';
                color = '#fff';
            }

            cell.style.cssText = `background: ${bg}; color: ${color}; text-align: center; padding: 6px 4px; border-radius: 6px; font-weight: 600; font-size: 0.75rem; transition: all 0.2s; cursor: default;`;
            cell.textContent = count > 0 ? count : '';
            cell.title = `${topic.name} · ${dates[i]}: ${count} 条`;
            table.appendChild(cell);
        }
    }

    container.appendChild(table);
}

async function fetchEntityTimeline() {
    const input = document.getElementById('entity-input');
    const container = document.getElementById('timeline-container');
    if (!input || !container) return;

    const entity = input.value.trim();
    if (!entity) return;

    container.innerHTML = '<p class="timeline-placeholder">正在搜索...</p>';

    try {
        const res = await fetch(`/api/v1/insights/timeline?entity=${encodeURIComponent(entity)}&days=30`);
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        const data = await res.json();
        renderEntityTimeline(data, container);
    } catch (e) {
        console.error('Failed to fetch entity timeline', e);
        container.innerHTML = `<p class="timeline-placeholder">搜索失败: ${e.message}</p>`;
    }
}

function renderEntityTimeline(data, container) {
    container.innerHTML = '';

    if (!data.items || data.items.length === 0) {
        container.innerHTML = `<p class="timeline-placeholder">在最近 ${data.days || 30} 天内未找到与 "${data.entity}" 相关的资讯</p>`;
        return;
    }

    const header = document.createElement('div');
    header.style.cssText = 'margin-bottom: 1.25rem; color: var(--text-secondary); font-size: 0.85rem;';
    header.textContent = `找到 ${data.total} 条与 "${data.entity}" 相关的资讯（近 ${data.days} 天）`;
    container.appendChild(header);

    const timeline = document.createElement('div');
    timeline.className = 'entity-timeline';
    timeline.style.cssText = 'display: flex; flex-direction: column; gap: 0.75rem; position: relative; padding-left: 1.5rem; border-left: 2px solid rgba(99, 102, 241, 0.3);';

    for (const item of data.items) {
        const entry = document.createElement('div');
        entry.className = 'timeline-entry';
        entry.style.cssText = 'position: relative; padding: 1rem 1.25rem; background: var(--surface-color); border: 1px solid var(--border-color); border-radius: 12px; transition: all 0.3s ease; cursor: default;';

        // Dot on the timeline line
        const dot = document.createElement('div');
        dot.style.cssText = 'position: absolute; left: -2rem; top: 1.25rem; width: 10px; height: 10px; background: var(--accent-color); border-radius: 50%; box-shadow: 0 0 8px rgba(99,102,241,0.5);';
        entry.appendChild(dot);

        const dateLine = document.createElement('div');
        dateLine.style.cssText = 'font-size: 0.78rem; color: var(--accent-color); font-weight: 600; margin-bottom: 0.35rem;';
        dateLine.textContent = item.date || '';
        entry.appendChild(dateLine);

        const headline = document.createElement('div');
        headline.style.cssText = 'font-size: 0.95rem; color: var(--text-primary); font-weight: 600; margin-bottom: 0.3rem; line-height: 1.4;';
        headline.textContent = item.headline || '未命名';
        entry.appendChild(headline);

        if (item.source) {
            const source = document.createElement('div');
            source.style.cssText = 'font-size: 0.78rem; color: var(--text-secondary);';
            source.textContent = `来源: ${item.source}`;
            entry.appendChild(source);
        }

        timeline.appendChild(entry);
    }

    container.appendChild(timeline);
}

// ==========================================
// Stats Panel
// ==========================================

function toggleStatsPanel() {
    const modal = document.getElementById('stats-modal');
    if (!modal) return;
    toggleOverlay(modal, '.metrics-refresh-btn');
}

// Sources Management Panel
// ==========================================

function toggleSourcesPanel() {
    const modal = document.getElementById('sources-modal');
    if (!modal) return;
    if (toggleOverlay(modal, '#new-source-url')) {
        loadSourcesForCurrentBoard();
    }
}

function _getCurrentBoardObj() {
    if (!currentBoardSlug || !availableBoards.length) return null;
    return availableBoards.find(b => b.slug === currentBoardSlug) || null;
}

async function loadSourcesForCurrentBoard() {
    const listEl = document.getElementById('sources-feed-list');
    const labelEl = document.getElementById('sources-board-label');
    const board = _getCurrentBoardObj();

    if (!board) {
        labelEl.textContent = '当前板块: --';
        listEl.innerHTML = '<p class="sources-placeholder">未选择板块</p>';
        return;
    }

    labelEl.textContent = `${board.icon || ''} ${board.name} (${board.source_type})`.trim();

    // For RSS and multi-source boards, extract feeds from source_config
    const config = board.source_config || {};
    let feeds = [];

    if (board.source_type === 'rss') {
        feeds = config.feeds || [];
    } else if (board.source_type === 'multi') {
        // Multi-source: extract RSS feeds if any
        const sources = config.sources || {};
        if (sources.rss && sources.rss.feeds) {
            feeds = sources.rss.feeds;
        }
    }

    if (feeds.length === 0) {
        listEl.innerHTML = '<p class="sources-placeholder">此板块暂无配置 RSS 信息源</p>';
        return;
    }

    renderFeedList(feeds, listEl);
}

function renderFeedList(feeds, container) {
    container.innerHTML = '';
    feeds.forEach((url, index) => {
        const item = document.createElement('div');
        item.className = 'source-feed-item';
        item.id = `source-item-${index}`;

        item.innerHTML = `
            <span class="source-feed-index">${index + 1}</span>
            <span class="source-feed-url">${url}</span>
            <span class="source-feed-status" id="source-status-${index}"></span>
            <div class="source-feed-actions">
                <button class="source-feed-test-btn" onclick="testExistingFeed(${index}, '${url.replace(/'/g, "\\'")}')">测试</button>
                <button class="source-feed-del-btn" onclick="deleteSourceFeed(${index})">删除</button>
            </div>
        `;
        container.appendChild(item);
    });
}

async function testSourceFeed() {
    const input = document.getElementById('new-source-url');
    const resultEl = document.getElementById('source-test-result');
    const url = input.value.trim();

    if (!url) return;

    resultEl.style.display = 'block';
    resultEl.className = 'source-test-result';
    resultEl.innerHTML = '<span style="animation: pulseText 1.5s infinite;">正在测试连接...</span>';

    try {
        const res = await fetch('/api/v1/sources/test', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({url}),
        });
        const data = await res.json();

        if (data.ok) {
            resultEl.className = 'source-test-result test-ok';
            const samples = data.sample_titles.map(t => `<li>${t}</li>`).join('');
            resultEl.innerHTML = `
                <strong>✓ 连接成功</strong> — ${data.feed_title}<br>
                <span style="opacity:0.8;">共 ${data.article_count} 篇文章</span>
                ${samples ? `<ul style="margin: 0.5rem 0 0 1rem; opacity: 0.8; font-size: 0.8rem;">${samples}</ul>` : ''}
            `;
        } else {
            resultEl.className = 'source-test-result test-fail';
            resultEl.innerHTML = `<strong>✗ 连接失败</strong> — ${data.error}`;
        }
    } catch (e) {
        resultEl.className = 'source-test-result test-fail';
        resultEl.innerHTML = `<strong>✗ 请求异常</strong> — ${e.message}`;
    }
}

async function testExistingFeed(index, url) {
    const statusEl = document.getElementById(`source-status-${index}`);
    if (!statusEl) return;

    statusEl.className = 'source-feed-status status-testing';
    statusEl.textContent = '测试中…';

    try {
        const res = await fetch('/api/v1/sources/test', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({url}),
        });
        const data = await res.json();

        if (data.ok) {
            statusEl.className = 'source-feed-status status-ok';
            statusEl.textContent = `✓ ${data.article_count}篇`;
            statusEl.title = data.feed_title;
        } else {
            statusEl.className = 'source-feed-status status-fail';
            statusEl.textContent = `✗ ${data.error || '失败'}`;
            statusEl.title = data.error;
        }
    } catch (e) {
        statusEl.className = 'source-feed-status status-fail';
        statusEl.textContent = '✗ 异常';
        statusEl.title = e.message;
    }
}

async function _updateBoardFeeds(newFeeds) {
    const board = _getCurrentBoardObj();
    if (!board) return;

    let newConfig;
    if (board.source_type === 'rss') {
        newConfig = {...(board.source_config || {}), feeds: newFeeds};
    } else if (board.source_type === 'multi') {
        const oldConfig = board.source_config || {};
        const sources = oldConfig.sources || {};
        sources.rss = {...(sources.rss || {}), feeds: newFeeds};
        newConfig = {...oldConfig, sources};
    } else {
        return;
    }

    const res = await fetch(`/api/v1/boards/${encodeURIComponent(board.slug)}`, {
        method: 'PATCH',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({source_config: newConfig}),
    });

    if (!res.ok) {
        const detail = await res.text();
        throw new Error(detail);
    }

    // Update the local board object so UI stays in sync
    const updated = await res.json();
    board.source_config = updated.source_config;
    // Also update the availableBoards array
    const idx = availableBoards.findIndex(b => b.slug === board.slug);
    if (idx !== -1) availableBoards[idx] = {...availableBoards[idx], source_config: updated.source_config};
}

function _getCurrentFeeds() {
    const board = _getCurrentBoardObj();
    if (!board) return [];
    const config = board.source_config || {};
    if (board.source_type === 'rss') return [...(config.feeds || [])];
    if (board.source_type === 'multi') {
        const sources = config.sources || {};
        return [...(sources.rss?.feeds || [])];
    }
    return [];
}

async function addSourceFeed() {
    const input = document.getElementById('new-source-url');
    const url = input.value.trim();
    if (!url) return;

    const feeds = _getCurrentFeeds();
    if (feeds.includes(url)) {
        alert('此信息源已存在');
        return;
    }

    feeds.push(url);

    try {
        await _updateBoardFeeds(feeds);
        input.value = '';
        document.getElementById('source-test-result').style.display = 'none';
        loadSourcesForCurrentBoard();
    } catch (e) {
        alert('添加失败: ' + e.message);
    }
}

async function deleteSourceFeed(index) {
    const feeds = _getCurrentFeeds();
    if (index < 0 || index >= feeds.length) return;

    const removed = feeds[index];
    if (!confirm(`确认删除此信息源？\n${removed}`)) return;

    feeds.splice(index, 1);

    try {
        await _updateBoardFeeds(feeds);
        loadSourcesForCurrentBoard();
    } catch (e) {
        alert('删除失败: ' + e.message);
    }
}


// -----------------------------------------------------------------------
// Catch-up Digest (精炼补读)
// -----------------------------------------------------------------------

async function _refreshCatchupBadge() {
    try {
        let url = '/api/v1/catchup/status';
        if (currentBoardSlug) url += `?board=${encodeURIComponent(currentBoardSlug)}`;
        const resp = await fetch(url);
        if (!resp.ok) return;
        const data = await resp.json();
        const count = (data.unviewed_count || 0) + (data.gap_count || 0);
        const badge = document.getElementById('catchup-badge');
        if (badge) {
            if (count > 0) {
                badge.textContent = count;
                badge.style.display = 'inline';
            } else {
                badge.style.display = 'none';
            }
        }
    } catch (_) { /* non-critical */ }
}

function toggleCatchupPanel() {
    const panel = document.getElementById('catchup-modal');
    if (toggleOverlay(panel, '#catchup-gen-btn')) {
        _loadCatchupStatus();
    }
}

async function _loadCatchupStatus() {
    const statusEl = document.getElementById('catchup-status');
    const genBtn = document.getElementById('catchup-gen-btn');
    if (!statusEl) return;

    try {
        let url = '/api/v1/catchup/status';
        if (currentBoardSlug) url += `?board=${encodeURIComponent(currentBoardSlug)}`;
        const resp = await fetch(url);
        if (!resp.ok) throw new Error('Failed');
        const data = await resp.json();

        const unviewed = data.unviewed_count || 0;
        const gaps = data.gap_count || 0;
        const total = unviewed + gaps;

        if (total === 0) {
            statusEl.innerHTML = '<p class="catchup-placeholder"><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round" style="margin-right: 0.3rem; vertical-align: middle;"><polyline points="20 6 9 17 4 12"></polyline></svg> 所有内容都已阅读，无需补读</p>';
            if (genBtn) genBtn.style.display = 'none';
        } else {
            let msg = '';
            if (unviewed > 0) msg += `${unviewed} 天未读`;
            if (gaps > 0) msg += `${unviewed > 0 ? ' + ' : ''}${gaps} 天未采集`;
            statusEl.innerHTML = `<p class="catchup-status-text">${msg} 的内容待补读</p>`;
            if (genBtn) genBtn.style.display = '';
        }
    } catch (_) {
        statusEl.innerHTML = '<p class="catchup-placeholder">检查未读状态失败</p>';
    }
}

async function triggerCatchupDigest() {
    const contentEl = document.getElementById('catchup-content');
    const genBtn = document.getElementById('catchup-gen-btn');
    const statusEl = document.getElementById('catchup-status');

    if (!contentEl) return;

    // Show loading
    contentEl.innerHTML = '<p class="catchup-placeholder">AI 编辑正在精炼未读内容，请稍候...</p>';
    if (genBtn) {
        genBtn.disabled = true;
        genBtn.textContent = '生成中...';
    }

    try {
        let url = '/api/v1/catchup';
        if (currentBoardSlug) url += `?board=${encodeURIComponent(currentBoardSlug)}`;
        const resp = await fetch(url, { method: 'POST' });
        if (!resp.ok) {
            const errData = await resp.json().catch(() => ({}));
            throw new Error(errData.detail || 'Failed');
        }
        const data = await resp.json();

        if (!data.digest) {
            contentEl.innerHTML = '<p class="catchup-placeholder">没有可补读的内容。</p>';
        } else {
            const digestData = data.digest;
            let rangeInfo = '';
            if (data.dates_covered && data.dates_covered.length > 0) {
                rangeInfo = `<div class="catchup-range">覆盖日期：${data.dates_covered.map(d => formatSummaryDate(d)).join('、')}</div>`;
                if (data.backfilled_dates && data.backfilled_dates.length > 0) {
                    rangeInfo += `<div class="catchup-backfill">已补采：${data.backfilled_dates.map(d => formatSummaryDate(d)).join('、')}</div>`;
                }
            }

            let html = rangeInfo;
            if (digestData.overview) {
                html += `<div class="catchup-overview">${digestData.overview}</div>`;
            }
            if (Array.isArray(digestData.top_news)) {
                html += '<div class="catchup-news-list">';
                digestData.top_news.forEach(item => {
                    html += `<div class="catchup-news-item">
                        <div class="catchup-news-headline">${item.headline || item.title || ''}</div>
                        <div class="catchup-news-meta">
                            <span class="catchup-news-category">${item.category || ''}</span>
                            ${item.source ? `<span class="catchup-news-source">${item.source}</span>` : ''}
                        </div>
                        ${Array.isArray(item.key_points) && item.key_points.length > 0
                            ? `<ul class="catchup-news-points">${item.key_points.map(p => `<li>${p}</li>`).join('')}</ul>`
                            : ''}
                        ${item.original_link ? `<a class="catchup-news-link" href="${item.original_link}" target="_blank" rel="noopener">阅读原文 ${ICONS.external}</a>` : ''}
                    </div>`;
                });
                html += '</div>';
            }
            contentEl.innerHTML = html;
        }

        // Refresh badge
        _refreshCatchupBadge();
    } catch (error) {
        contentEl.innerHTML = `<p class="catchup-placeholder">生成失败：${error.message}</p>`;
    } finally {
        if (genBtn) {
            genBtn.disabled = false;
            genBtn.textContent = '生成精炼补读';
        }
    }
}

function filterHistoryByViewed() {
    const checkbox = document.getElementById('history-unread-only');
    const showUnreadOnly = checkbox && checkbox.checked;
    const items = document.querySelectorAll('#history-list .history-item');
    items.forEach(item => {
        if (showUnreadOnly) {
            item.style.display = item.classList.contains('history-item--unviewed') ? '' : 'none';
        } else {
            item.style.display = '';
        }
    });
}
