import { z } from 'zod';

const USERNAME = z.string().regex(/^[A-Za-z0-9]{3,20}$/, '3–20 letters or numbers');
const GAME_PASSWORD = z.string().regex(/^[\x21-\x7e]{8,16}$/, '8–16 characters, no spaces');
const TOTP_CODE = z.string().regex(/^\d{6}$/, 'Enter the 6-digit code');

export const loginSchema = z.object({
	username: z.string().min(1, 'Username is required'),
	password: z.string().min(1, 'Password is required')
});

export const totpSchema = loginSchema.extend({ code: TOTP_CODE });

export const registerSchema = z
	.object({ username: USERNAME, password: GAME_PASSWORD, confirm: z.string() })
	.refine((d) => d.password === d.confirm, {
		message: 'Passwords do not match',
		path: ['confirm']
	});

export const passwordChangeSchema = z
	.object({
		current_password: z.string().min(1, 'Current password is required'),
		new_password: GAME_PASSWORD,
		confirm: z.string()
	})
	.refine((d) => d.new_password === d.confirm, {
		message: 'Passwords do not match',
		path: ['confirm']
	});

export const inviteSchema = z.object({ email: z.email('Enter a valid email address') });

export const grantAdminSchema = z.object({ username: USERNAME });

export const codeSchema = z.object({ code: TOTP_CODE });

export const emailChangeSchema = z.object({
	new_email: z.email('Enter a valid email address'),
	password: z.string().min(1, 'Password is required'),
	code: z.string().optional()
});

export const disable2faSchema = z.object({
	password: z.string().min(1, 'Password is required'),
	code: TOTP_CODE
});
