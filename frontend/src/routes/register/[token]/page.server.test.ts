import { beforeEach, describe, expect, it, vi } from 'vitest';

vi.mock('$lib/server/api', async (orig) => {
	const mod = (await orig()) as object;
	return { ...mod, api: vi.fn() };
});
vi.mock('$env/dynamic/private', () => ({ env: {} }));

import { api } from '$lib/server/api';
import { actions, load } from './+page.server';

function formEvent(fields: Record<string, string>) {
	const fd = new FormData();
	for (const [k, v] of Object.entries(fields)) fd.set(k, v);
	return {
		request: new Request('http://t.est', { method: 'POST', body: fd }),
		params: { token: 'tok123' },
		cookies: { get: vi.fn(), set: vi.fn(), delete: vi.fn() },
		url: new URL('http://t.est/register/tok123'),
		fetch: vi.fn(),
		locals: { user: null }
	} as never;
}

beforeEach(() => vi.clearAllMocks());

describe('load', () => {
	it('returns invite email when valid', async () => {
		vi.mocked(api).mockResolvedValue({ status: 200, data: { email: 'a@b.c' } });
		const res = await load(formEvent({}));
		expect(res).toEqual({ email: 'a@b.c' });
		expect(api).toHaveBeenCalledWith(expect.anything(), 'GET', '/api/v1/register/tok123');
	});

	it('maps 404/410 to invalid states', async () => {
		vi.mocked(api).mockResolvedValue({ status: 404, data: { detail: 'Invite not found' } });
		expect(await load(formEvent({}))).toEqual({ invalid: 'Invite not found' });
		vi.mocked(api).mockResolvedValue({ status: 410, data: { detail: 'Invite expired' } });
		expect(await load(formEvent({}))).toEqual({ invalid: 'Invite expired' });
	});

	it('falls back to a generic message when the backend omits detail', async () => {
		vi.mocked(api).mockResolvedValue({ status: 500, data: {} });
		expect(await load(formEvent({}))).toEqual({ invalid: 'This invite link is not valid' });
	});
});

describe('register action', () => {
	const good = { username: 'Newbie1', password: 'hunter2!!', confirm: 'hunter2!!' };

	it('registers and reports success', async () => {
		vi.mocked(api).mockResolvedValue({ status: 201, data: { username: 'NEWBIE1' } });
		const res = await actions.default(formEvent(good));
		expect(res).toEqual({ success: true, username: 'NEWBIE1' });
		expect(api).toHaveBeenCalledWith(expect.anything(), 'POST', '/api/v1/register/tok123', {
			username: 'Newbie1',
			password: 'hunter2!!'
		});
	});

	it('rejects invalid form input locally', async () => {
		const res = await actions.default(formEvent({ ...good, confirm: 'different1' }));
		expect(res).toMatchObject({ status: 400 });
		expect(api).not.toHaveBeenCalled();
	});

	it('surfaces backend errors (409 taken, 410 gone, 503 down)', async () => {
		vi.mocked(api).mockResolvedValue({ status: 409, data: { detail: 'Username already taken' } });
		let res = await actions.default(formEvent(good));
		expect(res).toMatchObject({ status: 409, data: { message: 'Username already taken' } });
		vi.mocked(api).mockResolvedValue({
			status: 503,
			data: { detail: 'Game server temporarily unavailable' }
		});
		res = await actions.default(formEvent(good));
		expect(res).toMatchObject({ status: 503 });
	});

	it('falls back to a generic message when the backend omits detail', async () => {
		vi.mocked(api).mockResolvedValue({ status: 500, data: {} });
		const res = await actions.default(formEvent(good));
		expect(res).toMatchObject({ status: 500, data: { message: 'Registration failed' } });
	});
});
