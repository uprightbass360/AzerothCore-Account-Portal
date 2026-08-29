import { beforeEach, describe, expect, it, vi } from 'vitest';

vi.mock('$lib/server/api', async (orig) => {
	const mod = (await orig()) as object;
	return { ...mod, api: vi.fn(), setSessionCookie: vi.fn() };
});
vi.mock('$env/dynamic/private', () => ({ env: {} }));

import { api, setSessionCookie } from '$lib/server/api';
import { actions, load } from './+page.server';

function formEvent(fields: Record<string, string>, cookie?: string) {
	const fd = new FormData();
	for (const [k, v] of Object.entries(fields)) fd.set(k, v);
	return {
		request: new Request('http://t.est', { method: 'POST', body: fd }),
		cookies: { get: vi.fn().mockReturnValue(cookie), set: vi.fn(), delete: vi.fn() },
		url: new URL('http://t.est/login'),
		fetch: vi.fn(),
		locals: { user: null }
	} as never;
}

beforeEach(() => vi.clearAllMocks());

describe('load', () => {
	it('redirects logged-in users to /account', () => {
		try {
			load({ locals: { user: { username: 'X' } } } as never);
			expect.unreachable('should have redirected');
		} catch (e) {
			expect(e).toMatchObject({ status: 303, location: '/account' });
		}
		expect(load({ locals: { user: null } } as never)).toEqual({});
	});
});

describe('login action', () => {
	it('sets cookie and redirects on success', async () => {
		vi.mocked(api).mockResolvedValue({
			status: 200,
			data: { token: 't0k', expires_at: '2027-01-01T00:00:00Z' }
		});
		await expect(
			actions.login(formEvent({ username: 'bob', password: 'pw123456' }))
		).rejects.toMatchObject({
			status: 303,
			location: '/account'
		});
		expect(setSessionCookie).toHaveBeenCalledWith(expect.anything(), 't0k', '2027-01-01T00:00:00Z');
	});

	it('returns twofa step when required', async () => {
		vi.mocked(api).mockResolvedValue({ status: 200, data: { status: '2fa_required' } });
		const res = await actions.login(formEvent({ username: 'bob', password: 'pw123456' }));
		expect(res).toEqual({ twofa: true, username: 'bob', password: 'pw123456' });
	});

	it('fails with message on 401 and 429', async () => {
		vi.mocked(api).mockResolvedValue({
			status: 401,
			data: { detail: 'Invalid username or password' }
		});
		let res = await actions.login(formEvent({ username: 'bob', password: 'x1234567' }));
		expect(res).toMatchObject({ status: 401, data: { message: 'Invalid username or password' } });
		vi.mocked(api).mockResolvedValue({
			status: 429,
			data: { detail: 'Too many attempts, try again later' }
		});
		res = await actions.login(formEvent({ username: 'bob', password: 'x1234567' }));
		expect(res).toMatchObject({ status: 429 });
	});

	it('fails on invalid form input without calling the api', async () => {
		const res = await actions.login(formEvent({ username: '', password: '' }));
		expect(res).toMatchObject({ status: 400 });
		expect(api).not.toHaveBeenCalled();
	});

	it('falls back to a generic message when the backend omits detail', async () => {
		vi.mocked(api).mockResolvedValue({ status: 500, data: {} });
		const res = await actions.login(formEvent({ username: 'bob', password: 'x1234567' }));
		expect(res).toMatchObject({ status: 500, data: { message: 'Login failed' } });
	});
});

describe('twofa action', () => {
	it('issues session on valid code', async () => {
		vi.mocked(api).mockResolvedValue({
			status: 200,
			data: { token: 't0k', expires_at: '2027-01-01T00:00:00Z' }
		});
		await expect(
			actions.twofa(formEvent({ username: 'bob', password: 'pw123456', code: '123456' }))
		).rejects.toMatchObject({ status: 303 });
	});

	it('keeps the twofa form on invalid code', async () => {
		vi.mocked(api).mockResolvedValue({ status: 401, data: { detail: 'Invalid code' } });
		const res = await actions.twofa(
			formEvent({ username: 'bob', password: 'pw123456', code: '111111' })
		);
		expect(res).toMatchObject({ status: 401, data: { twofa: true, message: 'Invalid code' } });
	});

	it('fails on invalid code format without calling the api', async () => {
		const res = await actions.twofa(
			formEvent({ username: 'bob', password: 'pw123456', code: 'abc' })
		);
		expect(res).toMatchObject({ status: 400, data: { twofa: true } });
		expect(api).not.toHaveBeenCalled();
	});

	it('falls back to a generic message when the backend omits detail', async () => {
		vi.mocked(api).mockResolvedValue({ status: 500, data: {} });
		const res = await actions.twofa(
			formEvent({ username: 'bob', password: 'pw123456', code: '111111' })
		);
		expect(res).toMatchObject({ status: 500, data: { message: 'Login failed' } });
	});
});
