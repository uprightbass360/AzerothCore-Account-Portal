import { fail } from '@sveltejs/kit';
import { codeSchema, disable2faSchema, passwordChangeSchema } from '$lib/schemas';
import { api } from '$lib/server/api';
import { parseForm } from '$lib/server/forms';
import type { Actions } from './$types';

type Detail = { detail?: string };

export const actions: Actions = {
	password: async (event) => {
		const parsed = await parseForm(event.request, passwordChangeSchema);
		if (!parsed.ok) return fail(400, { ...parsed, section: 'password' });
		const { status, data } = await api<Detail>(event, 'POST', '/api/v1/user/password', {
			current_password: parsed.data.current_password,
			new_password: parsed.data.new_password
		});
		if (status === 200) return { passwordChanged: true };
		return fail(status, { message: data.detail ?? 'Password change failed', section: 'password' });
	},

	setup2fa: async (event) => {
		const { status, data } = await api<
			{ secret: string; otpauth_uri: string; qr_svg: string } & Detail
		>(event, 'POST', '/api/v1/user/2fa/setup');
		if (status === 200) {
			return { setup: { secret: data.secret, otpauth_uri: data.otpauth_uri, qr_svg: data.qr_svg } };
		}
		return fail(status, { message: data.detail ?? '2FA setup failed', section: 'twofa' });
	},

	confirm2fa: async (event) => {
		const parsed = await parseForm(event.request, codeSchema);
		if (!parsed.ok) return fail(400, { ...parsed, setupPending: true, section: 'twofa' });
		const { status, data } = await api<Detail>(
			event,
			'POST',
			'/api/v1/user/2fa/confirm',
			parsed.data
		);
		if (status === 200) return { enabled: true };
		return fail(status, {
			message: data.detail ?? 'Confirmation failed',
			setupPending: true,
			section: 'twofa'
		});
	},

	disable2fa: async (event) => {
		const parsed = await parseForm(event.request, disable2faSchema);
		if (!parsed.ok) return fail(400, { ...parsed, section: 'twofa' });
		const { status, data } = await api<Detail>(
			event,
			'POST',
			'/api/v1/user/2fa/disable',
			parsed.data
		);
		if (status === 200) return { disabled: true };
		return fail(status, { message: data.detail ?? 'Disable failed', section: 'twofa' });
	}
};
