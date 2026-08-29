import { fail } from '@sveltejs/kit';
import { registerSchema } from '$lib/schemas';
import { api } from '$lib/server/api';
import { parseForm } from '$lib/server/forms';
import type { Actions, PageServerLoad } from './$types';

export const load: PageServerLoad = async (event) => {
	const { status, data } = await api<{ email?: string; detail?: string }>(
		event,
		'GET',
		`/api/v1/register/${encodeURIComponent(event.params.token)}`
	);
	if (status !== 200) return { invalid: data.detail ?? 'This invite link is not valid' };
	return { email: data.email };
};

export const actions: Actions = {
	default: async (event) => {
		const parsed = await parseForm(event.request, registerSchema);
		if (!parsed.ok) return fail(400, parsed);
		const { status, data } = await api<{ username?: string; detail?: string }>(
			event,
			'POST',
			`/api/v1/register/${encodeURIComponent(event.params.token)}`,
			{ username: parsed.data.username, password: parsed.data.password }
		);
		if (status === 201) return { success: true, username: data.username };
		return fail(status, {
			message: data.detail ?? 'Registration failed',
			values: { username: parsed.data.username }
		});
	}
};
