function addLinkTarget(html) {
  const base = '<base target="_blank">';
  if (/<head(?:\s[^>]*)?>/i.test(html)) {
    return html.replace(/<head(\s[^>]*)?>/i, (match) => `${match}${base}`);
  }
  return `${base}${html}`;
}

window.addEventListener('message', (event) => {
  if (event.source !== parent || event.data?.type !== 'EIDO_RENDER_HTML') return;
  const html = typeof event.data.html === 'string' ? event.data.html : '';
  document.open();
  document.write(addLinkTarget(html));
  document.close();
});

parent.postMessage({ type: 'EIDO_PREVIEW_READY' }, '*');
