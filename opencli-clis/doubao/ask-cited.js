import { cli, Strategy } from '@jackwener/opencli/registry';
import { ArgumentError } from '@jackwener/opencli/errors';
import { DOUBAO_DOMAIN, getDoubaoTranscriptLines, getDoubaoVisibleTurns, sendDoubaoMessage, startNewDoubaoChat, waitForDoubaoResponse } from './utils.js';
// Citation markers render as inline site-name spans (no href in the DOM).
// Clicking one calls window.open with the real source URL, so we stub
// window.open and click each marker to harvest the links.
// NOTE: 'container-DEV3jt' is a hashed CSS class from Doubao's frontend —
// if citation extraction suddenly returns empty, re-inspect the marker class.
const extractCitationsScript = `(async () => {
  const spans = [...document.querySelectorAll('span.container-DEV3jt')];
  const opened = [];
  window.open = (u) => { opened.push(u); return null; };
  const results = [];
  for (const s of spans) {
    const name = (s.textContent || '').trim();
    const before = opened.length;
    // Humanize the clicks: random point inside the element (never dead
    // center) and a random 1–3s pause between citations — Linux/datacenter
    // browsers are already high-risk, bursts of identical clicks make it worse.
    const r = s.getBoundingClientRect();
    const x = r.left + r.width * (0.2 + Math.random() * 0.6);
    const y = r.top + r.height * (0.2 + Math.random() * 0.6);
    for (const t of ['pointerdown', 'mousedown', 'mouseup']) {
      s.dispatchEvent(new MouseEvent(t, { bubbles: true, cancelable: true, clientX: x, clientY: y }));
    }
    s.click();
    await new Promise((res) => setTimeout(res, 1000 + Math.random() * 2000));
    const url = opened.length > before ? opened[opened.length - 1] : '';
    if (url) results.push({ name, url });
  }
  const seen = new Set();
  return results.filter((c) => c.url && !seen.has(c.url) && seen.add(c.url));
})()`;
export const askCitedCommand = cli({
    site: 'doubao',
    name: 'ask-cited',
    access: 'write',
    description: 'Ask in a new Doubao conversation, return the answer plus citation links',
    domain: DOUBAO_DOMAIN,
    strategy: Strategy.COOKIE,
    browser: true,
    siteSession: 'persistent',
    navigateBefore: false,
    args: [
        { name: 'text', required: true, positional: true, help: 'Prompt to send' },
        { name: 'timeout', type: 'int', required: false, help: 'Max seconds to wait (default: 90)', default: 90 },
    ],
    columns: ['Answer', 'Citations'],
    func: async (page, kwargs) => {
        const text = kwargs.text;
        const timeout = kwargs.timeout;
        if (!Number.isInteger(timeout) || timeout < 1) {
            throw new ArgumentError('--timeout must be a positive integer (seconds)');
        }
        await startNewDoubaoChat(page);
        const beforeTurns = await getDoubaoVisibleTurns(page);
        const beforeLines = await getDoubaoTranscriptLines(page);
        await sendDoubaoMessage(page, text);
        const response = await waitForDoubaoResponse(page, beforeLines, beforeTurns, text, timeout);
        if (!response) {
            return [{ Answer: '', Citations: JSON.stringify({ error: `No response within ${timeout}s. Doubao may still be generating.` }) }];
        }
        const citations = await page.evaluate(extractCitationsScript).catch(() => []);
        return [{ Answer: response, Citations: JSON.stringify(citations || []) }];
    },
});
