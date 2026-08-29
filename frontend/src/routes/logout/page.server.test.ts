import { beforeEach, describe, expect, it, vi } from 'vitest';

vi.mock('$lib/server/api', async (orig) => {
	const mod = (await orig()) as object;
	return { ...mod, api: vi.fn(), clearSessionCookie: vi.fn() };
});
vi.mock('$env/dynamic/private', () => ({ env: {} }));

import { api, clearSessionCookie } from '$lib/server/api';
import { actions } from './+page.server';

function makeEvent() {
	return {
		cookies: { get: vi.fn(), set: vi.fn(), delete: vi.fn() },
		url: new URL('http://t.est/logout'),
		fetch: vi.fn(),
		locals: { user: null }
	} as never;
}

beforeEach(() => vi.clearAllMocks());

describe('logout action', () => {
	it('calls the backend, clears the cookie, and redirects to /login', async () => {
		vi.mocked(api).mockResolvedValue({ status: 200, data: {} });
		await expect(actions.default(makeEvent())).rejects.toMatchObject({
			status: 303,
			location: '/login'
		});
		expect(api).toHaveBeenCalledWith(expect.anything(), 'POST', '/api/v1/auth/logout');
		expect(clearSessionCookie).toHaveBeenCalled();
	});
});
