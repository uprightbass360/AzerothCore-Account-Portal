import { fail } from '@sveltejs/kit';
import { resetPasswordSchema } from '$lib/schemas';
import { api } from '$lib/server/api';
import { parseForm } from '$lib/server/forms';
import type { Actions, PageServerLoad } from './$types';

type Detail = { detail?: string };

export const load: PageServerLoad = async (event) => {
	const { status, data } = await api<{ username?: string; totp_required?: boolean } & Detail>(
		event,
		'GET',
		`/api/v1/password-reset/${encodeURIComponent(event.params.token)}`
	);
	if (status !== 200) return { invalid: data.detail ?? 'This reset link is not valid' };
	return { username: data.username, totpRequired: data.totp_required ?? false };
};

export const actions: Actions = {
	default: async (event) => {
		const parsed = await parseForm(event.request, resetPasswordSchema);
		if (!parsed.ok) return fail(400, parsed);
		const payload: Record<string, string> = { new_password: parsed.data.new_password };
		if (parsed.data.code?.trim()) payload.code = parsed.data.code.trim();
		const { status, data } = await api<{ username?: string } & Detail>(
			event,
			'POST',
			`/api/v1/password-reset/${encodeURIComponent(event.params.token)}`,
			payload
		);
		if (status === 200) return { success: true, username: data.username };
		return fail(status, { message: data.detail ?? 'Password reset failed' });
	}
};
