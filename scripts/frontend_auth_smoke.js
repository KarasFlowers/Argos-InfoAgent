const fs = require('node:fs');
const vm = require('node:vm');

const appJs = fs.readFileSync('app/web/static/app.js', 'utf8');

function createContext({ apiKey = '', responseStatus = 200 } = {}) {
  const calls = [];
  const pendingFetches = [];
  const localStorageData = new Map(apiKey ? [['argos_api_key', apiKey]] : []);
  let reloadCount = 0;
  const window = {
    location: {
      origin: 'http://127.0.0.1:8000',
      reload: () => { reloadCount += 1; },
    },
    matchMedia: () => ({ matches: false }),
    fetch: async (input, init) => {
      calls.push({
        input,
        headers: Object.fromEntries(new Headers(init?.headers || {}).entries()),
      });
      if (pendingFetches.length > 0) {
        await pendingFetches.shift();
      }
      return { status: responseStatus, ok: responseStatus >= 200 && responseStatus < 300 };
    },
  };

  const context = {
    console,
    window,
    document: { addEventListener: () => {} },
    localStorage: {
      getItem: (key) => localStorageData.get(key) || null,
      setItem: (key, value) => localStorageData.set(key, value),
      removeItem: (key) => localStorageData.delete(key),
    },
    sessionStorage: {
      getItem: () => null,
      setItem: () => {},
      removeItem: () => {},
    },
    Headers,
    Request,
    URL,
    HTMLElement: class HTMLElement {},
    setTimeout: () => 0,
    requestAnimationFrame: () => {},
  };
  context.globalThis = context;
  context.calls = calls;
  context.deferNextFetch = () => {
    let resolve;
    pendingFetches.push(new Promise((done) => { resolve = done; }));
    return resolve;
  };
  context.getReloadCount = () => reloadCount;
  context.getStoredApiKey = () => localStorageData.get('argos_api_key') || '';
  return context;
}

function apiKeyDialogDocument(inputValue) {
  const input = { value: inputValue };
  const message = {
    textContent: '',
    attributes: {},
    setAttribute: (key, value) => { message.attributes[key] = value; },
  };
  const save = { disabled: false, textContent: '保存并刷新' };
  const button = { classList: { toggle: () => {} }, title: '' };
  return {
    elements: { input, message, save, button },
    getElementById: (id) => ({
      'api-key-input': input,
      'api-key-message': message,
      'api-key-save': save,
      'settings-btn': button,
    })[id] || null,
    addEventListener: () => {},
  };
}

async function main() {
  const withKey = createContext({ apiKey: 'secret-key' });
  vm.runInNewContext(appJs, withKey, { filename: 'app.js' });

  await withKey.window.fetch('/api/v1/boards');
  await withKey.window.fetch('http://127.0.0.1:8000/api/v1/summary');
  await withKey.window.fetch('https://example.com/api/v1/boards');

  const [relative, sameOriginAbsolute, external] = withKey.calls;
  if (relative.headers['x-api-key'] !== 'secret-key') {
    throw new Error('Expected relative same-origin API request to include X-API-Key');
  }
  if (sameOriginAbsolute.headers['x-api-key'] !== 'secret-key') {
    throw new Error('Expected absolute same-origin API request to include X-API-Key');
  }
  if (external.headers['x-api-key']) {
    throw new Error('External request leaked X-API-Key');
  }

  const withoutKey = createContext();
  vm.runInNewContext(appJs, withoutKey, { filename: 'app.js' });
  await withoutKey.window.fetch('/api/v1/boards');
  if (withoutKey.calls[0].headers['x-api-key']) {
    throw new Error('Request without stored key should not include X-API-Key');
  }

  const wrongKey = createContext({ responseStatus: 403 });
  vm.runInNewContext(appJs, wrongKey, { filename: 'app.js' });
  wrongKey.document = apiKeyDialogDocument('wrong-key');
  await wrongKey.saveApiKeyFromDialog();
  if (wrongKey.getStoredApiKey()) {
    throw new Error('Invalid API key should not be stored');
  }
  if (wrongKey.getReloadCount() !== 0) {
    throw new Error('Invalid API key should not reload the page');
  }
  if (wrongKey.document.elements.message.attributes.role !== 'alert') {
    throw new Error('Invalid API key should be announced as an alert');
  }

  const correctKey = createContext({ responseStatus: 200 });
  vm.runInNewContext(appJs, correctKey, { filename: 'app.js' });
  correctKey.document = apiKeyDialogDocument('secret-key');
  await correctKey.saveApiKeyFromDialog();
  if (correctKey.getStoredApiKey() !== 'secret-key') {
    throw new Error('Valid API key should be stored after verification');
  }
  if (correctKey.getReloadCount() !== 1) {
    throw new Error('Valid API key should reload the page once');
  }

  const duplicateSubmit = createContext({ responseStatus: 200 });
  vm.runInNewContext(appJs, duplicateSubmit, { filename: 'app.js' });
  duplicateSubmit.document = apiKeyDialogDocument('secret-key');
  const releaseValidation = duplicateSubmit.deferNextFetch();
  const firstSave = duplicateSubmit.saveApiKeyFromDialog();
  const secondSave = duplicateSubmit.saveApiKeyFromDialog();
  if (duplicateSubmit.calls.length !== 1) {
    throw new Error('Duplicate API key saves should share one in-flight validation');
  }
  if (duplicateSubmit.document.elements.message.attributes.role !== 'status') {
    throw new Error('API key validation progress should be announced as status');
  }
  releaseValidation();
  await Promise.all([firstSave, secondSave]);
  if (duplicateSubmit.getReloadCount() !== 1) {
    throw new Error('Duplicate API key saves should reload the page once');
  }

  console.log('Frontend auth smoke passed: X-API-Key is scoped and API key saves are verified before a single reload.');
}

main().catch((error) => {
  console.error(`Frontend auth smoke failed: ${error.message}`);
  process.exit(1);
});
