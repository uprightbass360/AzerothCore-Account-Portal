import { beforeEach, describe, expect, it, vi } from 'vitest';

vi.mock('$lib/server/api', async (orig) => {
	const mod = (await orig()) as object;
	return { ...mod, api: vi.fn(), clearSessionCookie: vi.fn(), refreshSessionCookie: vi.fn() };
});
vi.mock('$env/dynamic/private', () => ({
	env: { BACKEND_URL: 'http://b', INTERNAL_API_KEY: 'k' }
}));

import { api, clearSessionCookie, refreshSessionCookie } from '$lib/server/api';
import { handle } from './hooks.server';

const USER = { username: 'BOB', email: null, totp_enabled: false, is_admin: false };

function makeEvent(path: string, cookie?: string) {
	return {
		url: new URL(`http://portal.test${path}`),
		cookies: { get: vi.fn().mockReturnValue(cookie), delete: vi.fn() },
		locals: {} as { user: unknown },
		fetch: vi.fn()
	};
}
const resolve = vi.fn().mockResolvedValue(new Response('ok'));

beforeEach(() => vi.clearAllMocks());

describe('handle', () => {
	it('no cookie → anonymous, public routes pass', async () => {
		const event = makeEvent('/login');
		await handle({ event, resolve } as never);
		expect(event.locals.user).toBeNull();
		expect(resolve).toHaveBeenCalled();
	});

	it('valid cookie → locals.user set, cookie refreshed', async () => {
		vi.mocked(api).mockResolvedValue({ status: 200, data: USER });
		const event = makeEvent('/account', 'tok');
		await handle({ event, resolve } as never);
		expect(event.locals.user).toEqual(USER);
		expect(refreshSessionCookie).toHaveBeenCalledWith(event);
	});

	it('stale cookie → cleared, guard redirects, cookie not refreshed', async () => {
		vi.mocked(api).mockResolvedValue({ status: 401, data: {} });
		const event = makeEvent('/account', 'tok');
		await expect(handle({ event, resolve } as never)).rejects.toMatchObject({
			status: 303,
			location: '/login'
		});
		expect(clearSessionCookie).toHaveBeenCalled();
		expect(refreshSessionCookie).not.toHaveBeenCalled();
	});

	it('non-admin on /admin → redirected to /account', async () => {
		vi.mocked(api).mockResolvedValue({ status: 200, data: USER });
		const event = makeEvent('/admin/invites', 'tok');
		await expect(handle({ event, resolve } as never)).rejects.toMatchObject({
			status: 303,
			location: '/account'
		});
	});

	it('admin on /admin → passes', async () => {
		vi.mocked(api).mockResolvedValue({ status: 200, data: { ...USER, is_admin: true } });
		const event = makeEvent('/admin/invites', 'tok');
		await handle({ event, resolve } as never);
		expect(resolve).toHaveBeenCalled();
	});
});
