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
		url: new URL(`http://t.est/admin/admins${search}`),
		fetch: vi.fn(),
		locals: { user: { username: 'BOSS', email: null, totp_enabled: false, is_admin: true } }
	} as never;
}

beforeEach(() => vi.clearAllMocks());

describe('load', () => {
	it('lists admins', async () => {
		vi.mocked(api).mockResolvedValue({ status: 200, data: { items: [{ account_id: 1 }] } });
		expect(await load(formEvent({}))).toEqual({ admins: [{ account_id: 1 }] });
	});

	it('falls back to an empty list when items is missing', async () => {
		vi.mocked(api).mockResolvedValue({ status: 200, data: {} });
		expect(await load(formEvent({}))).toEqual({ admins: [] });
	});
});

describe('grant and revoke actions', () => {
	it('grant validates then posts; revoke deletes; last-admin error surfaces', async () => {
		const res = await actions.grant(formEvent({ username: '!' }));
		expect(res).toMatchObject({ status: 400 });
		vi.mocked(api).mockResolvedValue({ status: 201, data: { username: 'NEW' } });
		expect(await actions.grant(formEvent({ username: 'NewMin' }))).toEqual({ granted: 'NEW' });
		vi.mocked(api).mockResolvedValue({ status: 200, data: { ok: true } });
		expect(await actions.revoke(formEvent({ account_id: '5' }))).toEqual({ revoked: true });
		expect(api).toHaveBeenCalledWith(expect.anything(), 'DELETE', '/api/v1/admin/admins/5');
		vi.mocked(api).mockResolvedValue({
			status: 400,
			data: { detail: 'Cannot remove the last admin' }
		});
		expect(await actions.revoke(formEvent({ account_id: '1' }))).toMatchObject({
			status: 400,
			data: { message: 'Cannot remove the last admin' }
		});
	});

	it('falls back to a default message when the backend omits detail', async () => {
		vi.mocked(api).mockResolvedValue({ status: 500, data: {} });
		const grantRes = await actions.grant(formEvent({ username: 'NewMin' }));
		expect(grantRes).toMatchObject({ status: 500, data: { message: 'Grant failed' } });
		const revokeRes = await actions.revoke(formEvent({ account_id: '5' }));
		expect(revokeRes).toMatchObject({ status: 500, data: { message: 'Revoke failed' } });
	});
});
