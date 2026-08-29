import { describe, expect, it } from 'vitest';
import { load } from './+layout.server';

describe('layout load', () => {
	it('exposes locals.user to the page', () => {
		const user = { username: 'BOB', email: null, totp_enabled: false, is_admin: false };
		expect(load({ locals: { user } } as never)).toEqual({ user });
	});

	it('exposes null when anonymous', () => {
		expect(load({ locals: { user: null } } as never)).toEqual({ user: null });
	});
});
