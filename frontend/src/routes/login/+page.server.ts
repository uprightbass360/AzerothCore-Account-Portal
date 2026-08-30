import { fail, redirect } from '@sveltejs/kit';
import { env } from '$env/dynamic/private';
import { loginSchema, totpSchema } from '$lib/schemas';
import { api, setSessionCookie } from '$lib/server/api';
import { parseForm } from '$lib/server/forms';
import type { Actions, PageServerLoad } from './$types';

type LoginResponse = { token?: string; expires_at?: string; status?: string; detail?: string };

export const load: PageServerLoad = ({ locals }) => {
	if (locals.user) redirect(303, '/account');
	return { origin: env.ORIGIN ?? '' };
};

export const actions: Actions = {
	login: async (event) => {
		const parsed = await parseForm(event.request, loginSchema);
		if (!parsed.ok) return fail(400, parsed);
		const { status, data } = await api<LoginResponse>(
			event,
			'POST',
			'/api/v1/auth/login',
			parsed.data
		);
		if (status === 200 && data.token) {
			setSessionCookie(event, data.token, data.expires_at!);
			redirect(303, '/account');
		}
		if (status === 200 && data.status === '2fa_required') {
			// password round-trips through the server-rendered 2FA form only, never to the browser log
			return { twofa: true, username: parsed.data.username, password: parsed.data.password };
		}
		return fail(status, {
			message: data.detail ?? 'Login failed',
			values: { username: parsed.data.username }
		});
	},

	twofa: async (event) => {
		const parsed = await parseForm(event.request, totpSchema);
		if (!parsed.ok) return fail(400, { ...parsed, twofa: true });
		const { status, data } = await api<LoginResponse>(
			event,
			'POST',
			'/api/v1/auth/login/2fa',
			parsed.data
		);
		if (status === 200 && data.token) {
			setSessionCookie(event, data.token, data.expires_at!);
			redirect(303, '/account');
		}
		return fail(status, {
			twofa: true,
			username: parsed.data.username,
			password: parsed.data.password,
			message: data.detail ?? 'Login failed'
		});
	}
};
