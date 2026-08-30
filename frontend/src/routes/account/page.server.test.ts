import { beforeEach, describe, expect, it, vi } from 'vitest';

vi.mock('$lib/server/api', async (orig) => {
	const mod = (await orig()) as object;
	return { ...mod, api: vi.fn() };
});
vi.mock('$env/dynamic/private', () => ({ env: {} }));

import { api } from '$lib/server/api';
import { actions } from './+page.server';

function formEvent(fields: Record<string, string>) {
	const fd = new FormData();
	for (const [k, v] of Object.entries(fields)) fd.set(k, v);
	return {
		request: new Request('http://t.est', { method: 'POST', body: fd }),
		cookies: { get: vi.fn(), set: vi.fn(), delete: vi.fn() },
		url: new URL('http://t.est/account'),
		fetch: vi.fn(),
		locals: { user: { username: 'BOB', email: null, totp_enabled: false, is_admin: false } }
	} as never;
}

beforeEach(() => vi.clearAllMocks());

describe('password action', () => {
	const good = { current_password: 'oldpass99', new_password: 'newpass99', confirm: 'newpass99' };

	it('changes password', async () => {
		vi.mocked(api).mockResolvedValue({ status: 200, data: { ok: true } });
		const res = await actions.password(formEvent(good));
		expect(res).toEqual({ passwordChanged: true });
		expect(api).toHaveBeenCalledWith(expect.anything(), 'POST', '/api/v1/user/password', {
			current_password: 'oldpass99',
			new_password: 'newpass99'
		});
	});

	it('rejects mismatched confirm locally', async () => {
		const res = await actions.password(formEvent({ ...good, confirm: 'other9999' }));
		expect(res).toMatchObject({ status: 400, data: { section: 'password' } });
		expect(api).not.toHaveBeenCalled();
	});

	it('surfaces wrong current password', async () => {
		vi.mocked(api).mockResolvedValue({
			status: 403,
			data: { detail: 'Current password is incorrect' }
		});
		const res = await actions.password(formEvent(good));
		expect(res).toMatchObject({
			status: 403,
			data: { message: 'Current password is incorrect', section: 'password' }
		});
	});

	it('falls back to a default message when the backend omits detail', async () => {
		vi.mocked(api).mockResolvedValue({ status: 422, data: {} });
		const res = await actions.password(formEvent(good));
		expect(res).toMatchObject({
			status: 422,
			data: { message: 'Password change failed', section: 'password' }
		});
	});
});

describe('2fa actions', () => {
	it('disable2fa rejects an invalid code locally', async () => {
		const res = await actions.disable2fa(formEvent({ password: 'pw', code: 'abc' }));
		expect(res).toMatchObject({ status: 400, data: { section: 'twofa' } });
		expect(api).not.toHaveBeenCalled();
	});

	it('setup2fa returns secret payload', async () => {
		const payload = { secret: 'ABCDEFGHIJKLMNOP', otpauth_uri: 'otpauth://x', qr_svg: '<svg/>' };
		vi.mocked(api).mockResolvedValue({ status: 200, data: payload });
		const res = await actions.setup2fa(formEvent({}));
		expect(res).toEqual({ setup: payload });
	});

	it('setup2fa surfaces 409', async () => {
		vi.mocked(api).mockResolvedValue({ status: 409, data: { detail: '2FA already enabled' } });
		const res = await actions.setup2fa(formEvent({}));
		expect(res).toMatchObject({
			status: 409,
			data: { message: '2FA already enabled', section: 'twofa' }
		});
	});

	it('setup2fa falls back to a default message when the backend omits detail', async () => {
		vi.mocked(api).mockResolvedValue({ status: 500, data: {} });
		const res = await actions.setup2fa(formEvent({}));
		expect(res).toMatchObject({
			status: 500,
			data: { message: '2FA setup failed', section: 'twofa' }
		});
	});

	it('confirm2fa validates code then confirms', async () => {
		let res = await actions.confirm2fa(formEvent({ code: 'abc' }));
		expect(res).toMatchObject({ status: 400, data: { setupPending: true, section: 'twofa' } });
		vi.mocked(api).mockResolvedValue({ status: 200, data: { ok: true } });
		res = await actions.confirm2fa(formEvent({ code: '123456' }));
		expect(res).toEqual({ enabled: true });
		vi.mocked(api).mockResolvedValue({ status: 400, data: { detail: 'Invalid code' } });
		res = await actions.confirm2fa(formEvent({ code: '123456' }));
		expect(res).toMatchObject({
			status: 400,
			data: { message: 'Invalid code', setupPending: true, section: 'twofa' }
		});
	});

	it('confirm2fa falls back to a default message when the backend omits detail', async () => {
		vi.mocked(api).mockResolvedValue({ status: 400, data: {} });
		const res = await actions.confirm2fa(formEvent({ code: '123456' }));
		expect(res).toMatchObject({
			status: 400,
			data: { message: 'Confirmation failed', setupPending: true, section: 'twofa' }
		});
	});

	it('disable2fa flows', async () => {
		vi.mocked(api).mockResolvedValue({ status: 200, data: { ok: true } });
		let res = await actions.disable2fa(formEvent({ password: 'pw', code: '123456' }));
		expect(res).toEqual({ disabled: true });
		vi.mocked(api).mockResolvedValue({ status: 403, data: { detail: 'Password is incorrect' } });
		res = await actions.disable2fa(formEvent({ password: 'pw', code: '123456' }));
		expect(res).toMatchObject({
			status: 403,
			data: { message: 'Password is incorrect', section: 'twofa' }
		});
	});

	it('disable2fa falls back to a default message when the backend omits detail', async () => {
		vi.mocked(api).mockResolvedValue({ status: 400, data: {} });
		const res = await actions.disable2fa(formEvent({ password: 'pw', code: '123456' }));
		expect(res).toMatchObject({
			status: 400,
			data: { message: 'Disable failed', section: 'twofa' }
		});
	});
});

describe('email action', () => {
	const good = { new_email: 'new@addr.example' };

	it('requests the change and reports the target address', async () => {
		vi.mocked(api).mockResolvedValue({ status: 200, data: { sent_to: 'new@addr.example' } });
		const res = await actions.email(formEvent(good));
		expect(res).toEqual({ emailRequested: 'new@addr.example' });
		expect(api).toHaveBeenCalledWith(expect.anything(), 'POST', '/api/v1/user/email', {
			new_email: 'new@addr.example'
		});
	});

	it('includes a trimmed 2FA code only when provided', async () => {
		vi.mocked(api).mockResolvedValue({ status: 200, data: { sent_to: 'new@addr.example' } });
		await actions.email(formEvent({ ...good, code: ' 123456 ' }));
		expect(api).toHaveBeenCalledWith(expect.anything(), 'POST', '/api/v1/user/email', {
			new_email: 'new@addr.example',
			code: '123456'
		});
		await actions.email(formEvent({ ...good, code: '  ' }));
		const lastPayload = vi.mocked(api).mock.calls.at(-1)?.[3];
		expect(lastPayload).toEqual({ new_email: 'new@addr.example' });
	});

	it('rejects an invalid email locally with the email section tag', async () => {
		const res = await actions.email(formEvent({ ...good, new_email: 'nope' }));
		expect(res).toMatchObject({ status: 400, data: { section: 'email' } });
		expect(api).not.toHaveBeenCalled();
	});

	it('surfaces backend failures with the email section tag', async () => {
		vi.mocked(api).mockResolvedValue({ status: 502, data: {} });
		const res = await actions.email(formEvent(good));
		expect(res).toMatchObject({
			status: 502,
			data: { message: 'Email change failed', section: 'email' }
		});
	});
});
