import { describe, expect, it } from 'vitest';
import {
	disable2faSchema,
	grantAdminSchema,
	inviteSchema,
	loginSchema,
	passwordChangeSchema,
	registerSchema,
	totpSchema
} from './schemas';

describe('schemas', () => {
	it('loginSchema requires both fields', () => {
		expect(loginSchema.safeParse({ username: 'a', password: 'b' }).success).toBe(true);
		expect(loginSchema.safeParse({ username: '', password: 'b' }).success).toBe(false);
	});

	it('totpSchema requires 6 digits', () => {
		expect(totpSchema.safeParse({ username: 'a', password: 'b', code: '123456' }).success).toBe(
			true
		);
		expect(totpSchema.safeParse({ username: 'a', password: 'b', code: '12345' }).success).toBe(
			false
		);
	});

	it('registerSchema enforces AC constraints and confirm match', () => {
		const good = { username: 'Newbie1', password: 'hunter2!!', confirm: 'hunter2!!' };
		expect(registerSchema.safeParse(good).success).toBe(true);
		expect(registerSchema.safeParse({ ...good, username: 'x!' }).success).toBe(false);
		expect(registerSchema.safeParse({ ...good, password: 'short', confirm: 'short' }).success).toBe(
			false
		);
		expect(
			registerSchema.safeParse({ ...good, password: 'x'.repeat(17), confirm: 'x'.repeat(17) })
				.success
		).toBe(false);
		const mismatch = registerSchema.safeParse({ ...good, confirm: 'different1' });
		expect(mismatch.success).toBe(false);
	});

	it('passwordChangeSchema mirrors register rules', () => {
		const good = { current_password: 'old', new_password: 'hunter2!!', confirm: 'hunter2!!' };
		expect(passwordChangeSchema.safeParse(good).success).toBe(true);
		expect(passwordChangeSchema.safeParse({ ...good, confirm: 'nope-nope' }).success).toBe(false);
	});

	it('inviteSchema validates email', () => {
		expect(inviteSchema.safeParse({ email: 'a@b.co' }).success).toBe(true);
		expect(inviteSchema.safeParse({ email: 'nope' }).success).toBe(false);
	});

	it('grantAdminSchema and disable2faSchema', () => {
		expect(grantAdminSchema.safeParse({ username: 'Boss1' }).success).toBe(true);
		expect(grantAdminSchema.safeParse({ username: '!' }).success).toBe(false);
		expect(disable2faSchema.safeParse({ password: 'x', code: '123456' }).success).toBe(true);
		expect(disable2faSchema.safeParse({ password: '', code: '123456' }).success).toBe(false);
	});
});
