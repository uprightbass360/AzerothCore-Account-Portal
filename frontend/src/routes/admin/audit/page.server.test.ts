import { beforeEach, describe, expect, it, vi } from 'vitest';

vi.mock('$lib/server/api', async (orig) => {
	const mod = (await orig()) as object;
	return { ...mod, api: vi.fn() };
});
vi.mock('$env/dynamic/private', () => ({ env: {} }));

import { api } from '$lib/server/api';
import { load } from './+page.server';

function formEvent(fields: Record<string, string>, search = '') {
	const fd = new FormData();
	for (const [k, v] of Object.entries(fields)) fd.set(k, v);
	return {
		request: new Request('http://t.est', { method: 'POST', body: fd }),
		cookies: { get: vi.fn(), set: vi.fn(), delete: vi.fn() },
		url: new URL(`http://t.est/admin/audit${search}`),
		fetch: vi.fn(),
		locals: { user: { username: 'BOSS', email: null, totp_enabled: false, is_admin: true } }
	} as never;
}

beforeEach(() => vi.clearAllMocks());

describe('load', () => {
	it('forwards filter and page', async () => {
		vi.mocked(api).mockResolvedValue({
			status: 200,
			data: { items: [{ action: 'login.success' }], total: 1, page: 1, pages: 1 }
		});
		const res = await load(formEvent({}, '?action=login.success&page=1'));
		expect(api).toHaveBeenCalledWith(
			expect.anything(),
			'GET',
			'/api/v1/admin/audit?action=login.success&page=1'
		);
		expect(res).toEqual({
			entries: [{ action: 'login.success' }],
			total: 1,
			page: 1,
			pages: 1,
			action: 'login.success'
		});
	});

	it('defaults filter, page and result fields when absent', async () => {
		vi.mocked(api).mockResolvedValue({ status: 200, data: {} });
		const res = await load(formEvent({}));
		expect(api).toHaveBeenCalledWith(
			expect.anything(),
			'GET',
			'/api/v1/admin/audit?action=&page=1'
		);
		expect(res).toEqual({ entries: [], total: 0, page: 1, pages: 1, action: '' });
	});
});
