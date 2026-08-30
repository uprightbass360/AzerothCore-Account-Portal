import { beforeEach, describe, expect, it, vi } from 'vitest';

vi.mock('$lib/server/api', async (orig) => {
	const mod = (await orig()) as object;
	return { ...mod, api: vi.fn() };
});
vi.mock('$env/dynamic/private', () => ({ env: {} }));

import { api } from '$lib/server/api';
import { actions, load } from './+page.server';

function makeEvent(fields: Record<string, string> = {}) {
	const fd = new FormData();
	for (const [k, v] of Object.entries(fields)) fd.set(k, v);
	return {
		request: new Request('http://t.est', { method: 'POST', body: fd }),
		params: { token: 'tok/1' },
		cookies: { get: vi.fn(), set: vi.fn(), delete: vi.fn() },
		url: new URL('http://t.est/reset-password/tok1'),
		fetch: vi.fn(),
		locals: { user: null }
	} as never;
}

beforeEach(() => vi.clearAllMocks());

describe('load', () => {
	it('returns username and totp flag, url-encoding the token', async () => {
		vi.mocked(api).mockResolvedValue({
			status: 200,
			data: { username: 'VICTIM', totp_required: true }
		});
		expect(await load(makeEvent())).toEqual({ username: 'VICTIM', totpRequired: true });
		expect(api).toHaveBeenCalledWith(expect.anything(), 'GET', '/api/v1/password-reset/tok%2F1');
	});

	it('defaults totp flag and maps failures with and without detail', async () => {
		vi.mocked(api).mockResolvedValue({ status: 200, data: { username: 'V' } });
		expect(await load(makeEvent())).toEqual({ username: 'V', totpRequired: false });
		vi.mocked(api).mockResolvedValue({ status: 410, data: { detail: 'expired' } });
		expect(await load(makeEvent())).toEqual({ invalid: 'expired' });
		vi.mocked(api).mockResolvedValue({ status: 404, data: {} });
		expect(await load(makeEvent())).toEqual({ invalid: 'This reset link is not valid' });
	});
});

describe('reset action', () => {
	const good = { new_password: 'brandNew99', confirm: 'brandNew99' };

	it('sets the password and reports success', async () => {
		vi.mocked(api).mockResolvedValue({ status: 200, data: { username: 'VICTIM' } });
		expect(await actions.default(makeEvent(good))).toEqual({ success: true, username: 'VICTIM' });
		expect(api).toHaveBeenCalledWith(expect.anything(), 'POST', '/api/v1/password-reset/tok%2F1', {
			new_password: 'brandNew99'
		});
	});

	it('includes a trimmed code only when provided', async () => {
		vi.mocked(api).mockResolvedValue({ status: 200, data: { username: 'V' } });
		await actions.default(makeEvent({ ...good, code: ' 123456 ' }));
		expect(vi.mocked(api).mock.calls.at(-1)?.[3]).toEqual({
			new_password: 'brandNew99',
			code: '123456'
		});
		await actions.default(makeEvent({ ...good, code: '  ' }));
		expect(vi.mocked(api).mock.calls.at(-1)?.[3]).toEqual({ new_password: 'brandNew99' });
	});

	it('rejects mismatched or invalid passwords locally', async () => {
		let res = await actions.default(makeEvent({ ...good, confirm: 'other9999' }));
		expect(res).toMatchObject({ status: 400 });
		res = await actions.default(makeEvent({ new_password: 'short', confirm: 'short' }));
		expect(res).toMatchObject({ status: 400 });
		expect(api).not.toHaveBeenCalled();
	});

	it('surfaces backend failures with and without detail', async () => {
		vi.mocked(api).mockResolvedValue({ status: 400, data: { detail: 'Invalid code' } });
		expect(await actions.default(makeEvent(good))).toMatchObject({
			status: 400,
			data: { message: 'Invalid code' }
		});
		vi.mocked(api).mockResolvedValue({ status: 503, data: {} });
		expect(await actions.default(makeEvent(good))).toMatchObject({
			data: { message: 'Password reset failed' }
		});
	});
});
