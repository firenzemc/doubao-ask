import { cli, Strategy } from '@jackwener/opencli/registry';
import { ArgumentError } from '@jackwener/opencli/errors';
import { DOUBAO_DOMAIN } from './utils.js';
// Generic humanized drag with trusted CDP input at viewport coordinates.
// Needed because the Doubao captcha lives in a cross-origin iframe — DOM
// selectors can't reach in, but trusted Input events hit whatever is at the
// coordinates, iframe or not.
export const dragCommand = cli({
    site: 'doubao',
    name: 'drag',
    access: 'write',
    description: 'Humanized trusted drag between two viewport points (for captcha interaction)',
    domain: DOUBAO_DOMAIN,
    strategy: Strategy.COOKIE,
    browser: true,
    siteSession: 'persistent',
    navigateBefore: false,
    args: [
        { name: 'from-x', type: 'int', required: true, help: 'Start X (viewport px)' },
        { name: 'from-y', type: 'int', required: true, help: 'Start Y (viewport px)' },
        { name: 'to-x', type: 'int', required: true, help: 'End X (viewport px)' },
        { name: 'to-y', type: 'int', required: true, help: 'End Y (viewport px)' },
        { name: 'steps', type: 'int', required: false, default: 0, help: 'Intermediate moves (default: 24-33 random)' },
    ],
    columns: ['Status', 'Detail'],
    func: async (page, kwargs) => {
        const fromX = kwargs['from-x'];
        const fromY = kwargs['from-y'];
        const toX = kwargs['to-x'];
        const toY = kwargs['to-y'];
        for (const v of [fromX, fromY, toX, toY]) {
            if (!Number.isInteger(v)) {
                throw new ArgumentError('coordinates must be integers');
            }
        }
        const steps = kwargs.steps > 0 ? kwargs.steps : 24 + Math.floor(Math.random() * 10);
        const distX = toX - fromX;
        const distY = toY - fromY;
        // Ease-out curve + jitter + variable timing: anti-bot discipline.
        await page.cdp('Input.dispatchMouseEvent', { type: 'mouseMoved', x: fromX, y: fromY });
        await page.wait(0.15 + Math.random() * 0.2);
        await page.cdp('Input.dispatchMouseEvent', { type: 'mousePressed', x: fromX, y: fromY, button: 'left', clickCount: 1 });
        for (let i = 1; i <= steps; i++) {
            const t = i / steps;
            const ease = 1 - Math.pow(1 - t, 2.2);
            const x = Math.round(fromX + distX * ease + (Math.random() - 0.5) * 2);
            const y = Math.round(fromY + distY * ease + (Math.random() - 0.5) * 3);
            await page.cdp('Input.dispatchMouseEvent', { type: 'mouseMoved', x, y, button: 'left', buttons: 1 });
            await page.wait(0.02 + Math.random() * 0.05);
        }
        await page.wait(0.12 + Math.random() * 0.2);
        await page.cdp('Input.dispatchMouseEvent', { type: 'mouseReleased', x: toX, y: toY, button: 'left', clickCount: 1 });
        return [{ Status: 'Dragged', Detail: `(${fromX},${fromY}) -> (${toX},${toY}) in ${steps} steps` }];
    },
});
export const clickAtCommand = cli({
    site: 'doubao',
    name: 'click-at',
    access: 'write',
    description: 'Trusted click at viewport coordinates (for captcha buttons inside iframes)',
    domain: DOUBAO_DOMAIN,
    strategy: Strategy.COOKIE,
    browser: true,
    siteSession: 'persistent',
    navigateBefore: false,
    args: [
        { name: 'x', type: 'int', required: true, help: 'X (viewport px)' },
        { name: 'y', type: 'int', required: true, help: 'Y (viewport px)' },
    ],
    columns: ['Status', 'Detail'],
    func: async (page, kwargs) => {
        const x = kwargs.x;
        const y = kwargs.y;
        if (!Number.isInteger(x) || !Number.isInteger(y)) {
            throw new ArgumentError('coordinates must be integers');
        }
        await page.nativeClick(x, y);
        return [{ Status: 'Clicked', Detail: `(${x},${y})` }];
    },
});
