import { fail } from '@sveltejs/kit';
import { grantAdminSchema } from '$lib/schemas';
import { api } from '$lib/server/api';
import { parseForm } from '$lib/server/forms';
import type { Actions, PageServerLoad } from './$types';

type Detail = { detail?: string; username?: string };
type Admin = {
	account_id: number;
	username: string;
	granted_by: number | null;
	granted_at: string;
};

export const load: PageServerLoad = async (event) => {
	const { data } = await api<{ items: Admin[] }>(event, 'GET', '/api/v1/admin/admins');
	return { admins: data.items ?? [] };
};

export const actions: Actions = {
	grant: async (event) => {
		const parsed = await parseForm(event.request, grantAdminSchema);
		if (!parsed.ok) return fail(400, parsed);
		const { status, data } = await api<Detail>(event, 'POST', '/api/v1/admin/admins', parsed.data);
		if (status === 201) return { granted: data.username };
		return fail(status, { message: data.detail ?? 'Grant failed', values: parsed.data });
	},
	revoke: async (event) => {
		const fd = await event.request.formData();
		const { status, data } = await api<Detail>(
			event,
			'DELETE',
			`/api/v1/admin/admins/${fd.get('account_id')}`
		);
		if (status === 200) return { revoked: true };
		return fail(status, { message: data.detail ?? 'Revoke failed' });
	}
};
