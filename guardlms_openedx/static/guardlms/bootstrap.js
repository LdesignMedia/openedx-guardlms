/* Loaded by Django pages and Tutor MFE external-script hooks. No user context. */
(() => {
  if (window.__guardlmsOpenEdxBoot) return;
  window.__guardlmsOpenEdxBoot = true;
  const source = document.currentScript;
  if (!source) return;
  const origin = new URL(source.src).origin;
  const configUrl = `${origin}/guardlms/browser-config`;
  let running = false;
  let config;
  function stop() {
    if (window.GuardLMS && running) {
      window.GuardLMS.destroy();
      running = false;
    }
  }
  async function refresh() {
    try {
      const response = await fetch(configUrl, { cache: 'no-store', credentials: 'omit' });
      if (!response.ok) { stop(); return; }
      const next = await response.json();
      if (!next.apiKey) { stop(); return; }
      const serialized = JSON.stringify(next);
      if (serialized === config && running) return;
      stop();
      if (!window.GuardLMS) {
        await new Promise((resolve, reject) => {
          const script = document.createElement('script');
          script.src = next.sdkUrl;
          script.onload = resolve;
          script.onerror = reject;
          document.head.appendChild(script);
        });
      }
      // Deployment SDK handles SPA navigation and plan-gated page/scroll analytics.
      window.GuardLMS.init({ ...next, releaseStage: 'production',
        autoDetectErrors: next.autoDetectErrors,
        networkBreadcrumbsEnabled: next.autoDetectErrors,
        consoleBreadcrumbsEnabled: false,
        interactionBreadcrumbsEnabled: false,
        onError: (error) => next.autoDetectErrors ? error : null,
        beforeSend: (error) => next.autoDetectErrors ? error : null,
      });
      config = serialized;
      running = true;
    } catch (_) { stop(); }
  }
  refresh();
  // Respect disconnect and changed preferences in already-open browser tabs.
  window.setInterval(refresh, 60000);
})();
