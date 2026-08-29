import { describe, expect, it } from 'vitest';
import { loginSchema, registerSchema } from '$lib/schemas';
import { parseForm } from './forms';

function req(fields: Record<string, string>): Request {
	const fd = new FormData();
	for (const [k, v] of Object.entries(fields)) fd.set(k, v);
	return new Request('http://t.est', { method: 'POST', body: fd });
}

describe('parseForm', () => {
	it('returns data on valid input', async () => {
		const r = await parseForm(req({ username: 'a', password: 'b' }), loginSchema);
		expect(r).toEqual({ ok: true, data: { username: 'a', password: 'b' } });
	});

	it('returns field errors and redacts secrets', async () => {
		const r = await parseForm(
			req({ username: 'x!', password: 'secret99', confirm: 'other' }),
			registerSchema
		);
		expect(r.ok).toBe(false);
		if (!r.ok) {
			expect(r.errors.username?.[0]).toBeTruthy();
			expect(r.values.username).toBe('x!');
			expect(r.values.password).toBeUndefined();
			expect(r.values.confirm).toBeUndefined();
		}
	});

	it('ignores non-string entries', async () => {
		const fd = new FormData();
		fd.set('username', 'a');
		fd.set('password', 'b');
		fd.set('file', new Blob(['x']));
		const r = await parseForm(
			new Request('http://t.est', { method: 'POST', body: fd }),
			loginSchema
		);
		expect(r.ok).toBe(true);
	});
});
