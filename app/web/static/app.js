let latestData = null;
let eventsByCluster = {};
let currentUrl = null;
let isIngesting = false;
let currentQueryController = null;
let currentOverviewController = null;
let _summaryAbortController = null;
let _summaryFetchId = 0;
let latestHistoryArchive = [];
let _historyInsightsLoaded = false;  // track if insights tab has been loaded
let currentBoardSlug = null;
let availableBoards = [];
let currentBoardSources = [];
let currentSourceDashboard = null;
let currentCoverageAnalysis = null;
let currentCoverageContext = null;
let currentCoverageFocusClusterId = null;
let currentCoverageRequestId = 0;
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
    'history-modal': '往日',
    'catchup-modal': '精炼补读',
    'magazine-modal': '本周深度周刊',
    'sources-modal': '信息源管理',
    'coverage-modal': '报道差异分析',
    'refresh-modal': '重新调教简报',
    'stats-modal': '数据统计',
    'board-modal': '板块管理',
    'saved-modal': '我的收藏',
    'rag-panel': '深度追问'
};
const SOURCE_CREDIBILITY_OPTIONS = [
    { value: '', label: '自动判断' },
    { value: 'official', label: '官方/一手' },
    { value: 'established', label: '成熟媒体' },
    { value: 'specialist', label: '垂直专家' },
    { value: 'community', label: '社区线索' },
    { value: 'aggregator', label: '聚合转载' },
    { value: 'mirror', label: '镜像搬运' },
    { value: 'ai_generated', label: 'AI 生成' },
    { value: 'risky', label: '高风险' },
];
const SOURCE_CREDIBILITY_LABELS = SOURCE_CREDIBILITY_OPTIONS.reduce((acc, item) => {
    acc[item.value] = item.label;
    return acc;
}, {});

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
    document.documentElement.classList.add('theme-transitioning');
    const isLight = document.documentElement.classList.toggle('light-mode');
    try { localStorage.setItem('argos-theme', isLight ? 'light' : 'dark'); } catch (_) {}
    _updateThemeIcon();
    setTimeout(() => document.documentElement.classList.remove('theme-transitioning'), 300);
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
        ['coverage-modal', closeCoverageModal],
        ['sources-modal', toggleSourcesPanel],
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
        html += `<div class="board-tab-wrapper ${isActive}" draggable="true" data-slug="${escapeHtml(b.slug || '')}" data-index="${i}">
            <button class="board-tab ${isActive} js-board-switch" data-board-slug="${escapeHtml(b.slug || '')}">
                ${escapeHtml(b.icon || '')} ${escapeHtml(b.name || '')}
            </button>
            <button class="board-edit-btn js-board-edit" data-board-slug="${escapeHtml(b.slug || '')}" title="设置此板块">⚙️</button>
        </div>`;
    }
    html += `<button class="board-add-btn js-board-add" title="新建板块">➕ 添加板块</button>`;
    container.innerHTML = html;
    container.querySelectorAll('.js-board-switch').forEach((button) => {
        button.addEventListener('click', () => switchBoard(button.dataset.boardSlug || ''));
    });
    container.querySelectorAll('.js-board-edit').forEach((button) => {
        button.addEventListener('click', () => openBoardModal(button.dataset.boardSlug || null));
    });
    container.querySelector('.js-board-add')?.addEventListener('click', () => openBoardModal());
    
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

    // Reset insights tab state for new board
    _historyInsightsLoaded = false;

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
let wizardLastSourceValidation = null; // most recent validation result
let wizardLastDiscoveryReport = null;
let wizardLastPreviewData = null;
let wizardLastPreviewError = '';
let wizardIsLoading = false;
let wizardTopic = '';              // derived topic for feed-fix requests
let wizardBrokenFeeds = new Set(); // broken feed URLs not yet replaced

function clearWizardReviewState() {
    wizardLastSourceValidation = null;
    wizardLastDiscoveryReport = null;
    wizardLastPreviewData = null;
    wizardLastPreviewError = '';
    wizardBrokenFeeds = new Set();
}

function clearWizardReviewPanel() {
    const reviewPanel = document.getElementById('wizard-review-panel');
    if (reviewPanel) {
        reviewPanel.style.display = 'none';
        reviewPanel.innerHTML = '';
    }
    const applyRow = document.getElementById('wizard-apply-row');
    if (applyRow) applyRow.style.display = 'none';
    const previewBtn = document.getElementById('wizard-preview-btn');
    if (previewBtn) {
        previewBtn.style.display = 'inline-flex';
        previewBtn.disabled = false;
        previewBtn.textContent = '预览抓取效果';
    }
}

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

    clearWizardReviewState();
    clearWizardReviewPanel();
    wizardTopic = '';
    wizardLastConfig = JSON.parse(JSON.stringify(tpl));
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
    clearWizardReviewState();
    wizardIsLoading = false;
    wizardTopic = '';
    const messagesDiv = document.getElementById('wizard-messages');
    if (messagesDiv) {
        messagesDiv.innerHTML = `<div class="wizard-msg wizard-msg--ai">告诉我你想要一个什么样的板块，比如：<br>"我想每天学 5 个英语商务单词"，<br>"汇总国内外顶级 AI 实验室的最新论文"，<br>"每天给我一条冷门心理学知识"...</div>`;
    }
    clearWizardReviewPanel();
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
        div.innerHTML = renderMarkdownSafe(content);
    } else {
        div.textContent = content;
    }
    container.appendChild(div);
    container.scrollTop = container.scrollHeight;
    return div;
}

function getWizardSourceTypeLabel(sourceType) {
    const typeLabels = {
        rss: 'RSS 订阅源',
        pure_llm: '纯 LLM 生成',
        hackernews: 'Hacker News 热帖',
        reddit: 'Reddit 社区',
        github: 'GitHub 动态',
        multi: '混合数据源',
    };
    return typeLabels[sourceType] || sourceType || '未知类型';
}

function renderWizardReviewPanel() {
    const panel = document.getElementById('wizard-review-panel');
    const applyRow = document.getElementById('wizard-apply-row');
    const previewBtn = document.getElementById('wizard-preview-btn');
    const applyHint = document.getElementById('wizard-apply-hint');
    if (!panel) return;

    if (!wizardLastConfig) {
        panel.style.display = 'none';
        panel.innerHTML = '';
        if (applyRow) applyRow.style.display = 'none';
        return;
    }

    const cfg = wizardLastConfig;
    const validation = Array.isArray(wizardLastSourceValidation) ? wizardLastSourceValidation : [];
    const discovery = wizardLastDiscoveryReport || {};
    const preview = wizardLastPreviewData;
    const brokenCount = wizardBrokenFeeds.size;
    const okSources = validation.filter(item => item && item.ok);
    const failedSources = validation.filter(item => item && !item.ok);
    const selectedSources = Array.isArray(discovery.selected) ? discovery.selected : [];
    const droppedSources = Array.isArray(discovery.dropped) ? discovery.dropped : [];
    const previewSources = Array.isArray(preview?.sources) ? preview.sources : [];
    const previewSamples = previewSources
        .filter(item => item.ok && Array.isArray(item.sample_titles) && item.sample_titles.length > 0)
        .slice(0, 3);
    const issueBits = [];
    if (brokenCount > 0) {
        issueBits.push(`仍有 ${brokenCount} 个失效源待替换，应用到表单时会自动移除。`);
    }
    if (droppedSources.length > 0) {
        issueBits.push(`已过滤 ${droppedSources.length} 个高风险候选源。`);
    }
    if (!okSources.length && validation.length > 0) {
        issueBits.push('当前没有通过验证的来源，建议继续调整。');
    }

    panel.style.display = 'block';
    panel.innerHTML = `
        <div class="wizard-review-card">
            <div class="wizard-review-card__head">
                <div>
                    <div class="wizard-review-card__eyebrow">向导评审</div>
                    <h4 class="wizard-review-card__title">${escapeHtml(`${cfg.icon || '❖'} ${cfg.name || '未命名板块'}`.trim())}</h4>
                    <p class="wizard-review-card__subtitle">${escapeHtml(getWizardSourceTypeLabel(cfg.source_type))} · slug: ${escapeHtml(cfg.slug || '--')}</p>
                </div>
                <div class="wizard-review-card__chips">
                    <span class="wizard-review-chip">${escapeHtml(String(okSources.length))} 个可用源</span>
                    <span class="wizard-review-chip">${escapeHtml(String(failedSources.length))} 个失败源</span>
                    ${discovery.safe_count != null ? `<span class="wizard-review-chip">${escapeHtml(String(discovery.safe_count))} 个非 risky 候选</span>` : ''}
                </div>
            </div>

            <div class="wizard-review-grid">
                <section class="wizard-review-section">
                    <div class="wizard-review-section__title">来源筛选</div>
                    <p class="wizard-review-section__summary">${escapeHtml(discovery.summary || '已基于可用性和可信度生成推荐来源。')}</p>
                    ${selectedSources.length ? `
                        <div class="wizard-review-source-list">
                            ${selectedSources.slice(0, 4).map(item => `
                                <div class="wizard-review-source-item is-ok">
                                    <div class="wizard-review-source-item__top">
                                        <span class="wizard-review-source-item__name">${escapeHtml(item.feed_title || item.label || item.url || '候选源')}</span>
                                        <span class="wizard-review-source-item__meta">${escapeHtml(item.trust_label || 'unknown')} trust${item.trust_score != null ? ` ${escapeHtml(String(item.trust_score))}` : ''}</span>
                                    </div>
                                    <div class="wizard-review-source-item__sub">${escapeHtml(item.selection_reason || item.quality_summary || '已纳入推荐配置。')}</div>
                                </div>
                            `).join('')}
                        </div>
                    ` : '<p class="wizard-review-empty">当前没有结构化候选摘要，将直接使用验证结果。</p>'}
                </section>

                <section class="wizard-review-section">
                    <div class="wizard-review-section__title">最终验证</div>
                    <p class="wizard-review-section__summary">这些是当前配置里真正会进入板块的数据源状态。</p>
                    <div class="wizard-review-source-list">
                        ${validation.length ? validation.slice(0, 5).map(item => `
                            <div class="wizard-review-source-item ${item.ok ? 'is-ok' : 'is-fail'}">
                                <div class="wizard-review-source-item__top">
                                    <span class="wizard-review-source-item__name">${escapeHtml(item.label || item.url || '数据源')}</span>
                                    <span class="wizard-review-source-item__meta">${item.ok ? '可用' : '失败'}${item.trust_label ? ` · ${escapeHtml(item.trust_label)} trust` : ''}</span>
                                </div>
                                <div class="wizard-review-source-item__sub">${escapeHtml(item.ok ? (item.quality_summary || `${item.article_count || 0} 篇样本`) : (item.error || '验证失败'))}</div>
                            </div>
                        `).join('') : '<p class="wizard-review-empty">还没有验证数据。</p>'}
                    </div>
                </section>
            </div>

            <section class="wizard-review-section">
                <div class="wizard-review-section__title">抓取预览</div>
                ${preview ? `
                    <p class="wizard-review-section__summary">${escapeHtml(preview.quality_report?.summary || `本次预览共抓取 ${preview.total_articles || 0} 篇文章。`)}</p>
                    <div class="wizard-review-card__chips">
                        <span class="wizard-review-chip">${escapeHtml(String(preview.total_articles || 0))} 篇样本</span>
                        <span class="wizard-review-chip">${escapeHtml(String((preview.sources || []).filter(item => item.ok).length))} 个源返回内容</span>
                        ${preview.quality_report ? `<span class="wizard-review-chip">${escapeHtml(String(preview.quality_report.dropped_count || 0))} 个被建议放弃</span>` : ''}
                    </div>
                    ${previewSamples.length ? `
                        <div class="wizard-review-preview-list">
                            ${previewSamples.map(item => `
                                <div class="wizard-review-preview-item">
                                    <div class="wizard-review-preview-item__name">${escapeHtml(item.feed_title || item.label || item.url || '数据源')}</div>
                                    <div class="wizard-review-preview-item__samples">${(item.sample_titles || []).slice(0, 2).map(title => escapeHtml(title)).join(' · ')}</div>
                                </div>
                            `).join('')}
                        </div>
                    ` : '<p class="wizard-review-empty">预览已完成，但暂时没有代表样本标题。</p>'}
                ` : wizardLastPreviewError ? `
                    <p class="wizard-review-section__summary is-warning">预览失败：${escapeHtml(wizardLastPreviewError)}</p>
                ` : `
                    <p class="wizard-review-section__summary">还没有执行抓取预览。建议在应用前先看一下样本质量。</p>
                `}
            </section>

            ${issueBits.length ? `
                <section class="wizard-review-section is-warning">
                    <div class="wizard-review-section__title">待处理问题</div>
                    <div class="wizard-review-issues">
                        ${issueBits.map(item => `<div class="wizard-review-issue">${escapeHtml(item)}</div>`).join('')}
                    </div>
                </section>
            ` : ''}
        </div>
    `;

    if (applyRow) applyRow.style.display = 'flex';
    if (applyHint) {
        applyHint.innerHTML = `<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round" style="margin-right: 0.3rem; vertical-align: middle;"><polyline points="20 6 9 17 4 12"></polyline></svg>${issueBits.length ? '先处理问题或查看预览，再应用到表单' : '推荐配置已准备好，可直接应用到表单'}`;
    }
    if (previewBtn) {
        const isPureLlm = cfg.source_type === 'pure_llm';
        previewBtn.style.display = isPureLlm ? 'none' : 'inline-flex';
        if (!previewBtn.disabled) {
            previewBtn.textContent = preview ? '重新预览抓取' : '预览抓取效果';
        }
    }
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
        const payload = { messages: wizardMessages };
        if (wizardLastConfig) {
            payload.current_config = wizardLastConfig;
        }
        if (wizardLastSourceValidation) {
            payload.source_validation = wizardLastSourceValidation;
        }

        const res = await fetch('/api/v1/boards/wizard', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload),
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
            wizardLastSourceValidation = data.source_validation || null;
            wizardLastDiscoveryReport = data.source_discovery_report || null;
            wizardLastPreviewData = null;
            wizardLastPreviewError = '';
            // Derive a topic string for later feed-fix requests.
            wizardTopic = `${data.config.name || ''} ${data.config.system_prompt || ''}`.trim();
            // Summary preview
            const cfg = data.config;
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
- 类型：${getWizardSourceTypeLabel(cfg.source_type)}
${sourceDetail}`;
            appendWizardMsg('ai', preview);
            if (data.source_discovery_report) {
                renderWizardDiscoveryReport(data.source_discovery_report);
            }

            // RSS/Multi feeds: render per-URL validation status
            if (wizardLastSourceValidation && wizardLastSourceValidation.length > 0) {
                renderWizardSourceStatus(wizardLastSourceValidation);
                
                // For RSS: trigger auto-fix if any feeds are broken
                if (isRss) {
                    const broken = wizardLastSourceValidation.filter(v => v.source_type === 'rss' && !v.ok).map(v => v.url);
                    if (broken.length > 0) {
                        fixWizardFeeds(broken);
                    }
                }
            }
            renderWizardReviewPanel();
        } else {
            wizardLastConfig = null;
            clearWizardReviewState();
            renderWizardReviewPanel();
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

function renderWizardSourceStatus(validation) {
    const container = document.getElementById('wizard-messages');

    // Track broken RSS feeds so applyWizardConfig can drop unresolved ones.
    wizardBrokenFeeds = new Set(
        (validation || []).filter(v => v.source_type === 'rss' && !v.ok).map(v => v.url)
    );

    const card = document.createElement('div');
    card.className = 'wizard-msg wizard-msg--ai wizard-feed-status';
    const title = document.createElement('div');
    title.className = 'wizard-feed-title';
    title.textContent = '内容源状态';
    card.appendChild(title);

    validation.forEach(v => {
        const row = document.createElement('div');
        let state = 'pending', icon = '…', meta = '检测中';
        if (v && v.ok) {
            state = 'ok'; icon = '✓';
            meta = v.source_type === 'pure_llm' ? 'AI 原创内容，无需抓取' : '正常';
        } else if (v) { state = 'fail'; icon = '✗'; meta = v.error || '失败'; }
        row.className = `wizard-feed-row wizard-feed-row--${state}`;
        
        const typeEl = document.createElement('span');
        typeEl.className = 'wizard-feed-type';
        typeEl.textContent = `[${v.source_type}]`;
        typeEl.style.color = 'var(--text-secondary)';
        typeEl.style.fontSize = '0.7rem';
        typeEl.style.marginRight = '0.3rem';

        const iconEl = document.createElement('span');
        iconEl.className = 'wizard-feed-icon';
        iconEl.textContent = icon;
        
        const urlEl = document.createElement('span');
        urlEl.className = 'wizard-feed-url';
        urlEl.textContent = v.label || v.url;
        
        const metaEl = document.createElement('span');
        metaEl.className = 'wizard-feed-meta';
        const trustText = v?.trust_label ? ` · ${v.trust_label} trust${v.trust_score != null ? ` ${v.trust_score}` : ''}` : '';
        metaEl.textContent = `${meta}${trustText}`;
        
        row.append(iconEl, typeEl, urlEl, metaEl);
        if (v?.quality_summary) {
            const noteEl = document.createElement('div');
            noteEl.className = 'wizard-feed-note';
            noteEl.textContent = v.quality_summary;
            card.appendChild(row);
            card.appendChild(noteEl);
            return;
        }
        card.appendChild(row);
    });

    const hint = document.createElement('div');
    hint.className = 'wizard-feed-note';
    hint.style.marginTop = '0.7rem';
    hint.style.marginLeft = '0';
    hint.textContent = (wizardLastConfig || {}).source_type === 'pure_llm'
        ? '纯 LLM 内容无需抓取，评审区会直接展示推荐配置。'
        : '继续看下方评审区，你可以先预览抓取效果，再决定是否应用到表单。';
    card.appendChild(hint);

    container.appendChild(card);
    container.scrollTop = container.scrollHeight;
    return card;
}

function renderWizardDiscoveryReport(report) {
    if (!report) return;
    const container = document.getElementById('wizard-messages');
    const card = document.createElement('div');
    card.className = 'wizard-msg wizard-msg--ai wizard-feed-status';

    const title = document.createElement('div');
    title.className = 'wizard-feed-title';
    title.textContent = '来源质量筛选';
    card.appendChild(title);

    const summary = document.createElement('div');
    summary.className = 'wizard-feed-note';
    summary.textContent = report.summary || '已按来源质量完成初筛。';
    card.appendChild(summary);

    const selected = Array.isArray(report.selected) ? report.selected : [];
    if (selected.length > 0) {
        selected.slice(0, 3).forEach(entry => {
            const row = document.createElement('div');
            row.className = 'wizard-feed-row wizard-feed-row--ok';
            row.innerHTML = `
                <span class="wizard-feed-icon">✓</span>
                <span class="wizard-feed-url">${escapeHtml(entry.label || entry.url || entry.source_type || '候选源')}</span>
                <span class="wizard-feed-meta">${escapeHtml(entry.trust_label || 'unknown')} trust${entry.trust_score != null ? ` ${escapeHtml(String(entry.trust_score))}` : ''}</span>
            `;
            card.appendChild(row);
        });
    }

    const dropped = Array.isArray(report.dropped) ? report.dropped : [];
    if (dropped.length > 0) {
        const droppedHead = document.createElement('div');
        droppedHead.className = 'wizard-feed-title';
        droppedHead.style.marginTop = '0.8rem';
        droppedHead.style.fontSize = '0.82rem';
        droppedHead.textContent = '已过滤的高风险来源';
        card.appendChild(droppedHead);

        dropped.slice(0, 3).forEach(entry => {
            const row = document.createElement('div');
            row.className = 'wizard-feed-row wizard-feed-row--fail';
            row.innerHTML = `
                <span class="wizard-feed-icon">✗</span>
                <span class="wizard-feed-url">${escapeHtml(entry.label || entry.url || entry.source_type || '候选源')}</span>
                <span class="wizard-feed-meta">${escapeHtml(entry.trust_label || 'risky')} trust${entry.trust_score != null ? ` ${escapeHtml(String(entry.trust_score))}` : ''}</span>
            `;
            card.appendChild(row);

            if (entry.selection_reason) {
                const note = document.createElement('div');
                note.className = 'wizard-feed-note';
                note.textContent = entry.selection_reason;
                card.appendChild(note);
            }
        });
    }

    container.appendChild(card);
    container.scrollTop = container.scrollHeight;
}

async function triggerWizardPreview(btn) {
    if (!wizardLastConfig) return;
    btn.disabled = true;
    btn.textContent = '抓取中...';
    
    const container = document.getElementById('wizard-messages');
    const loadingMsg = appendWizardMsg('ai', '📊 正在测试抓取，请稍候...');
    
    try {
        const res = await fetch('/api/v1/boards/wizard/preview', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ config: wizardLastConfig }),
        });
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        const data = await res.json();
        loadingMsg.remove();
        wizardLastPreviewData = data;
        wizardLastPreviewError = '';

        if (data.quality_report?.summary) {
            appendWizardMsg('ai', `质量预览：${data.quality_report.summary}`);
        }
        
        const card = document.createElement('div');
        card.className = 'wizard-msg wizard-msg--ai wizard-feed-status';
        
        const title = document.createElement('div');
        title.className = 'wizard-feed-title';
        title.textContent = `预览结果: 共抓取 ${data.total_articles || 0} 篇文章`;
        card.appendChild(title);

        (data.sources || []).forEach(v => {
            const row = document.createElement('div');
            row.style.marginBottom = '0.5rem';
            
            const head = document.createElement('div');
            head.className = `wizard-feed-row wizard-feed-row--${v.ok ? 'ok' : 'fail'}`;
            head.innerHTML = `
                <span class="wizard-feed-icon">${v.ok ? '✓' : '✗'}</span>
                <span style="color:var(--text-secondary);font-size:0.7rem;margin-right:0.3rem;">[${v.source_type}]</span>
                <span class="wizard-feed-url">${escapeHtml(v.label || v.url)}</span>
                <span class="wizard-feed-meta">${v.ok ? (v.source_type === 'pure_llm' ? 'AI 原创内容' : (v.article_count + '篇')) : escapeHtml(v.error)}${v.trust_label ? ` · ${escapeHtml(v.trust_label)} trust${v.trust_score != null ? ` ${escapeHtml(String(v.trust_score))}` : ''}` : ''}</span>
            `;
            row.appendChild(head);
            
            if (v.ok && v.sample_titles && v.sample_titles.length > 0) {
                const samples = document.createElement('div');
                samples.style.paddingLeft = '1.5rem';
                samples.style.fontSize = '0.75rem';
                samples.style.color = 'var(--text-secondary)';
                samples.innerHTML = v.sample_titles.map(t => `• ${escapeHtml(t)}`).join('<br>');
                row.appendChild(samples);
            }
            if (v.quality_summary) {
                const note = document.createElement('div');
                note.className = 'wizard-feed-note';
                note.textContent = v.quality_summary;
                row.appendChild(note);
            }
            card.appendChild(row);
        });
        
        container.appendChild(card);
        container.scrollTop = container.scrollHeight;
        renderWizardReviewPanel();
    } catch (e) {
        loadingMsg.remove();
        wizardLastPreviewData = null;
        wizardLastPreviewError = e.message;
        renderWizardReviewPanel();
        appendWizardMsg('ai', `❌ 预览失败：${e.message}`);
    } finally {
        btn.disabled = false;
        btn.textContent = '重新预览抓取';
    }
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
            btn.addEventListener('click', () => acceptWizardAlternative(alt.original, s, row, card));
            row.append(info, btn);
            card.appendChild(row);
        });
        container.appendChild(card);
    });
    container.scrollTop = container.scrollHeight;
}

function _getWizardRssFeeds() {
    if (!wizardLastConfig || !wizardLastConfig.source_config) return null;
    const sc = wizardLastConfig.source_config;
    if (wizardLastConfig.source_type === 'multi') {
        const rssGroup = (sc.sources || {}).rss;
        if (!rssGroup) return null;
        if (!rssGroup.feeds) rssGroup.feeds = [];
        return rssGroup.feeds;
    }
    if (!sc.feeds) sc.feeds = [];
    return sc.feeds;
}

function acceptWizardAlternative(originalUrl, suggestion, rowEl, cardEl) {
    const newUrl = suggestion?.url || '';
    if (!newUrl) return;
    const feeds = _getWizardRssFeeds();
    if (!feeds) return;
    const idx = feeds.indexOf(originalUrl);
    if (idx !== -1) {
        feeds[idx] = newUrl;
    } else if (!feeds.includes(newUrl)) {
        feeds.push(newUrl);
    }
    // This original is now resolved — remove it from the broken set.
    wizardBrokenFeeds.delete(originalUrl);
    if (Array.isArray(wizardLastSourceValidation)) {
        const replacement = {
            source_type: suggestion?.source_type || 'rss',
            label: suggestion?.feed_title || newUrl,
            url: newUrl,
            ok: true,
            article_count: suggestion?.article_count || 0,
            sample_titles: Array.isArray(suggestion?.sample_titles) ? suggestion.sample_titles : [],
            trust_label: suggestion?.trust_label || '',
            trust_score: suggestion?.trust_score,
            quality_summary: '已采用替代源，建议再做一次抓取预览确认样本质量。',
        };
        const existingIndex = wizardLastSourceValidation.findIndex((item) => item?.url === originalUrl);
        if (existingIndex >= 0) {
            wizardLastSourceValidation.splice(existingIndex, 1, replacement);
        } else {
            wizardLastSourceValidation.push(replacement);
        }
    }
    wizardLastPreviewData = null;
    wizardLastPreviewError = '';

    // Lock this card's buttons and mark accepted row.
    cardEl.querySelectorAll('.wizard-alt-accept-btn').forEach(b => { b.disabled = true; });
    rowEl.classList.add('wizard-alt-row--accepted');
    const tag = document.createElement('span');
    tag.className = 'wizard-alt-accepted-tag';
    tag.textContent = '已采用';
    rowEl.appendChild(tag);
    renderWizardReviewPanel();
}

function applyWizardConfig() {
    if (!wizardLastConfig) return;
    const cfg = wizardLastConfig;
    // Drop any RSS feeds still known to be broken and not replaced.
    if (wizardBrokenFeeds.size) {
        const feeds = _getWizardRssFeeds();
        if (feeds && Array.isArray(feeds)) {
            const filtered = feeds.filter(u => !wizardBrokenFeeds.has(u));
            if (cfg.source_type === 'multi') {
                cfg.source_config.sources.rss.feeds = filtered;
            } else {
                cfg.source_config.feeds = filtered;
            }
        }
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
    const sourceAnalysisSection = document.getElementById('source-analysis-section');
    const viewControls = document.getElementById('view-controls');

    if (!latestData) return;

    clearElement(container);
    container.className = 'news-grid dashboard';
    overviewSection.style.display = 'block';
    if (sourceAnalysisSection) sourceAnalysisSection.style.display = 'none';
    viewControls.style.display = 'none';

    buildEventsByCluster();
    renderSourceStats(latestData.source_stats || computeSourceStats(latestData.top_news));
    renderSourceAnalysis();
    renderCategoryNav();

    (latestData.top_news || []).forEach((newsItem, index) => {
        container.appendChild(createNewsCard(newsItem, index));
    });

    // Auto-catchup items mixed into the card flow
    const catchupItems = latestData.catchup_news || [];
    if (catchupItems.length > 0) {
        const offset = (latestData.top_news || []).length;
        catchupItems.forEach((newsItem, index) => {
            container.appendChild(createNewsCard(newsItem, offset + index));
        });
    }

    window.scrollTo({ top: 0, behavior: 'smooth' });
}

function renderSourceAnalysis() {
    const section = document.getElementById('source-analysis-section');
    const listEl = document.getElementById('source-analysis-list');
    const hintEl = document.getElementById('source-analysis-hint');
    const viewAllBtn = document.getElementById('source-analysis-view-all');
    if (!section || !listEl || !hintEl) return;

    const items = latestData?.source_analysis?.items || [];
    if (!items.length) {
        section.style.display = 'none';
        listEl.innerHTML = '';
        hintEl.textContent = '';
        if (viewAllBtn) viewAllBtn.style.display = 'none';
        return;
    }

    hintEl.textContent = `最近 ${latestData.source_analysis.lookback_days || 3} 天`;
    if (viewAllBtn) viewAllBtn.style.display = 'inline-flex';
    listEl.innerHTML = items.map(item => `
        <article class="source-analysis-card">
            <div class="source-analysis-card__top">
                <h5 class="source-analysis-card__title">${escapeHtml(item.title || '未命名事件')}</h5>
                <span class="source-analysis-card__badge is-${safeClassToken(item.divergence_label, 'low', ['low', 'medium', 'high'])}">${escapeHtml(getCoverageDivergenceLabel(item.divergence_label || 'low'))}</span>
            </div>
            <p class="source-analysis-card__summary">${escapeHtml(item.difference_summary || '')}</p>
            <div class="source-analysis-card__meta">
                ${(item.sources || []).slice(0, 4).map(source => `<span class="source-analysis-card__pill">${escapeHtml(source)}</span>`).join('')}
            </div>
            <div class="source-analysis-card__angles">
                ${(item.source_angles || []).slice(0, 2).map(angle => {
                    const hrefAttr = externalLinkAttrs(angle.original_link);
                    const wrapperTag = hrefAttr ? 'a' : 'div';
                    return `
                    <${wrapperTag} class="source-analysis-card__angle"${hrefAttr}>
                        <span class="source-analysis-card__angle-source">${escapeHtml(angle.source || 'Unknown')}</span>
                        <span class="source-analysis-card__angle-text">${escapeHtml(angle.angle || angle.headline || '')}</span>
                    </${wrapperTag}>
                `;
                }).join('')}
            </div>
            <div class="source-analysis-card__footer">
                <button
                    type="button"
                    class="source-analysis-card__action"
                    onclick="openCoverageModalFromSummary(${item.cluster_id != null ? Number(item.cluster_id) : 'null'})"
                >
                    查看完整角度
                </button>
            </div>
        </article>
    `).join('');
    section.style.display = 'block';
}

function getCoverageDivergenceLabel(value) {
    const normalized = String(value || 'low').trim().toLowerCase();
    if (normalized === 'high') return '差异高';
    if (normalized === 'medium') return '差异中';
    return '差异低';
}

function closeCoverageModal() {
    const modal = document.getElementById('coverage-modal');
    if (!modal) return;
    closeOverlay(modal);
}

function setCoverageModalStatus(message = '', tone = '') {
    const statusEl = document.getElementById('coverage-modal-status');
    if (!statusEl) return;
    if (!message) {
        statusEl.style.display = 'none';
        statusEl.textContent = '';
        statusEl.className = 'coverage-modal-status';
        return;
    }
    statusEl.style.display = 'block';
    statusEl.textContent = message;
    statusEl.className = `coverage-modal-status${tone ? ` is-${safeClassToken(tone, 'info')}` : ''}`;
}

function normalizeCoverageAnalysis(data, fallback = {}) {
    return {
        date: data?.date || fallback.date || '',
        lookback_days: data?.lookback_days || fallback.lookback_days || fallback.days || 3,
        items: Array.isArray(data?.items) ? data.items : [],
    };
}

function renderCoverageModal() {
    const titleEl = document.getElementById('coverage-modal-title');
    const subtitleEl = document.getElementById('coverage-modal-subtitle');
    const listEl = document.getElementById('coverage-modal-list');
    if (!titleEl || !subtitleEl || !listEl) return;

    const context = currentCoverageContext || {};
    const analysis = currentCoverageAnalysis || normalizeCoverageAnalysis({}, context);
    const focusClusterId = currentCoverageFocusClusterId != null ? Number(currentCoverageFocusClusterId) : null;
    const items = Array.isArray(analysis.items) ? analysis.items.slice() : [];

    if (focusClusterId != null) {
        items.sort((left, right) => {
            const leftFocused = Number(left?.cluster_id) === focusClusterId ? 1 : 0;
            const rightFocused = Number(right?.cluster_id) === focusClusterId ? 1 : 0;
            return rightFocused - leftFocused;
        });
    }

    titleEl.textContent = context.title || '报道差异分析';
    subtitleEl.textContent = context.subtitle || `最近 ${analysis.lookback_days || 3} 天`;

    if (!items.length) {
        listEl.innerHTML = '<p class="sources-placeholder">最近没有足够的多源重叠事件可供分析。</p>';
        return;
    }

    listEl.innerHTML = items.map((item) => {
        const isFocused = focusClusterId != null && Number(item.cluster_id) === focusClusterId;
        const tags = (item.source_angles || []).flatMap(angle => Array.isArray(angle.tags) ? angle.tags : []);
        const uniqueTags = [...new Set(tags.map(tag => String(tag || '').trim()).filter(Boolean))].slice(0, 6);
        return `
            <article class="coverage-modal-card${isFocused ? ' is-focused' : ''}">
                <div class="coverage-modal-card__top">
                    <div>
                        <div class="coverage-modal-card__eyebrow">${item.latest_date ? `最近更新 ${escapeHtml(formatSummaryDate(item.latest_date))}` : '最近事件'}</div>
                        <h4 class="coverage-modal-card__title">${escapeHtml(item.title || '未命名事件')}</h4>
                    </div>
                    <div class="coverage-modal-card__badges">
                        <span class="source-analysis-card__badge is-${safeClassToken(item.divergence_label, 'low', ['low', 'medium', 'high'])}">${escapeHtml(getCoverageDivergenceLabel(item.divergence_label || 'low'))}</span>
                        ${item.divergence_score != null ? `<span class="coverage-modal-card__score">${escapeHtml(String(item.divergence_score))} 分</span>` : ''}
                    </div>
                </div>
                <p class="coverage-modal-card__summary">${escapeHtml(item.difference_summary || '')}</p>
                <div class="coverage-modal-card__meta">
                    <span class="sources-coverage-pill">${escapeHtml(String(item.source_count || (item.sources || []).length || 0))} 个来源</span>
                    <span class="sources-coverage-pill">${escapeHtml(String(item.item_count || 0))} 篇报道</span>
                    ${(item.sources || []).slice(0, 4).map(source => `<span class="source-analysis-card__pill">${escapeHtml(source)}</span>`).join('')}
                </div>
                ${uniqueTags.length ? `
                    <div class="coverage-modal-card__topics">
                        ${uniqueTags.map(tag => `<span class="coverage-modal-card__topic">${escapeHtml(tag)}</span>`).join('')}
                    </div>
                ` : ''}
                <div class="coverage-modal-card__angles">
                    ${(item.source_angles || []).map(angle => {
                        const hrefAttr = externalLinkAttrs(angle.original_link);
                        return `
                        <article class="coverage-modal-angle">
                            <div class="coverage-modal-angle__top">
                                <div class="coverage-modal-angle__source-row">
                                    <span class="coverage-modal-angle__source">${escapeHtml(angle.source || 'Unknown')}</span>
                                    ${angle.date ? `<span class="coverage-modal-angle__date">${escapeHtml(formatSummaryDate(angle.date))}</span>` : ''}
                                </div>
                                ${hrefAttr ? `
                                    <a class="coverage-modal-angle__link"${hrefAttr}>
                                        ${ICONS.external}
                                        <span>原文</span>
                                    </a>
                                ` : ''}
                            </div>
                            ${angle.headline ? `<div class="coverage-modal-angle__headline">${escapeHtml(angle.headline)}</div>` : ''}
                            <p class="coverage-modal-angle__text">${escapeHtml(angle.angle || angle.headline || '')}</p>
                            ${(angle.tags || []).length ? `
                                <div class="coverage-modal-angle__tags">
                                    ${(angle.tags || []).slice(0, 4).map(tag => `<span class="coverage-modal-angle__tag">${escapeHtml(tag)}</span>`).join('')}
                                </div>
                            ` : ''}
                        </article>
                    `;
                    }).join('')}
                </div>
            </article>
        `;
    }).join('');
}

async function refreshCoverageModalData() {
    const context = currentCoverageContext;
    if (!context) return;
    const params = new URLSearchParams();
    if (context.board) params.set('board', context.board);
    if (context.date) params.set('date', context.date);
    params.set('days', String(Math.max(2, Math.min(7, Number(context.days) || 3))));
    params.set('limit', String(Math.max(1, Math.min(20, Number(context.limit) || 12))));

    const requestId = ++currentCoverageRequestId;
    setCoverageModalStatus('正在加载完整差异分析...', 'loading');
    try {
        const res = await fetch(`/api/v1/sources/coverage?${params.toString()}`);
        if (!res.ok) throw new Error(await readResponseError(res, '读取报道差异失败'));
        const data = await res.json();
        if (requestId !== currentCoverageRequestId) return;
        currentCoverageAnalysis = normalizeCoverageAnalysis(data, context);
        renderCoverageModal();
        if (currentCoverageAnalysis.items.length > 0) {
            setCoverageModalStatus('');
        } else {
            setCoverageModalStatus('最近没有足够的多源重叠事件可供分析。', 'info');
        }
    } catch (error) {
        if (requestId !== currentCoverageRequestId) return;
        console.error('Failed to load coverage analysis:', error);
        renderCoverageModal();
        if (currentCoverageAnalysis?.items?.length) {
            setCoverageModalStatus(`完整分析刷新失败，先展示当前预览：${error.message}`, 'warning');
        } else {
            setCoverageModalStatus(`读取报道差异失败：${error.message}`, 'error');
        }
    }
}

function openCoverageModal(options = {}) {
    const modal = document.getElementById('coverage-modal');
    if (!modal) return;

    currentCoverageContext = {
        title: options.title || '报道差异分析',
        subtitle: options.subtitle || '',
        board: options.board || '',
        date: options.date || '',
        days: options.days || 3,
        limit: options.limit || 12,
    };
    currentCoverageFocusClusterId = options.focusClusterId != null ? Number(options.focusClusterId) : null;
    currentCoverageAnalysis = normalizeCoverageAnalysis(options.analysis, currentCoverageContext);
    renderCoverageModal();
    setCoverageModalStatus(currentCoverageAnalysis.items.length ? '正在刷新完整分析...' : '正在加载报道差异...', 'loading');
    openOverlay(modal, '#coverage-modal-close');

    if (currentCoverageContext.board || currentCoverageContext.date) {
        refreshCoverageModalData();
    } else if (currentCoverageAnalysis.items.length) {
        setCoverageModalStatus('');
    } else {
        setCoverageModalStatus('最近没有足够的多源重叠事件可供分析。', 'info');
    }
}

function openCoverageModalFromSummary(focusClusterId = null) {
    const analysis = latestData?.source_analysis;
    if (!analysis || !(analysis.items || []).length) return;
    const board = latestData?.board || currentBoardSlug || '';
    const boardObj = _getCurrentBoardObj();
    const dateText = latestData?.date ? formatSummaryDate(latestData.date) : '当前日期';
    openCoverageModal({
        title: '多源报道差异',
        subtitle: `${boardObj?.name || board || '当前板块'} · ${dateText}`,
        board,
        date: latestData?.date || '',
        days: analysis.lookback_days || 3,
        limit: 12,
        focusClusterId,
        analysis,
    });
}

function openCoverageModalFromSources(focusClusterId = null) {
    const board = _getCurrentBoardObj();
    const analysis = currentSourceDashboard?.coverage_preview;
    if (!board || !analysis || !(analysis.items || []).length) return;
    openCoverageModal({
        title: '来源覆盖差异详情',
        subtitle: `${board.name || board.slug} · 最近 ${analysis.lookback_days || 3} 天`,
        board: board.slug,
        date: analysis.date || '',
        days: analysis.lookback_days || 3,
        limit: 12,
        focusClusterId,
        analysis,
    });
}

function buildEventsByCluster() {
    eventsByCluster = {};
    const items = latestData?.events || [];
    for (const item of items) {
        if (item.cluster_id == null) continue;
        eventsByCluster[item.cluster_id] = {
            days_covered: Number(item.days_covered || 1),
            source_count: Number(item.source_count || (item.sources || []).length || 1),
        };
    }
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

    // Story pill — subtle hint when this item is part of a multi-day story line.
    const story = newsItem.cluster_id != null ? eventsByCluster[newsItem.cluster_id] : null;
    if (story && (story.days_covered > 1 || story.source_count > 1)) {
        const storyPill = document.createElement('span');
        storyPill.className = 'story-pill';
        const parts = [];
        if (story.days_covered > 1) parts.push(`持续 ${story.days_covered} 天`);
        if (story.source_count > 1) parts.push(`${story.source_count} 源`);
        storyPill.textContent = parts.join(' · ');
        meta.appendChild(storyPill);
    }

    // Catchup badge — shows "补读" + original date
    if (newsItem.is_catchup) {
        const catchupBadge = document.createElement('span');
        catchupBadge.className = 'catchup-badge card-badge';
        catchupBadge.textContent = '补读';
        meta.appendChild(catchupBadge);
        if (newsItem.original_date) {
            const dateLabel = document.createElement('span');
            dateLabel.className = 'catchup-date-label';
            dateLabel.textContent = formatSummaryDate(newsItem.original_date);
            meta.appendChild(dateLabel);
        }
    }

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
    const sourceAnalysisSection = document.getElementById('source-analysis-section');
    const viewControls = document.getElementById('view-controls');

    clearElement(container);
    container.className = 'news-grid';
    overviewSection.style.display = 'none';
    if (sourceAnalysisSection) sourceAnalysisSection.style.display = 'none';
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
        loadPersonaTraining();
        loadPersonaData();
        loadExplicitPreferences();
        loadPrefSuggestions();
    }
}

async function loadPersonaTraining() {
    try {
        let url = '/api/v1/persona/training';
        if (currentBoardSlug) url += `?board=${encodeURIComponent(currentBoardSlug)}`;
        const response = await fetch(url);
        if (response.ok) {
            renderPersonaTraining(await response.json());
        }
    } catch (error) {
        console.error('Failed to load persona training:', error);
    }
}

function renderPersonaTraining(data) {
    const container = document.getElementById('persona-training-summary');
    if (!container) return;

    if (!data) {
        container.innerHTML = '<p class="empty-state-text">训练数据暂时不可用。</p>';
        return;
    }

    const summary = data.feedback_summary || {};
    const inferred = (data.inferred_interests || []).slice(0, 6);
    const topCategories = (data.top_categories || []).slice(0, 4);
    const topSources = (data.top_sources || []).slice(0, 4);
    const recentFeedback = (data.recent_feedback || []).slice(0, 4);

    const renderChips = (items, kind) => {
        if (!items.length) {
            return '<span class="persona-training-chip is-empty">暂无</span>';
        }
        return items.map((item) => {
            const count = item.count != null ? `<span class="persona-training-chip__count">${escapeHtml(String(item.count))}</span>` : '';
            return `
                <span class="persona-training-chip ${kind}">
                    <span>${escapeHtml(item.name || item.type || '未命名')}</span>
                    ${count}
                </span>
            `;
        }).join('');
    };

    const feedbackRows = recentFeedback.length
        ? recentFeedback.map((item) => `
            <div class="persona-training-feedback">
                <div class="persona-training-feedback__main">
                    <span class="persona-training-feedback__title">${escapeHtml(item.headline || item.url || '未命名文章')}</span>
                    <span class="persona-training-feedback__sentiment ${item.sentiment === 1 ? 'is-like' : 'is-dislike'}">${item.sentiment === 1 ? '喜欢' : '不喜欢'}</span>
                </div>
                <div class="persona-training-feedback__meta">
                    <span>${escapeHtml(item.source || '未知来源')}</span>
                    ${item.category ? `<span>${escapeHtml(item.category)}</span>` : ''}
                    ${item.date ? `<span>${escapeHtml(formatSummaryDate(item.date))}</span>` : ''}
                </div>
            </div>
        `).join('')
        : '<p class="empty-state-text">还没有显式反馈，点卡片上的赞/踩后，这里会开始学习你的偏好。</p>';

    container.innerHTML = `
        <div class="persona-training-grid">
            <div class="persona-training-stat">
                <span class="persona-training-stat__value">${escapeHtml(String(summary.liked_count || 0))}</span>
                <span class="persona-training-stat__label">喜欢</span>
            </div>
            <div class="persona-training-stat">
                <span class="persona-training-stat__value">${escapeHtml(String(summary.disliked_count || 0))}</span>
                <span class="persona-training-stat__label">不喜欢</span>
            </div>
            <div class="persona-training-stat">
                <span class="persona-training-stat__value">${escapeHtml(String(summary.focus_topic_count || 0))}</span>
                <span class="persona-training-stat__label">关注话题</span>
            </div>
            <div class="persona-training-stat">
                <span class="persona-training-stat__value">${escapeHtml(String((summary.prefer_source_count || 0) + (summary.avoid_source_count || 0)))}</span>
                <span class="persona-training-stat__label">来源规则</span>
            </div>
        </div>
        <div class="persona-training-panels">
            <section class="persona-training-card">
                <div class="persona-training-card__head">
                    <h5>系统学到的兴趣</h5>
                    <span>自动抽取</span>
                </div>
                <div class="persona-training-chip-row">
                    ${renderChips(inferred, 'is-interest')}
                </div>
            </section>
            <section class="persona-training-card">
                <div class="persona-training-card__head">
                    <h5>最近偏好的类别</h5>
                    <span>来自点赞</span>
                </div>
                <div class="persona-training-chip-row">
                    ${renderChips(topCategories, 'is-category')}
                </div>
            </section>
            <section class="persona-training-card">
                <div class="persona-training-card__head">
                    <h5>最近偏好的来源</h5>
                    <span>来自点赞</span>
                </div>
                <div class="persona-training-chip-row">
                    ${renderChips(topSources, 'is-source')}
                </div>
            </section>
            <section class="persona-training-card">
                <div class="persona-training-card__head">
                    <h5>最近训练样本</h5>
                    <span>${escapeHtml(data.board || 'default')}</span>
                </div>
                <div class="persona-training-feedback-list">
                    ${feedbackRows}
                </div>
            </section>
        </div>
    `;
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
                    `<div class="interest-popup__success"><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round" style="margin-right: 0.3rem; vertical-align: middle;"><polyline points="20 6 9 17 4 12"></polyline></svg> 已添加：<strong>${escapeHtml(opt)}</strong></div>`;
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

function formatCompactDay(date) {
    const dateObj = new Date(`${date}T00:00:00`);
    return dateObj.toLocaleDateString('zh-CN', {
        month: 'numeric',
        day: 'numeric'
    });
}

function formatDateTime(value) {
    if (!value) return '--';
    const dateObj = new Date(value);
    if (Number.isNaN(dateObj.getTime())) return '--';
    return dateObj.toLocaleString('zh-CN', {
        month: 'numeric',
        day: 'numeric',
        hour: '2-digit',
        minute: '2-digit',
        hour12: false,
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
        
        content.innerHTML = renderMarkdownSafe(data.weekly_insight || '');

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
    if (toggleOverlay(panel, '.history-tab.active')) {
        loadHistoryData('history');
    }
}

function switchHistoryTab(tabName) {
    const tabs = document.querySelectorAll('.history-tab');
    tabs.forEach(t => t.classList.toggle('active', t.dataset.tab === tabName));

    const archiveTab = document.getElementById('history-tab-archive');
    const insightsTab = document.getElementById('history-tab-insights');

    if (archiveTab) archiveTab.style.display = tabName === 'archive' ? '' : 'none';
    if (insightsTab) insightsTab.style.display = tabName === 'insights' ? '' : 'none';

    if (tabName === 'insights' && !_historyInsightsLoaded) {
        _historyInsightsLoaded = true;
        fetchHeatmap();
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

        // Dispatch to magazine recap
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

function safeClassToken(value, fallback = 'unknown', allowed = null) {
    const fallbackToken = String(fallback || 'unknown').toLowerCase();
    const token = String(value ?? '').trim().toLowerCase();
    const safe = /^[a-z0-9_-]+$/.test(token) ? token : fallbackToken;
    return Array.isArray(allowed) && !allowed.includes(safe) ? fallbackToken : safe;
}

function isSafeHttpUrlString(value) {
    try {
        const url = new URL(value);
        return url.protocol === 'http:' || url.protocol === 'https:';
    } catch {
        return false;
    }
}

function externalLinkAttrs(value) {
    return isSafeHttpUrlString(value)
        ? ` href="${escapeHtml(value)}" target="_blank" rel="noopener"`
        : '';
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
    container.innerHTML = '';
    items.forEach((item) => {
        const tag = document.createElement('span');
        tag.className = `pref-tag pref-tag-${category}`;
        tag.appendChild(document.createTextNode(item.content || ''));

        const button = document.createElement('button');
        button.className = 'pref-del';
        button.type = 'button';
        button.setAttribute('aria-label', '删除偏好');
        button.textContent = '×';
        button.addEventListener('click', () => deletePrefTag(item.id));

        tag.appendChild(button);
        container.appendChild(tag);
    });
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
    container.innerHTML = '';
    if (filtered.length === 0) {
        return;
    }

    const label = document.createElement('span');
    label.className = 'pref-suggestion-label';
    label.textContent = '快速添加';
    container.appendChild(label);

    filtered.forEach((item) => {
        const chip = document.createElement('button');
        chip.className = 'pref-suggestion-chip';
        chip.type = 'button';
        chip.textContent = item;
        chip.addEventListener('click', () => quickAddPref(category, item));
        container.appendChild(chip);
    });
}

async function quickAddPref(category, content) {
    const input = document.getElementById(`pref-input-${category}`);
    if (input) input.value = content;
    await addPrefTag(category);
}

// ==========================================
// Insights (Heatmap + Entity Timeline)
// ==========================================

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
        container.innerHTML = `<p class="heatmap-placeholder">加载失败: ${escapeHtml(e.message)}</p>`;
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
    table.style.cssText = `display: grid; grid-template-columns: 140px repeat(${dates.length}, minmax(36px, 1fr)); gap: 3px; font-size: 0.78rem;`;

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
        container.innerHTML = `<p class="timeline-placeholder">搜索失败: ${escapeHtml(e.message)}</p>`;
    }
}

function renderEntityTimeline(data, container) {
    container.innerHTML = '';

    if (!data.items || data.items.length === 0) {
        container.innerHTML = `<p class="timeline-placeholder">在最近 ${escapeHtml(data.days || 30)} 天内未找到与 "${escapeHtml(data.entity || '')}" 相关的资讯</p>`;
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
    const dashboardEl = document.getElementById('sources-dashboard-summary');
    const trendEl = document.getElementById('sources-trend-panel');
    const movementEl = document.getElementById('sources-movement-panel');
    const riskEl = document.getElementById('sources-risk-list');
    const coverageEl = document.getElementById('sources-coverage-preview');
    const replacementEl = document.getElementById('sources-replacement-panel');
    const discoveryEl = document.getElementById('sources-discovery-result');
    const board = _getCurrentBoardObj();

    if (!board) {
        labelEl.textContent = '当前板块: --';
        listEl.innerHTML = '<p class="sources-placeholder">未选择板块</p>';
        if (dashboardEl) dashboardEl.innerHTML = '<p class="sources-placeholder">未选择板块</p>';
        if (trendEl) {
            trendEl.style.display = 'none';
            trendEl.innerHTML = '';
        }
        if (movementEl) {
            movementEl.style.display = 'none';
            movementEl.innerHTML = '';
        }
        if (riskEl) {
            riskEl.style.display = 'none';
            riskEl.innerHTML = '';
        }
        if (coverageEl) {
            coverageEl.style.display = 'none';
            coverageEl.innerHTML = '';
        }
        if (replacementEl) {
            replacementEl.style.display = 'none';
            replacementEl.innerHTML = '';
        }
        if (discoveryEl) {
            discoveryEl.style.display = 'none';
            discoveryEl.innerHTML = '';
        }
        return;
    }

    labelEl.textContent = `${board.icon || ''} ${board.name} (${board.source_type})`.trim();

    if (!['rss', 'multi'].includes(board.source_type)) {
        currentBoardSources = [];
        currentSourceDashboard = null;
        listEl.innerHTML = '<p class="sources-placeholder">P0 来源管理暂只支持 RSS 源。此板块仍使用原有配置模型。</p>';
        if (dashboardEl) dashboardEl.innerHTML = '<p class="sources-placeholder">该板块暂无 RSS 来源仪表盘。</p>';
        if (trendEl) {
            trendEl.style.display = 'none';
            trendEl.innerHTML = '';
        }
        if (movementEl) {
            movementEl.style.display = 'none';
            movementEl.innerHTML = '';
        }
        if (riskEl) {
            riskEl.style.display = 'none';
            riskEl.innerHTML = '';
        }
        if (coverageEl) {
            coverageEl.style.display = 'none';
            coverageEl.innerHTML = '';
        }
        if (replacementEl) {
            replacementEl.style.display = 'none';
            replacementEl.innerHTML = '';
        }
        if (discoveryEl) {
            discoveryEl.style.display = 'none';
            discoveryEl.innerHTML = '';
        }
        return;
    }

    listEl.innerHTML = '<p class="sources-placeholder">正在读取信息源...</p>';
    if (dashboardEl) dashboardEl.innerHTML = '<p class="sources-placeholder">正在计算来源健康与质量指标...</p>';
    if (trendEl) {
        trendEl.style.display = 'none';
        trendEl.innerHTML = '';
    }
    if (movementEl) {
        movementEl.style.display = 'none';
        movementEl.innerHTML = '';
    }
    if (replacementEl) {
        replacementEl.style.display = 'none';
        replacementEl.innerHTML = '';
    }
    if (discoveryEl) {
        discoveryEl.style.display = 'none';
        discoveryEl.innerHTML = '';
    }
    try {
        const [sourcesRes, dashboardRes] = await Promise.all([
            fetch(`/api/v1/boards/${encodeURIComponent(board.slug)}/sources`),
            fetch(`/api/v1/sources/dashboard?board=${encodeURIComponent(board.slug)}`),
        ]);
        if (!sourcesRes.ok) throw new Error(await readResponseError(sourcesRes, '读取失败'));
        const sources = await sourcesRes.json();
        let enrichedById = new Map();
        if (dashboardRes.ok) {
            currentSourceDashboard = await dashboardRes.json();
            enrichedById = new Map((currentSourceDashboard.sources || []).map(source => [source.id, source]));
            renderSourceDashboard(currentSourceDashboard, dashboardEl, coverageEl);
        } else {
            currentSourceDashboard = null;
            if (dashboardEl) dashboardEl.innerHTML = '<p class="sources-placeholder">来源仪表盘读取失败</p>';
            if (trendEl) {
                trendEl.style.display = 'none';
                trendEl.innerHTML = '';
            }
            if (movementEl) {
                movementEl.style.display = 'none';
                movementEl.innerHTML = '';
            }
            if (riskEl) {
                riskEl.style.display = 'none';
                riskEl.innerHTML = '';
            }
            if (coverageEl) {
                coverageEl.style.display = 'none';
                coverageEl.innerHTML = '';
            }
            if (replacementEl) {
                replacementEl.style.display = 'none';
                replacementEl.innerHTML = '';
            }
            if (discoveryEl) {
                discoveryEl.style.display = 'none';
                discoveryEl.innerHTML = '';
            }
        }
        currentBoardSources = (sources || [])
            .filter(source => source.enabled !== false)
            .map(source => ({...source, ...(enrichedById.get(source.id) || {})}));
        if (currentBoardSources.length === 0) {
            listEl.innerHTML = '<p class="sources-placeholder">此板块暂无配置 RSS 信息源</p>';
            return;
        }
        renderFeedList(currentBoardSources, listEl);
    } catch (e) {
        currentBoardSources = [];
        currentSourceDashboard = null;
        listEl.innerHTML = `<p class="sources-placeholder">读取信息源失败：${escapeHtml(e.message)}</p>`;
        if (dashboardEl) dashboardEl.innerHTML = '<p class="sources-placeholder">来源仪表盘读取失败</p>';
        if (trendEl) {
            trendEl.style.display = 'none';
            trendEl.innerHTML = '';
        }
        if (movementEl) {
            movementEl.style.display = 'none';
            movementEl.innerHTML = '';
        }
        if (riskEl) {
            riskEl.style.display = 'none';
            riskEl.innerHTML = '';
        }
        if (coverageEl) {
            coverageEl.style.display = 'none';
            coverageEl.innerHTML = '';
        }
        if (replacementEl) {
            replacementEl.style.display = 'none';
            replacementEl.innerHTML = '';
        }
        if (discoveryEl) {
            discoveryEl.style.display = 'none';
            discoveryEl.innerHTML = '';
        }
    }
}

function renderSourceDashboard(data, summaryEl, coverageEl) {
    if (!summaryEl) return;
    const trendEl = document.getElementById('sources-trend-panel');
    const movementEl = document.getElementById('sources-movement-panel');
    const riskEl = document.getElementById('sources-risk-list');
    const summary = data?.summary || {};
    const successRate = summary.avg_success_rate != null ? `${Math.round(summary.avg_success_rate * 100)}%` : '--';
    const responseTime = summary.avg_response_time_ms != null ? `${Math.round(summary.avg_response_time_ms)} ms` : '--';
    const trustAtRisk = (summary.watch_sources ?? 0) + (summary.risky_sources ?? 0);
    summaryEl.innerHTML = `
        <div class="sources-dashboard-card">
            <span class="sources-dashboard-value">${summary.total_sources ?? 0}</span>
            <span class="sources-dashboard-label">来源总数</span>
        </div>
        <div class="sources-dashboard-card">
            <span class="sources-dashboard-value">${summary.high_trust_sources ?? 0}</span>
            <span class="sources-dashboard-label">高可信</span>
        </div>
        <div class="sources-dashboard-card">
            <span class="sources-dashboard-value">${summary.healthy_sources ?? 0}</span>
            <span class="sources-dashboard-label">健康来源</span>
        </div>
        <div class="sources-dashboard-card is-warning">
            <span class="sources-dashboard-value">${trustAtRisk}</span>
            <span class="sources-dashboard-label">可信度待关注</span>
        </div>
        <div class="sources-dashboard-card">
            <span class="sources-dashboard-value">${summary.manual_override_sources ?? 0}</span>
            <span class="sources-dashboard-label">人工标注</span>
        </div>
        <div class="sources-dashboard-card is-warning">
            <span class="sources-dashboard-value">${(summary.degraded_sources ?? 0) + (summary.unhealthy_sources ?? 0)}</span>
            <span class="sources-dashboard-label">需关注</span>
        </div>
        <div class="sources-dashboard-card">
            <span class="sources-dashboard-value">${successRate}</span>
            <span class="sources-dashboard-label">平均成功率</span>
        </div>
        <div class="sources-dashboard-card">
            <span class="sources-dashboard-value">${responseTime}</span>
            <span class="sources-dashboard-label">平均响应</span>
        </div>
    `;

    const timeline = Array.isArray(data?.health_timeline) ? data.health_timeline : [];
    if (trendEl) {
        if (!timeline.length) {
            trendEl.style.display = 'none';
            trendEl.innerHTML = '';
        } else {
            const totalChecks = timeline.reduce((sum, day) => sum + (day.checks || 0), 0);
            const okChecks = timeline.reduce((sum, day) => sum + (day.ok_checks || 0), 0);
            const activeDays = timeline.filter(day => (day.checks || 0) > 0).length;
            trendEl.style.display = 'block';
            trendEl.innerHTML = `
                <div class="sources-trend-head">
                    <div>
                        <div class="sources-risk-head">最近趋势</div>
                        <p class="sources-trend-summary">最近 ${data.window_days || timeline.length} 天共 ${totalChecks} 次检查，活跃于 ${activeDays} 天。</p>
                    </div>
                    <div class="sources-trend-chips">
                        <span class="sources-coverage-pill">${totalChecks > 0 ? `${Math.round((okChecks / totalChecks) * 100)}% 成功` : '暂无检查'}</span>
                        <span class="sources-coverage-pill">${timeline.filter(day => (day.failed_checks || 0) > 0).length} 天有失败</span>
                    </div>
                </div>
                <div class="sources-trend-bars">
                    ${timeline.map(day => {
                        const checks = day.checks || 0;
                        const successPercent = checks > 0 && day.success_rate != null ? Math.max(10, Math.round(day.success_rate * 100)) : 8;
                        const toneClass = checks === 0 ? 'is-empty' : (day.failed_checks || 0) > 0 ? 'is-warning' : 'is-healthy';
                        const statusText = checks > 0 && day.success_rate != null ? `${Math.round(day.success_rate * 100)}%` : '--';
                        const metaText = checks > 0 ? `${checks} 次` : '无检查';
                        return `
                            <div class="sources-trend-day ${toneClass}">
                                <div class="sources-trend-day__bar">
                                    <span class="sources-trend-day__fill" style="height:${successPercent}%"></span>
                                </div>
                                <div class="sources-trend-day__value">${escapeHtml(statusText)}</div>
                                <div class="sources-trend-day__meta">${escapeHtml(metaText)}</div>
                                <div class="sources-trend-day__label">${escapeHtml(formatCompactDay(day.date || ''))}</div>
                            </div>
                        `;
                    }).join('')}
                </div>
            `;
        }
    }

    const recentMovements = Array.isArray(data?.recent_movements) ? data.recent_movements : [];
    if (movementEl) {
        if (!recentMovements.length) {
            movementEl.style.display = 'none';
            movementEl.innerHTML = '';
        } else {
            movementEl.style.display = 'block';
            movementEl.innerHTML = `
                <div class="sources-risk-head">最近波动</div>
                <div class="sources-movement-items">
                    ${recentMovements.map(item => `
                        <div class="sources-movement-item is-${safeClassToken(item.movement, 'stable', ['stable', 'recovered', 'degraded'])}">
                            <div class="sources-movement-item__main">
                                <span class="sources-movement-item__name">${escapeHtml(item.name || item.url || 'Unknown source')}</span>
                                <span class="sources-movement-item__badge is-${safeClassToken(item.movement, 'stable', ['stable', 'recovered', 'degraded'])}">${escapeHtml(getSourceMovementLabel(item.movement || 'stable'))}</span>
                            </div>
                            <div class="sources-movement-item__summary">${escapeHtml(item.summary || '最近状态发生变化。')}</div>
                            <div class="sources-movement-item__meta">${escapeHtml(formatDateTime(item.checked_at || ''))} · ${escapeHtml(item.health_status || 'unknown')} · ${escapeHtml(item.trust_label || 'unknown')} trust</div>
                        </div>
                    `).join('')}
                </div>
            `;
        }
    }

    const atRisk = data?.at_risk_sources || [];
    if (riskEl) {
        if (!atRisk.length) {
            riskEl.style.display = 'none';
            riskEl.innerHTML = '';
        } else {
            riskEl.style.display = 'block';
            riskEl.innerHTML = `
                <div class="sources-risk-head">需关注来源</div>
                <div class="sources-risk-items">
                    ${atRisk.map(source => `
                        <div class="sources-risk-item">
                            <div class="sources-risk-item__main">
                                <span class="sources-risk-item__name">${escapeHtml(source.name || source.url || 'Unknown source')}</span>
                                <span class="sources-risk-item__meta">${escapeHtml(source.health_status || 'unknown')} · ${escapeHtml(source.trust_label || 'unknown')} trust</span>
                            </div>
                            <div class="sources-risk-item__reason">${escapeHtml(source.risk_summary || source.quality_summary || source.last_error || '需要人工检查来源质量。')}</div>
                            <div class="sources-risk-item__reason">${escapeHtml(source.recommended_action || '建议人工复查。')}</div>
                            ${source.id != null ? `<button class="sources-risk-replace-btn" onclick="loadSourceAlternatives(${Number(source.id)})">替换建议</button>` : ''}
                        </div>
                    `).join('')}
                </div>
            `;
        }
    }

    if (!coverageEl) return;
    const items = data?.coverage_preview?.items || [];
    if (!items.length) {
        coverageEl.style.display = 'none';
        coverageEl.innerHTML = '';
        return;
    }
    coverageEl.style.display = 'block';
    coverageEl.innerHTML = `
        <div class="sources-coverage-head">
            <div>
                <h4 class="metrics-card-title">报道差异预览</h4>
                <span class="sources-coverage-hint">最近 ${data.coverage_preview.lookback_days || 3} 天</span>
            </div>
            <button type="button" class="sources-coverage-action" onclick="openCoverageModalFromSources()">查看全部</button>
        </div>
        <div class="sources-coverage-list">
            ${items.map(item => `
                <div class="sources-coverage-item">
                    <div class="sources-coverage-title">${escapeHtml(item.title || '未命名事件')}</div>
                    <div class="sources-coverage-meta">
                        <span class="sources-coverage-pill">${escapeHtml((item.sources || []).slice(0, 3).join(' / '))}</span>
                        <span class="sources-coverage-pill is-${safeClassToken(item.divergence_label, 'low', ['low', 'medium', 'high'])}">${escapeHtml(getCoverageDivergenceLabel(item.divergence_label || 'low'))}</span>
                    </div>
                    <p class="sources-coverage-summary">${escapeHtml(item.difference_summary || '')}</p>
                    <div class="sources-coverage-actions">
                        <span class="sources-coverage-caption">${item.latest_date ? `最近更新 ${escapeHtml(formatSummaryDate(item.latest_date))}` : `${escapeHtml(String(item.source_count || (item.sources || []).length || 0))} 个来源`}</span>
                        <button type="button" class="sources-coverage-action is-subtle" onclick="openCoverageModalFromSources(${item.cluster_id != null ? Number(item.cluster_id) : 'null'})">展开详情</button>
                    </div>
                </div>
            `).join('')}
        </div>
    `;
}

function getSourceCredibilityLabel(value) {
    return SOURCE_CREDIBILITY_LABELS[value || ''] || '自动判断';
}

function getSourceMovementLabel(value) {
    if (value === 'recovered') return '已恢复';
    if (value === 'degraded') return '刚恶化';
    return '有波动';
}

function renderSourceCredibilityOptions(selectedValue = '') {
    return SOURCE_CREDIBILITY_OPTIONS.map((option) => {
        const selected = option.value === (selectedValue || '') ? ' selected' : '';
        return `<option value="${escapeHtml(option.value)}"${selected}>${escapeHtml(option.label)}</option>`;
    }).join('');
}

function renderFeedList(sources, container) {
    container.innerHTML = '';
    sources.forEach((source, index) => {
        const url = source.url || '';
        const item = document.createElement('div');
        item.className = 'source-feed-item';
        item.id = `source-item-${source.id || index}`;

        const indexEl = document.createElement('span');
        indexEl.className = 'source-feed-index';
        indexEl.textContent = String(index + 1);

        const main = document.createElement('div');
        main.className = 'source-feed-main';

        const urlEl = document.createElement('span');
        urlEl.className = 'source-feed-url';
        urlEl.textContent = source.name ? `${source.name} · ${url}` : url;
        urlEl.title = url;

        const metaRow = document.createElement('div');
        metaRow.className = 'source-feed-meta-row';
        const healthChip = document.createElement('span');
        healthChip.className = `source-feed-chip is-${safeClassToken(source.health_status, 'unknown')}`;
        healthChip.textContent = source.health_status || 'unknown';
        metaRow.appendChild(healthChip);
        if (source.trust_label) {
            const trustChip = document.createElement('span');
            trustChip.className = `source-feed-chip is-trust-${source.trust_label}`;
            trustChip.textContent = `${source.trust_label} trust`;
            trustChip.title = source.quality_summary || '';
            metaRow.appendChild(trustChip);
        }
        if (source.credibility_override) {
            const overrideChip = document.createElement('span');
            overrideChip.className = 'source-feed-chip is-override';
            overrideChip.textContent = `人工: ${getSourceCredibilityLabel(source.credibility_override)}`;
            overrideChip.title = '已启用人工可信度标注';
            metaRow.appendChild(overrideChip);
        }
        const metaText = document.createElement('span');
        metaText.className = 'source-feed-meta-text';
        const articleCount = source.recent_article_count != null ? `${source.recent_article_count} 篇` : '0 篇';
        const eventCount = source.recent_event_count != null ? `${source.recent_event_count} 事件` : '0 事件';
        const successRate = source.success_rate != null ? `${Math.round(source.success_rate * 100)}% 成功` : '暂无检查';
        metaText.textContent = `${articleCount} · ${eventCount} · ${successRate}`;
        metaRow.appendChild(metaText);

        const controlRow = document.createElement('div');
        controlRow.className = 'source-feed-control-row';
        const credibilityLabel = document.createElement('label');
        credibilityLabel.className = 'source-feed-control-label';
        credibilityLabel.textContent = '可信度';
        const credibilitySelect = document.createElement('select');
        credibilitySelect.className = 'source-feed-select';
        credibilitySelect.innerHTML = renderSourceCredibilityOptions(source.credibility_override || '');
        credibilitySelect.setAttribute('aria-label', `设置 ${source.name || url} 的可信度`);
        credibilitySelect.addEventListener('change', async () => {
            const previousValue = source.credibility_override || '';
            const nextValue = credibilitySelect.value;
            credibilitySelect.disabled = true;
            try {
                await updateSourceCredibility(source.id, nextValue);
                source.credibility_override = nextValue;
                await loadSourcesForCurrentBoard();
            } catch (e) {
                source.credibility_override = previousValue;
                credibilitySelect.value = previousValue;
                alert('更新可信度失败: ' + e.message);
            } finally {
                credibilitySelect.disabled = false;
            }
        });
        controlRow.appendChild(credibilityLabel);
        controlRow.appendChild(credibilitySelect);

        main.appendChild(urlEl);
        main.appendChild(metaRow);
        main.appendChild(controlRow);
        if (Array.isArray(source.recent_statuses) && source.recent_statuses.length > 0) {
            const trendRow = document.createElement('div');
            trendRow.className = 'source-feed-trend-row';

            const trendLabel = document.createElement('span');
            trendLabel.className = 'source-feed-trend-label';
            trendLabel.textContent = '最近检查';

            const trendDots = document.createElement('div');
            trendDots.className = 'source-feed-trend-dots';
            source.recent_statuses.slice(0, 6).forEach((entry) => {
                const dot = document.createElement('span');
                dot.className = `source-feed-trend-dot is-${safeClassToken(entry.status, 'unknown')}`;
                const titleParts = [formatDateTime(entry.checked_at || ''), entry.status || 'unknown'];
                if (entry.response_time_ms != null) {
                    titleParts.push(`${Math.round(entry.response_time_ms)} ms`);
                }
                if (entry.error_message) {
                    titleParts.push(entry.error_message);
                }
                dot.title = titleParts.filter(Boolean).join(' · ');
                trendDots.appendChild(dot);
            });

            trendRow.appendChild(trendLabel);
            trendRow.appendChild(trendDots);
            main.appendChild(trendRow);
        }

        const statusEl = document.createElement('span');
        statusEl.className = 'source-feed-status';
        const statusKey = source.id != null ? source.id : index;
        statusEl.id = `source-status-${statusKey}`;
        statusEl.dataset.sourceUrl = url;
        if (source.health_status && source.health_status !== 'healthy') {
            statusEl.textContent = source.health_status;
            statusEl.title = source.last_error || source.health_status;
        } else if (source.avg_response_time_ms != null) {
            statusEl.textContent = `${Math.round(source.avg_response_time_ms)}ms`;
            statusEl.title = '最近检查平均响应时间';
        }

        const actions = document.createElement('div');
        actions.className = 'source-feed-actions';

        const testBtn = document.createElement('button');
        testBtn.className = 'source-feed-test-btn';
        testBtn.textContent = '测试';
        testBtn.addEventListener('click', () => testExistingFeed(statusKey, url));

        const deleteBtn = document.createElement('button');
        deleteBtn.className = 'source-feed-del-btn';
        deleteBtn.textContent = '删除';
        deleteBtn.addEventListener('click', () => deleteSourceFeed(source.id));

        const replaceBtn = document.createElement('button');
        replaceBtn.className = 'source-feed-replace-btn';
        replaceBtn.textContent = '替换建议';
        replaceBtn.addEventListener('click', () => loadSourceAlternatives(source.id));

        actions.appendChild(testBtn);
        actions.appendChild(replaceBtn);
        actions.appendChild(deleteBtn);
        item.appendChild(indexEl);
        item.appendChild(main);
        item.appendChild(statusEl);
        item.appendChild(actions);
        container.appendChild(item);
    });
}

async function updateSourceCredibility(sourceId, credibilityOverride) {
    const board = _getCurrentBoardObj();
    if (!board || sourceId == null) return;

    const res = await fetch(`/api/v1/boards/${encodeURIComponent(board.slug)}/sources/${encodeURIComponent(sourceId)}`, {
        method: 'PATCH',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({ credibility_override: credibilityOverride }),
    });
    if (!res.ok) {
        throw new Error(await readResponseError(res, '更新可信度失败'));
    }
}

async function discoverSourceFeeds() {
    const board = _getCurrentBoardObj();
    const input = document.getElementById('discover-source-query');
    const panel = document.getElementById('sources-discovery-result');
    if (!board || !panel) return;

    const query = (input?.value || '').trim();
    panel.style.display = 'block';
    panel.innerHTML = '<p class="sources-placeholder">正在寻找并验证可用 RSS 来源...</p>';

    try {
        const res = await fetch(`/api/v1/boards/${encodeURIComponent(board.slug)}/sources/discover`, {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({ query }),
        });
        if (!res.ok) throw new Error(await readResponseError(res, '发现来源失败'));
        const data = await res.json();
        renderDiscoveredSources(data);
    } catch (e) {
        panel.style.display = 'block';
        panel.innerHTML = `<p class="sources-placeholder">来源发现失败：${escapeHtml(e.message)}</p>`;
    }
}

function renderDiscoveredSources(data) {
    const panel = document.getElementById('sources-discovery-result');
    if (!panel) return;

    const suggestions = data?.suggestions || [];
    const discarded = data?.discarded_suggestions || [];
    const skipped = data?.skipped_existing || [];
    const topic = data?.topic || '当前板块主题';
    const searchedTerms = Array.isArray(data?.searched_terms) ? data.searched_terms : [];

    panel.style.display = 'block';
    panel.innerHTML = `
        <div class="sources-discovery-head">
            <div>
                <div class="sources-risk-head">发现结果</div>
                <p class="sources-discovery-summary">${escapeHtml(data?.summary || '已完成来源发现。')}</p>
                <p class="sources-discovery-meta">${escapeHtml(topic)}${searchedTerms.length ? ` · 检索词：${escapeHtml(searchedTerms.slice(0, 3).join('、'))}` : ''}</p>
            </div>
        </div>
        ${suggestions.length ? `
            <div class="sources-discovery-list">
                ${suggestions.map(item => `
                    <div class="sources-discovery-item">
                        <div class="sources-discovery-item__top">
                            <span class="sources-discovery-item__title">${escapeHtml(item.feed_title || item.url || '未命名来源')}</span>
                            <span class="sources-discovery-item__meta">${escapeHtml(item.trust_label || 'unknown')} trust${item.trust_score != null ? ` ${escapeHtml(String(item.trust_score))}` : ''}</span>
                        </div>
                        <div class="sources-discovery-item__url">${escapeHtml(item.url || '')}</div>
                        <p class="sources-discovery-item__summary">${escapeHtml(item.selection_reason || item.quality_summary || '已通过可用性验证。')}</p>
                        <div class="sources-discovery-item__samples">
                            ${(item.sample_titles || []).slice(0, 2).map(title => `<span>${escapeHtml(title)}</span>`).join('')}
                        </div>
                        <div class="sources-discovery-item__actions">
                            <span class="sources-discovery-item__meta">${item.article_count != null ? `${escapeHtml(String(item.article_count))} 篇样本` : '已验证'}</span>
                            <button class="sources-replacement-apply-btn js-add-discovered-source" data-source-url="${escapeHtml(item.url || '')}">添加到当前板块</button>
                        </div>
                    </div>
                `).join('')}
            </div>
        ` : '<p class="sources-placeholder">暂时没有发现新的可用 RSS 来源。</p>'}
        ${skipped.length ? `
            <div class="sources-discovery-footnote">已跳过当前板块中已存在的来源：${escapeHtml(skipped.slice(0, 3).join('、'))}</div>
        ` : ''}
        ${discarded.length ? `
            <div class="sources-replacement-discarded">
                <div class="sources-risk-head">未采用的候选</div>
                ${discarded.map(item => `
                    <div class="sources-replacement-discarded__item">${escapeHtml(item.url || item.label || '候选源')} · ${escapeHtml(item.selection_reason || item.quality_summary || '质量较弱')}</div>
                `).join('')}
            </div>
        ` : ''}
    `;

    panel.querySelectorAll('.js-add-discovered-source').forEach((button) => {
        button.addEventListener('click', () => addDiscoveredSource(button.dataset.sourceUrl || ''));
    });
}

async function addDiscoveredSource(url) {
    const board = _getCurrentBoardObj();
    url = String(url || '').trim();
    if (!board || !url) return;

    try {
        const res = await fetch(`/api/v1/boards/${encodeURIComponent(board.slug)}/sources`, {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({ url }),
        });
        if (!res.ok) throw new Error(await readResponseError(res, '添加来源失败'));
        await initBoards();
        await loadSourcesForCurrentBoard();
        const panel = document.getElementById('sources-discovery-result');
        if (panel) {
            panel.style.display = 'block';
            panel.innerHTML = `<p class="sources-discovery-footnote">已将 ${escapeHtml(url)} 添加到当前板块。</p>`;
        }
    } catch (e) {
        alert('添加来源失败: ' + e.message);
    }
}

async function loadSourceAlternatives(sourceId) {
    const board = _getCurrentBoardObj();
    const panel = document.getElementById('sources-replacement-panel');
    if (!board || !panel || sourceId == null) return;

    panel.style.display = 'block';
    panel.innerHTML = '<p class="sources-placeholder">正在为该来源寻找替换建议...</p>';

    try {
        const res = await fetch(`/api/v1/boards/${encodeURIComponent(board.slug)}/sources/${encodeURIComponent(sourceId)}/alternatives`);
        if (!res.ok) throw new Error(await readResponseError(res, '读取替换建议失败'));
        const data = await res.json();
        renderSourceAlternatives(data, sourceId);
    } catch (e) {
        panel.innerHTML = `<p class="sources-placeholder">替换建议读取失败：${escapeHtml(e.message)}</p>`;
    }
}

function renderSourceAlternatives(data, sourceId) {
    const panel = document.getElementById('sources-replacement-panel');
    if (!panel) return;

    const source = data?.source || {};
    const alternatives = data?.alternatives || [];
    const discarded = data?.discarded_alternatives || [];
    const hasAlternatives = alternatives.length > 0;

    panel.style.display = 'block';
    panel.innerHTML = `
        <div class="sources-replacement-head">
            <div>
                <h4 class="metrics-card-title">替换建议</h4>
                <p class="sources-replacement-subtitle">${escapeHtml(source.name || source.url || '当前来源')}</p>
            </div>
            <button class="sources-replacement-close" onclick="closeSourceAlternatives()">收起</button>
        </div>
        <p class="sources-replacement-summary">${escapeHtml(source.risk_summary || source.quality_summary || data.summary || '已生成来源建议。')}</p>
        <p class="sources-replacement-summary is-muted">${escapeHtml(source.recommended_action || data.summary || '')}</p>
        ${hasAlternatives ? `
            <div class="sources-replacement-list">
                ${alternatives.map(item => `
                    <div class="sources-replacement-item">
                        <div class="sources-replacement-item__top">
                            <span class="sources-replacement-item__url">${escapeHtml(item.url || item.label || '未命名来源')}</span>
                            <span class="sources-replacement-item__meta">${escapeHtml(item.trust_label || 'unknown')} trust${item.trust_score != null ? ` ${escapeHtml(String(item.trust_score))}` : ''}</span>
                        </div>
                        <p class="sources-replacement-item__summary">${escapeHtml(item.quality_summary || item.selection_reason || '可作为替换候选。')}</p>
                        <div class="sources-replacement-item__actions">
                            <button class="sources-replacement-apply-btn js-apply-source-alternative" data-source-id="${escapeHtml(String(Number(sourceId)))}" data-source-url="${escapeHtml(item.url || '')}">采用这个</button>
                            <span class="sources-replacement-item__samples">${escapeHtml(item.feed_title || '')}${item.article_count != null ? ` · ${escapeHtml(String(item.article_count))} 篇` : ''}</span>
                        </div>
                    </div>
                `).join('')}
            </div>
        ` : '<p class="sources-placeholder">暂时没有找到更稳的替代 RSS 源。</p>'}
        ${discarded.length > 0 ? `
            <div class="sources-replacement-discarded">
                <div class="sources-risk-head">未采用的候选</div>
                ${discarded.map(item => `
                    <div class="sources-replacement-discarded__item">${escapeHtml(item.url || item.label || '候选源')} · ${escapeHtml(item.selection_reason || item.quality_summary || '质量较弱')}</div>
                `).join('')}
            </div>
        ` : ''}
    `;

    panel.querySelectorAll('.js-apply-source-alternative').forEach((button) => {
        button.addEventListener('click', () => {
            applySourceAlternative(Number(button.dataset.sourceId), button.dataset.sourceUrl || '');
        });
    });
}

function closeSourceAlternatives() {
    const panel = document.getElementById('sources-replacement-panel');
    if (!panel) return;
    panel.style.display = 'none';
    panel.innerHTML = '';
}

async function applySourceAlternative(sourceId, url) {
    const board = _getCurrentBoardObj();
    url = String(url || '').trim();
    if (!board || !url) return;

    try {
        const res = await fetch(`/api/v1/boards/${encodeURIComponent(board.slug)}/sources/${encodeURIComponent(sourceId)}`, {
            method: 'PATCH',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({ url }),
        });
        if (!res.ok) throw new Error(await readResponseError(res, '替换失败'));
        closeSourceAlternatives();
        await initBoards();
        await loadSourcesForCurrentBoard();
    } catch (e) {
        const panel = document.getElementById('sources-replacement-panel');
        if (panel) {
            panel.style.display = 'block';
            const errorEl = document.createElement('p');
            errorEl.className = 'sources-placeholder';
            errorEl.textContent = `应用替换失败：${e.message}`;
            panel.appendChild(errorEl);
        }
    }
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
            const sampleTitles = Array.isArray(data.sample_titles) ? data.sample_titles : [];
            const samples = sampleTitles.map(t => `<li>${escapeHtml(t)}</li>`).join('');
            resultEl.innerHTML = `
                <strong>✓ 连接成功</strong> — ${escapeHtml(data.feed_title || url)}<br>
                <span style="opacity:0.8;">共 ${escapeHtml(String(data.article_count || 0))} 篇文章</span>
                ${samples ? `<ul style="margin: 0.5rem 0 0 1rem; opacity: 0.8; font-size: 0.8rem;">${samples}</ul>` : ''}
            `;
        } else {
            resultEl.className = 'source-test-result test-fail';
            resultEl.innerHTML = `<strong>✗ 连接失败</strong> — ${escapeHtml(data.error || '未知错误')}`;
        }
    } catch (e) {
        resultEl.className = 'source-test-result test-fail';
        resultEl.innerHTML = `<strong>✗ 请求异常</strong> — ${escapeHtml(e.message)}`;
    }
}

function renderSourceTestStatus(statusEl, result) {
    if (!statusEl || !result) return;
    if (result.ok) {
        statusEl.className = 'source-feed-status status-ok';
        statusEl.textContent = `✓ ${result.article_count || 0}篇`;
        statusEl.title = result.feed_title || '';
    } else {
        statusEl.className = 'source-feed-status status-fail';
        statusEl.textContent = `✗ ${result.error || '失败'}`;
        statusEl.title = result.error || '';
    }
}

async function testExistingFeed(statusKey, url) {
    const statusEl = document.getElementById(`source-status-${statusKey}`);
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
        renderSourceTestStatus(statusEl, data);
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
    return currentBoardSources.map(source => source.url).filter(Boolean);
}

async function addSourceFeed() {
    const input = document.getElementById('new-source-url');
    const url = input.value.trim();
    if (!url) return;
    const board = _getCurrentBoardObj();
    if (!board) return;

    const feeds = _getCurrentFeeds();
    if (feeds.includes(url)) {
        alert('此信息源已存在');
        return;
    }

    try {
        const res = await fetch(`/api/v1/boards/${encodeURIComponent(board.slug)}/sources`, {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({url}),
        });
        if (!res.ok) throw new Error(await readResponseError(res, '添加失败'));
        input.value = '';
        document.getElementById('source-test-result').style.display = 'none';
        await initBoards();
        await loadSourcesForCurrentBoard();
    } catch (e) {
        alert('添加失败: ' + e.message);
    }
}

async function deleteSourceFeed(sourceId) {
    const board = _getCurrentBoardObj();
    if (!board || sourceId == null) return;

    const source = currentBoardSources.find(item => item.id === sourceId);
    const removed = source?.url || '';
    if (!confirm(`确认删除此信息源？\n${removed}`)) return;

    try {
        const res = await fetch(`/api/v1/boards/${encodeURIComponent(board.slug)}/sources/${encodeURIComponent(sourceId)}`, {
            method: 'DELETE',
        });
        if (!res.ok) throw new Error(await readResponseError(res, '删除失败'));
        await initBoards();
        await loadSourcesForCurrentBoard();
    } catch (e) {
        alert('删除失败: ' + e.message);
    }
}


// -----------------------------------------------------------------------
// Catch-up Digest (精炼补读)
// -----------------------------------------------------------------------

async function _loadCatchupConfig() {
    try {
        let url = '/api/v1/catchup/status';
        if (currentBoardSlug) url += `?board=${encodeURIComponent(currentBoardSlug)}`;
        const resp = await fetch(url);
        if (!resp.ok) return;
        const data = await resp.json();
        const days = data.catchup_days != null ? data.catchup_days : 7;
        const chk = document.getElementById('catchup-auto-chk');
        const sel = document.getElementById('catchup-days-select');
        const hint = document.getElementById('catchup-config-hint');
        if (chk) chk.checked = days > 0;
        if (sel) sel.value = String(days);
        if (hint) hint.textContent = days > 0 ? '开启后，未读条目将自动混入今日简报' : '自动补读已关闭';
    } catch (_) { /* non-critical */ }
}

async function toggleAutoCatchup(enabled) {
    const sel = document.getElementById('catchup-days-select');
    const hint = document.getElementById('catchup-config-hint');
    if (!enabled) {
        if (sel) sel.value = '0';
        if (hint) hint.textContent = '自动补读已关闭';
        await updateCatchupDays(0);
    } else {
        if (sel && sel.value === '0') sel.value = '7';
        if (hint) hint.textContent = '开启后，未读条目将自动混入今日简报';
        await updateCatchupDays(parseInt(sel?.value || '7', 10));
    }
}

async function updateCatchupDays(days) {
    days = parseInt(days, 10);
    const hint = document.getElementById('catchup-config-hint');
    const chk = document.getElementById('catchup-auto-chk');
    if (chk) chk.checked = days > 0;
    if (hint) hint.textContent = days > 0 ? '开启后，未读条目将自动混入今日简报' : '自动补读已关闭';
    try {
        const slug = currentBoardSlug || '';
        if (!slug) return;
        await fetch(`/api/v1/boards/${encodeURIComponent(slug)}`, {
            method: 'PATCH',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ catchup_days: days }),
        });
    } catch (_) { /* non-critical */ }
}

async function _refreshCatchupBadge() {
    try {
        let url = '/api/v1/catchup/status';
        if (currentBoardSlug) url += `?board=${encodeURIComponent(currentBoardSlug)}`;
        const resp = await fetch(url);
        if (!resp.ok) return;
        const data = await resp.json();
        const unreadArticles = data.unread_article_count != null ? data.unread_article_count : (data.unviewed_count || 0);
        const count = unreadArticles + (data.gap_count || 0);
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
        _loadCatchupConfig();
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

        const unreadArticles = data.unread_article_count != null ? data.unread_article_count : (data.unviewed_count || 0);
        const unreadDates = data.unread_date_count != null ? data.unread_date_count : (data.unviewed_count || 0);
        const gaps = data.gap_count || 0;
        const total = unreadArticles + gaps;

        if (total === 0) {
            statusEl.innerHTML = '<p class="catchup-placeholder"><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round" style="margin-right: 0.3rem; vertical-align: middle;"><polyline points="20 6 9 17 4 12"></polyline></svg> 所有内容都已阅读，无需补读</p>';
            if (genBtn) genBtn.style.display = 'none';
        } else {
            let msg = '';
            if (unreadArticles > 0) msg += `${unreadArticles} 篇未读`;
            if (unreadDates > 0) msg += `（${unreadDates} 天）`;
            if (gaps > 0) msg += `${unreadArticles > 0 ? ' + ' : ''}${gaps} 天未采集`;
            let html = `<p class="catchup-status-text">${msg} 的内容待补读</p>`;

            // Show clickable unviewed dates
            const unviewedDates = data.unviewed_dates || [];
            if (unviewedDates.length > 0) {
                html += '<div class="catchup-unviewed-dates">';
                html += '<span class="catchup-unviewed-label">未读日期：</span>';
                unviewedDates.forEach(d => {
                    html += `<button class="catchup-date-link js-catchup-date-link" data-summary-date="${escapeHtml(d || '')}">${escapeHtml(formatSummaryDate(d))}</button>`;
                });
                html += '</div>';
            }

            statusEl.innerHTML = html;
            statusEl.querySelectorAll('.js-catchup-date-link').forEach((button) => {
                button.addEventListener('click', () => {
                    toggleCatchupPanel();
                    fetchSummary(false, button.dataset.summaryDate || '');
                });
            });
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
                rangeInfo = `<div class="catchup-range">覆盖日期：${data.dates_covered.map(d => escapeHtml(formatSummaryDate(d))).join('、')}</div>`;
                if (data.backfilled_dates && data.backfilled_dates.length > 0) {
                    rangeInfo += `<div class="catchup-backfill">已补采：${data.backfilled_dates.map(d => escapeHtml(formatSummaryDate(d))).join('、')}</div>`;
                }
            }

            let html = rangeInfo;
            if (digestData.overview) {
                html += `<div class="catchup-overview">${escapeHtml(digestData.overview)}</div>`;
            }
            if (Array.isArray(digestData.top_news)) {
                html += '<div class="catchup-news-list">';
                digestData.top_news.forEach(item => {
                    const headline = item.headline || item.title || '';
                    const keyPoints = Array.isArray(item.key_points) ? item.key_points : [];
                    const hrefAttr = externalLinkAttrs(item.original_link);
                    html += `<div class="catchup-news-item">
                        <div class="catchup-news-headline">${escapeHtml(headline)}</div>
                        <div class="catchup-news-meta">
                            <span class="catchup-news-category">${escapeHtml(item.category || '')}</span>
                            ${item.source ? `<span class="catchup-news-source">${escapeHtml(item.source)}</span>` : ''}
                        </div>
                        ${keyPoints.length > 0
                            ? `<ul class="catchup-news-points">${keyPoints.map(p => `<li>${escapeHtml(p)}</li>`).join('')}</ul>`
                            : ''}
                        ${hrefAttr ? `<a class="catchup-news-link"${hrefAttr}>阅读原文 ${ICONS.external}</a>` : ''}
                    </div>`;
                });
                html += '</div>';
            }
            contentEl.innerHTML = html;
        }

        // Refresh badge
        _refreshCatchupBadge();
    } catch (error) {
        contentEl.innerHTML = `<p class="catchup-placeholder">生成失败：${escapeHtml(error.message)}</p>`;
    } finally {
        if (genBtn) {
            genBtn.disabled = false;
            genBtn.textContent = '生成精炼补读';
        }
    }
}

// -----------------------------------------------------------------------
// More Menu (dropdown for low-frequency actions)
// -----------------------------------------------------------------------

function toggleMoreMenu(e) {
    if (e) {
        e.stopPropagation();
    }
    const menu = document.getElementById('more-menu');
    const btn = document.getElementById('more-btn');
    if (!menu || !btn) return;

    const isVisible = menu.classList.contains('show');
    if (isVisible) {
        closeMoreMenu();
    } else {
        // Calculate position dynamically to avoid overflow clipping
        const rect = btn.getBoundingClientRect();
        menu.style.position = 'fixed';
        menu.style.top = (rect.bottom + 6) + 'px';

        // Prevent going off-screen on the right
        const menuWidth = 140;
        if (rect.left + menuWidth > window.innerWidth) {
            menu.style.left = (window.innerWidth - menuWidth - 16) + 'px';
        } else {
            menu.style.left = rect.left + 'px';
        }

        menu.classList.add('show');
        document.addEventListener('click', _closeMoreMenuOnOutsideClick);
        document.addEventListener('keydown', _closeMoreMenuOnEscape);
        window.addEventListener('resize', closeMoreMenu);
    }
}

function closeMoreMenu() {
    const menu = document.getElementById('more-menu');
    if (menu) menu.classList.remove('show');
    _removeMoreMenuListeners();
}

function _closeMoreMenuOnOutsideClick(e) {
    const menu = document.getElementById('more-menu');
    if (menu && !menu.contains(e.target)) {
        closeMoreMenu();
    }
}

function _closeMoreMenuOnEscape(e) {
    if (e.key === 'Escape') closeMoreMenu();
}

function _removeMoreMenuListeners() {
    document.removeEventListener('click', _closeMoreMenuOnOutsideClick);
    document.removeEventListener('keydown', _closeMoreMenuOnEscape);
    window.removeEventListener('resize', closeMoreMenu);
}

// -----------------------------------------------------------------------
// Test All Feeds
// -----------------------------------------------------------------------

async function testAllFeeds() {
    const btn = document.getElementById('test-all-btn');
    if (!btn) return;
    btn.disabled = true;
    btn.textContent = '测试中...';

    try {
        let url = '/api/v1/sources/test_all';
        if (currentBoardSlug) url += `?board=${encodeURIComponent(currentBoardSlug)}`;
        const res = await fetch(url, { method: 'POST' });
        if (!res.ok) throw new Error('Request failed');
        const results = await res.json();

        const resultList = Array.isArray(results) ? results : [];
        const resultByUrl = new Map(resultList.map(result => [result.url, result]));
        currentBoardSources.forEach((source, index) => {
            const statusKey = source.id != null ? source.id : index;
            const statusEl = document.getElementById(`source-status-${statusKey}`);
            const result = resultByUrl.get(source.url) || resultList[index];
            renderSourceTestStatus(statusEl, result);
        });
    } catch (e) {
        console.error('Test all feeds failed:', e);
    } finally {
        btn.disabled = false;
        btn.textContent = '测试全部';
    }
}
