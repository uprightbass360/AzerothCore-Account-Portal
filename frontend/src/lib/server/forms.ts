import { z, type ZodType } from 'zod';

export type FormFailure = {
	ok: false;
	errors: Record<string, string[]>;
	values: Record<string, string>;
};
export type FormResult<T> = { ok: true; data: T } | FormFailure;

const SECRET_FIELD = /password|confirm|code/i;

export async function parseForm<T>(request: Request, schema: ZodType<T>): Promise<FormResult<T>> {
	const fd = await request.formData();
	const raw: Record<string, string> = {};
	for (const [k, v] of fd.entries()) if (typeof v === 'string') raw[k] = v;
	const parsed = schema.safeParse(raw);
	if (parsed.success) return { ok: true, data: parsed.data };
	const { fieldErrors } = z.flattenError(parsed.error);
	const values: Record<string, string> = {};
	for (const [k, v] of Object.entries(raw)) if (!SECRET_FIELD.test(k)) values[k] = v;
	return { ok: false, errors: fieldErrors as Record<string, string[]>, values };
}
