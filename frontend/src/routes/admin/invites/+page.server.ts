import { fail } from '@sveltejs/kit';
import { inviteSchema } from '$lib/schemas';
import { api } from '$lib/server/api';
import { parseForm } from '$lib/server/forms';
import type { Actions, PageServerLoad } from './$types';

type Detail = { detail?: string };
type Invite = { id: number; email: string; created_at: string; expires_at: string };

export const load: PageServerLoad = async (event) => {
	const { data } = await api<{ items: Invite[] }>(event, 'GET', '/api/v1/admin/invites');
	return { invites: data.items ?? [] };
};

export const actions: Actions = {
	send: async (event) => {
		const parsed = await parseForm(event.request, inviteSchema);
		if (!parsed.ok) return fail(400, parsed);
		const { status, data } = await api<Detail>(event, 'POST', '/api/v1/admin/invites', parsed.data);
		if (status === 201) return { sent: parsed.data.email };
		return fail(status, { message: data.detail ?? 'Invite failed', values: parsed.data });
	},
	revoke: async (event) => {
		const fd = await event.request.formData();
		const { status, data } = await api<Detail>(
			event,
			'DELETE',
			`/api/v1/admin/invites/${encodeURIComponent(String(fd.get('id')))}`
		);
		if (status === 200) return { revoked: true };
		return fail(status, { message: data.detail ?? 'Revoke failed' });
	}
};
