import { cli, Strategy } from '@jackwener/opencli/registry';
import { DOUBAO_DOMAIN } from './utils.js';
// Locate the captcha iframe and report its geometry. Cross-origin, so we
// can't reach inside — but trusted CDP mouse events work at viewport
// coordinates regardless of iframe boundaries.
const findChallengeScript = `(() => {
  const f = document.querySelector('iframe[src*="captcha"], iframe[src*="verify"]');
  if (!f) return null;
  const r = f.getBoundingClientRect();
  return { x: r.left, y: r.top, w: r.width, h: r.height, src: (f.src || '').slice(0, 120) };
})()`;
export const solveSliderCommand = cli({
    site: 'doubao',
    name: 'solve-slider',
    access: 'write',
    description: 'Attempt a humanized trusted drag on the Doubao captcha slider',
    domain: DOUBAO_DOMAIN,
    strategy: Strategy.COOKIE,
    browser: true,
    siteSession: 'persistent',
    navigateBefore: false,
    args: [
        { name: 'distance', type: 'int', required: false, default: 0, help: 'Drag distance in px (default: ~72% of frame width)' },
        { name: 'handle-x', type: 'int', required: false, default: 42, help: 'Slider handle offset from frame left (px)' },
        { name: 'handle-y-ratio', type: 'float', required: false, default: 0.62, help: 'Slider handle height as fraction of frame height' },
    ],
    columns: ['Status', 'Detail'],
    func: async (page, kwargs) => {
        const frame = await page.evaluate(findChallengeScript);
        if (!frame) {
            return [{ Status: 'NoChallenge', Detail: 'no captcha iframe found on the page' }];
        }
        const frameInfo = `frame ${Math.round(frame.w)}x${Math.round(frame.h)} @ (${Math.round(frame.x)},${Math.round(frame.y)})`;
        const fromX = Math.round(frame.x + kwargs['handle-x']);
        const fromY = Math.round(frame.y + frame.h * kwargs['handle-y-ratio']);
        const dist = kwargs.distance > 0 ? kwargs.distance : Math.round(frame.w * 0.72);
        const toX = fromX + dist;
        const toY = fromY + Math.round((Math.random() - 0.5) * 4);
        // Humanized drag with trusted CDP input: ease-out curve, jittered
        // positions, variable per-step timing (see anti-bot discipline).
        const steps = 24 + Math.floor(Math.random() * 10);
        await page.cdp('Input.dispatchMouseEvent', { type: 'mouseMoved', x: fromX, y: fromY });
        await page.wait(0.15 + Math.random() * 0.2);
        await page.cdp('Input.dispatchMouseEvent', { type: 'mousePressed', x: fromX, y: fromY, button: 'left', clickCount: 1 });
        for (let i = 1; i <= steps; i++) {
            const t = i / steps;
            const ease = 1 - Math.pow(1 - t, 2.2);
            const x = Math.round(fromX + dist * ease + (Math.random() - 0.5) * 2);
            const y = Math.round(fromY + (toY - fromY) * t + (Math.random() - 0.5) * 3);
            await page.cdp('Input.dispatchMouseEvent', { type: 'mouseMoved', x, y, button: 'left', buttons: 1 });
            await page.wait(0.02 + Math.random() * 0.05);
        }
        await page.wait(0.12 + Math.random() * 0.2);
        await page.cdp('Input.dispatchMouseEvent', { type: 'mouseReleased', x: toX, y: toY, button: 'left', clickCount: 1 });
        await page.wait(1.5);
        const still = await page.evaluate(findChallengeScript);
        return [{
                Status: still ? 'StillBlocked' : 'MaybeSolved',
                Detail: `${frameInfo}; dragged (${fromX},${fromY}) -> (${toX},${toY}); ` + (still
                    ? `challenge iframe still present (${still.src})`
                    : 'challenge iframe gone — retry the ask now'),
            }];
    },
});
