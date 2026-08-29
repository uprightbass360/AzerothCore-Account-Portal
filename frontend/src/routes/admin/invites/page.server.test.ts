import { beforeEach, describe, expect, it, vi } from 'vitest';

vi.mock('$lib/server/api', async (orig) => {
	const mod = (await orig()) as object;
	return { ...mod, api: vi.fn() };
});
vi.mock('$env/dynamic/private', () => ({ env: {} }));

import { api } from '$lib/server/api';
import { actions, load } from './+page.server';

function formEvent(fields: Record<string, string>, search = '') {
	const fd = new FormData();
	for (const [k, v] of Object.entries(fields)) fd.set(k, v);
	return {
		request: new Request('http://t.est', { method: 'POST', body: fd }),
		cookies: { get: vi.fn(), set: vi.fn(), delete: vi.fn() },
		url: new URL(`http://t.est/admin/invites${search}`),
		fetch: vi.fn(),
		locals: { user: { username: 'BOSS', email: null, totp_enabled: false, is_admin: true } }
	} as never;
}

beforeEach(() => vi.clearAllMocks());

describe('load', () => {
	it('lists pending invites', async () => {
		vi.mocked(api).mockResolvedValue({ status: 200, data: { items: [{ id: 1, email: 'a@b.c' }] } });
		expect(await load(formEvent({}))).toEqual({ invites: [{ id: 1, email: 'a@b.c' }] });
	});

	it('falls back to an empty list when items is missing', async () => {
		vi.mocked(api).mockResolvedValue({ status: 200, data: {} });
		expect(await load(formEvent({}))).toEqual({ invites: [] });
	});
});

describe('send action', () => {
	it('validates email then posts', async () => {
		let res = await actions.send(formEvent({ email: 'bad' }));
		expect(res).toMatchObject({ status: 400 });
		expect(api).not.toHaveBeenCalled();

		vi.mocked(api).mockResolvedValue({ status: 201, data: { id: 2, email: 'a@b.co' } });
		res = await actions.send(formEvent({ email: 'a@b.co' }));
		expect(res).toEqual({ sent: 'a@b.co' });

		vi.mocked(api).mockResolvedValue({
			status: 502,
			data: { detail: 'Failed to send invite email' }
		});
		res = await actions.send(formEvent({ email: 'a@b.co' }));
		expect(res).toMatchObject({ status: 502, data: { message: 'Failed to send invite email' } });
	});

	it('falls back to a default message when the backend omits detail', async () => {
		vi.mocked(api).mockResolvedValue({ status: 500, data: {} });
		const res = await actions.send(formEvent({ email: 'a@b.co' }));
		expect(res).toMatchObject({ status: 500, data: { message: 'Invite failed' } });
	});
});

describe('revoke action', () => {
	it('deletes by id', async () => {
		vi.mocked(api).mockResolvedValue({ status: 200, data: { ok: true } });
		const res = await actions.revoke(formEvent({ id: '3' }));
		expect(res).toEqual({ revoked: true });
		expect(api).toHaveBeenCalledWith(expect.anything(), 'DELETE', '/api/v1/admin/invites/3');
		vi.mocked(api).mockResolvedValue({ status: 404, data: { detail: 'Invite not found' } });
		expect(await actions.revoke(formEvent({ id: '9' }))).toMatchObject({ status: 404 });
	});

	it('falls back to a default message when the backend omits detail', async () => {
		vi.mocked(api).mockResolvedValue({ status: 500, data: {} });
		const res = await actions.revoke(formEvent({ id: '9' }));
		expect(res).toMatchObject({ status: 500, data: { message: 'Revoke failed' } });
	});

	it('url-encodes the id', async () => {
		vi.mocked(api).mockResolvedValue({ status: 200, data: { ok: true } });
		await actions.revoke(formEvent({ id: '3/../4' }));
		expect(api).toHaveBeenCalledWith(
			expect.anything(),
			'DELETE',
			'/api/v1/admin/invites/3%2F..%2F4'
		);
	});
});
