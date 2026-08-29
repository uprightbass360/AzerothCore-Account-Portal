import { beforeEach, describe, expect, it, vi } from 'vitest';

vi.mock('$lib/server/api', async (orig) => {
	const mod = (await orig()) as object;
	return { ...mod, api: vi.fn() };
});
vi.mock('$env/dynamic/private', () => ({ env: {} }));

import { api } from '$lib/server/api';
import { GET } from './+server';

function requestEvent(token: string, username: string | null) {
	const url = new URL(`http://t.est/register/${token}/check-username`);
	if (username !== null) url.searchParams.set('username', username);
	return {
		params: { token },
		url,
		cookies: { get: vi.fn(), set: vi.fn(), delete: vi.fn() },
		fetch: vi.fn(),
		locals: { user: null }
	} as never;
}

beforeEach(() => vi.clearAllMocks());

describe('GET /register/[token]/check-username', () => {
	it('forwards the username query param and the backend status/body', async () => {
		vi.mocked(api).mockResolvedValue({ status: 200, data: { valid: true, available: true } });
		const res = await GET(requestEvent('tok123', 'newname'));
		expect(api).toHaveBeenCalledWith(
			expect.anything(),
			'GET',
			'/api/v1/register/tok123/check-username?username=newname'
		);
		expect(res.status).toBe(200);
		expect(await res.json()).toEqual({ valid: true, available: true });
	});

	it('url-encodes the token and username', async () => {
		vi.mocked(api).mockResolvedValue({ status: 200, data: { valid: false, available: false } });
		await GET(requestEvent('tok/123', 'a b?'));
		expect(api).toHaveBeenCalledWith(
			expect.anything(),
			'GET',
			'/api/v1/register/tok%2F123/check-username?username=a%20b%3F'
		);
	});

	it('defaults to an empty username when the query param is missing', async () => {
		vi.mocked(api).mockResolvedValue({ status: 200, data: { valid: false, available: false } });
		await GET(requestEvent('tok123', null));
		expect(api).toHaveBeenCalledWith(
			expect.anything(),
			'GET',
			'/api/v1/register/tok123/check-username?username='
		);
	});

	it('passes through a non-200 backend status', async () => {
		vi.mocked(api).mockResolvedValue({ status: 404, data: { detail: 'Invite not found' } });
		const res = await GET(requestEvent('bogus', 'name'));
		expect(res.status).toBe(404);
		expect(await res.json()).toEqual({ detail: 'Invite not found' });
	});
});
