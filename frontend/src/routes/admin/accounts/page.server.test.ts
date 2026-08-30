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
		url: new URL(`http://t.est/admin/accounts${search}`),
		fetch: vi.fn(),
		locals: { user: { username: 'BOSS', email: null, totp_enabled: false, is_admin: true } }
	} as never;
}

beforeEach(() => vi.clearAllMocks());

describe('load', () => {
	it('forwards search and page params', async () => {
		vi.mocked(api).mockResolvedValue({
			status: 200,
			data: { items: [{ username: 'A' }], total: 1, page: 2, pages: 3 }
		});
		const res = await load(formEvent({}, '?search=alp&page=2'));
		expect(api).toHaveBeenCalledWith(
			expect.anything(),
			'GET',
			'/api/v1/admin/accounts?search=alp&page=2&bots=false'
		);
		expect(res).toEqual({
			accounts: [{ username: 'A' }],
			total: 1,
			page: 2,
			pages: 3,
			search: 'alp',
			bots: false
		});
	});

	it('defaults search, page and result fields when absent', async () => {
		vi.mocked(api).mockResolvedValue({ status: 200, data: {} });
		const res = await load(formEvent({}));
		expect(api).toHaveBeenCalledWith(
			expect.anything(),
			'GET',
			'/api/v1/admin/accounts?search=&page=1&bots=false'
		);
		expect(res).toEqual({ accounts: [], total: 0, page: 1, pages: 1, search: '', bots: false });
	});

	it('enables bots when requested', async () => {
		vi.mocked(api).mockResolvedValue({ status: 200, data: {} });
		const res = await load(formEvent({}, '?bots=1'));
		expect(api).toHaveBeenCalledWith(
			expect.anything(),
			'GET',
			'/api/v1/admin/accounts?search=&page=1&bots=true'
		);
		expect(res).toMatchObject({ bots: true });
	});
});

describe('lock and unlock actions', () => {
	it('post to the right endpoints', async () => {
		vi.mocked(api).mockResolvedValue({ status: 200, data: { ok: true } });
		expect(await actions.lock(formEvent({ username: 'VICTIM' }))).toEqual({ done: true });
		expect(api).toHaveBeenCalledWith(
			expect.anything(),
			'POST',
			'/api/v1/admin/accounts/VICTIM/lock'
		);
		expect(await actions.unlock(formEvent({ username: 'VICTIM' }))).toEqual({ done: true });
		expect(api).toHaveBeenCalledWith(
			expect.anything(),
			'POST',
			'/api/v1/admin/accounts/VICTIM/unlock'
		);
		vi.mocked(api).mockResolvedValue({
			status: 400,
			data: { detail: 'Cannot lock your own account' }
		});
		expect(await actions.lock(formEvent({ username: 'BOSS' }))).toMatchObject({ status: 400 });
	});

	it('falls back to a default message when the backend omits detail', async () => {
		vi.mocked(api).mockResolvedValue({ status: 500, data: {} });
		const res = await actions.lock(formEvent({ username: 'VICTIM' }));
		expect(res).toMatchObject({ status: 500, data: { message: 'lock failed' } });
		const res2 = await actions.unlock(formEvent({ username: 'VICTIM' }));
		expect(res2).toMatchObject({ status: 500, data: { message: 'unlock failed' } });
	});

	it('url-encodes the username', async () => {
		vi.mocked(api).mockResolvedValue({ status: 200, data: { ok: true } });
		await actions.lock(formEvent({ username: 'weird/name?' }));
		expect(api).toHaveBeenCalledWith(
			expect.anything(),
			'POST',
			'/api/v1/admin/accounts/weird%2Fname%3F/lock'
		);
	});
});

describe('resetPassword action', () => {
	it('posts to the reset endpoint and reports the target address', async () => {
		vi.mocked(api).mockResolvedValue({ status: 200, data: { sent_to: 'v@m.example' } });
		const res = await actions.resetPassword(formEvent({ username: 'VICTIM' }));
		expect(res).toEqual({ resetSent: 'v@m.example' });
		expect(api).toHaveBeenCalledWith(
			expect.anything(),
			'POST',
			'/api/v1/admin/accounts/VICTIM/reset-password'
		);
	});

	it('surfaces failures with and without detail', async () => {
		vi.mocked(api).mockResolvedValue({
			status: 409,
			data: { detail: 'Account has no email on file — the reset link cannot be delivered' }
		});
		let res = await actions.resetPassword(formEvent({ username: 'NOEMAIL' }));
		expect(res).toMatchObject({
			status: 409,
			data: { message: 'Account has no email on file — the reset link cannot be delivered' }
		});
		vi.mocked(api).mockResolvedValue({ status: 502, data: {} });
		res = await actions.resetPassword(formEvent({ username: 'VICTIM' }));
		expect(res).toMatchObject({ status: 502, data: { message: 'Password reset failed' } });
	});
});
