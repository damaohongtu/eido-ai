(() => {
  if (window.__EIDO_CONTENT_SCRIPT_READY__) return;
  window.__EIDO_CONTENT_SCRIPT_READY__ = true;

  const MAX_TEXT_LENGTH = 80000;

  function cleanText(text) {
    return (text || '')
      .replace(/\s+/g, ' ')
      .replace(/[\u200B-\u200D\uFEFF]/g, '')
      .trim();
  }

  function getMeta(name) {
    const selector = [
      `meta[name="${name}"]`,
      `meta[property="${name}"]`,
      `meta[property="og:${name}"]`,
    ].join(',');
    return document.querySelector(selector)?.getAttribute('content') || '';
  }

  function collectHeadings(root) {
    return Array.from(root.querySelectorAll('h1,h2,h3'))
      .slice(0, 80)
      .map((node) => {
        const level = node.tagName.toLowerCase();
        const text = cleanText(node.textContent);
        return text ? `${level}: ${text}` : '';
      })
      .filter(Boolean);
  }

  function collectLinks(root) {
    return Array.from(root.querySelectorAll('a[href]'))
      .slice(0, 120)
      .map((node) => {
        const text = cleanText(node.textContent);
        const href = node.href;
        if (!text || !href) return '';
        return `${text} (${href})`;
      })
      .filter(Boolean);
  }

  function extractPage() {
    const root = document.querySelector('article') ||
      document.querySelector('main') ||
      document.body ||
      document.documentElement;

    const selection = cleanText(window.getSelection?.().toString() || '');
    const text = cleanText(root?.innerText || document.body?.innerText || '');
    const canonical = document.querySelector('link[rel="canonical"]')?.href || location.href;

    return {
      title: document.title || canonical,
      url: location.href,
      canonicalUrl: canonical,
      description: cleanText(getMeta('description')),
      siteName: cleanText(getMeta('site_name')),
      selection,
      headings: collectHeadings(root),
      links: collectLinks(root),
      text: text.slice(0, MAX_TEXT_LENGTH),
      truncated: text.length > MAX_TEXT_LENGTH,
      capturedAt: new Date().toISOString(),
    };
  }

  chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
    if (message?.type === 'EIDO_PING') {
      sendResponse({ ok: true });
      return false;
    }

    if (message?.type === 'EIDO_EXTRACT_PAGE') {
      sendResponse(extractPage());
      return false;
    }

    return false;
  });
})();
