import { beforeEach, describe, expect, it, vi } from 'vitest';

vi.mock('$lib/server/api', async (orig) => {
	const mod = (await orig()) as object;
	return { ...mod, api: vi.fn() };
});
vi.mock('$env/dynamic/private', () => ({ env: {} }));

import { api } from '$lib/server/api';
import { actions, load } from './+page.server';

function makeEvent() {
	return {
		request: new Request('http://t.est', { method: 'POST' }),
		params: { token: 'tok/123' },
		cookies: { get: vi.fn(), set: vi.fn(), delete: vi.fn() },
		url: new URL('http://t.est/confirm-email/tok123'),
		fetch: vi.fn(),
		locals: { user: null }
	} as never;
}

beforeEach(() => vi.clearAllMocks());

describe('load', () => {
	it('returns the pending email for a valid token, url-encoding it', async () => {
		vi.mocked(api).mockResolvedValue({ status: 200, data: { new_email: 'new@addr.example' } });
		expect(await load(makeEvent())).toEqual({ newEmail: 'new@addr.example' });
		expect(api).toHaveBeenCalledWith(expect.anything(), 'GET', '/api/v1/email-change/tok%2F123');
	});

	it('maps failures to an invalid state with and without detail', async () => {
		vi.mocked(api).mockResolvedValue({ status: 410, data: { detail: 'already used' } });
		expect(await load(makeEvent())).toEqual({ invalid: 'already used' });
		vi.mocked(api).mockResolvedValue({ status: 404, data: {} });
		expect(await load(makeEvent())).toEqual({ invalid: 'This confirmation link is not valid' });
	});
});

describe('confirm action', () => {
	it('confirms and returns the username', async () => {
		vi.mocked(api).mockResolvedValue({
			status: 200,
			data: { username: 'TESTUSER', new_email: 'new@addr.example' }
		});
		expect(await actions.default(makeEvent())).toEqual({
			success: true,
			username: 'TESTUSER',
			newEmail: 'new@addr.example'
		});
		expect(api).toHaveBeenCalledWith(expect.anything(), 'POST', '/api/v1/email-change/tok%2F123');
	});

	it('surfaces failures with and without detail', async () => {
		vi.mocked(api).mockResolvedValue({
			status: 503,
			data: { detail: 'Game server temporarily unavailable' }
		});
		expect(await actions.default(makeEvent())).toMatchObject({
			status: 503,
			data: { message: 'Game server temporarily unavailable' }
		});
		vi.mocked(api).mockResolvedValue({ status: 500, data: {} });
		expect(await actions.default(makeEvent())).toMatchObject({
			data: { message: 'Confirmation failed' }
		});
	});
});
