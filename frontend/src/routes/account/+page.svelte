<script lang="ts">
	import { enhance } from '$app/forms';
	import FieldErrors from '$lib/components/FieldErrors.svelte';
	let { data, form } = $props();
	const user = $derived(data.user!);
	const totpOn = $derived((user.totp_enabled || form?.enabled) && !form?.disabled);
</script>

<h1 class="mb-6 text-xl font-semibold">Your account</h1>

<div class="grid gap-6 md:grid-cols-2">
	<section class="rounded border border-stone-300 bg-white p-5 shadow-sm">
		<h2 class="mb-3 font-medium">Profile</h2>
		<dl class="text-sm">
			<dt class="text-stone-500">Username</dt>
			<dd class="mb-2">{user.username}</dd>
			<dt class="text-stone-500">Email</dt>
			<dd>{user.email ?? '—'}</dd>
		</dl>
	</section>

	<section class="rounded border border-stone-300 bg-white p-5 shadow-sm">
		<h2 class="mb-3 font-medium">Change password</h2>
		{#if form?.passwordChanged}
			<p class="mb-2 text-sm text-green-700">Password changed. Other sessions were signed out.</p>
		{/if}
		<form method="POST" action="?/password" use:enhance>
			<label class="mb-1 block text-sm" for="current_password">Current password</label>
			<input
				id="current_password"
				name="current_password"
				type="password"
				class="w-full rounded border border-stone-300 px-3 py-2"
			/>
			<FieldErrors errors={form?.errors?.current_password} />
			<label class="mt-3 mb-1 block text-sm" for="new_password">New password</label>
			<input
				id="new_password"
				name="new_password"
				type="password"
				class="w-full rounded border border-stone-300 px-3 py-2"
			/>
			<FieldErrors errors={form?.errors?.new_password} />
			<label class="mt-3 mb-1 block text-sm" for="confirm">Confirm new password</label>
			<input
				id="confirm"
				name="confirm"
				type="password"
				class="w-full rounded border border-stone-300 px-3 py-2"
			/>
			<FieldErrors errors={form?.errors?.confirm} />
			{#if form?.message && form?.section === 'password'}
				<p class="mt-2 text-sm text-red-600">{form.message}</p>
			{/if}
			<button class="mt-4 rounded bg-stone-900 px-4 py-2 text-sm text-stone-100"
				>Change password</button
			>
		</form>
	</section>

	<section class="rounded border border-stone-300 bg-white p-5 shadow-sm md:col-span-2">
		<h2 class="mb-3 font-medium">Two-factor authentication</h2>
		{#if form?.setup || form?.setupPending}
			{#if form?.setup}
				<div class="mb-3 flex items-start gap-4">
					<!-- eslint-disable-next-line svelte/no-at-html-tags -- server-generated SVG (segno) from our own backend, not user input -->
					<div class="shrink-0">{@html form.setup.qr_svg}</div>
					<div class="text-sm">
						<p class="mb-2">Scan with your authenticator app, or enter the code manually:</p>
						<code class="rounded bg-stone-100 px-2 py-1">{form.setup.secret}</code>
					</div>
				</div>
			{/if}
			<form method="POST" action="?/confirm2fa" use:enhance>
				<label class="mb-1 block text-sm" for="code">Enter the 6-digit code to confirm</label>
				<input
					id="code"
					name="code"
					inputmode="numeric"
					autocomplete="one-time-code"
					class="w-40 rounded border border-stone-300 px-3 py-2"
				/>
				<FieldErrors errors={form?.errors?.code} />
				{#if form?.message && form?.setupPending && form?.section === 'twofa'}
					<p class="mt-2 text-sm text-red-600">{form.message}</p>
				{/if}
				<button class="mt-3 rounded bg-stone-900 px-4 py-2 text-sm text-stone-100"
					>Enable 2FA</button
				>
			</form>
		{:else if totpOn}
			<p class="mb-3 text-sm text-green-700">2FA is enabled on your account.</p>
			<form method="POST" action="?/disable2fa" use:enhance class="flex flex-wrap items-end gap-3">
				<div>
					<label class="mb-1 block text-sm" for="d_password">Password</label>
					<input
						id="d_password"
						name="password"
						type="password"
						class="rounded border border-stone-300 px-3 py-2"
					/>
				</div>
				<div>
					<label class="mb-1 block text-sm" for="d_code">Current code</label>
					<input
						id="d_code"
						name="code"
						inputmode="numeric"
						class="w-32 rounded border border-stone-300 px-3 py-2"
					/>
				</div>
				<button class="rounded border border-red-700 px-4 py-2 text-sm text-red-700"
					>Disable 2FA</button
				>
			</form>
			{#if form?.message && form?.section === 'twofa'}<p class="mt-2 text-sm text-red-600">
					{form.message}
				</p>{/if}
		{:else}
			{#if form?.disabled}<p class="mb-2 text-sm text-stone-600">2FA has been disabled.</p>{/if}
			<p class="mb-3 text-sm text-stone-600">Protect your account with an authenticator app.</p>
			<form method="POST" action="?/setup2fa" use:enhance>
				<button class="rounded bg-stone-900 px-4 py-2 text-sm text-stone-100">Set up 2FA</button>
			</form>
			{#if form?.message && form?.section === 'twofa'}<p class="mt-2 text-sm text-red-600">
					{form.message}
				</p>{/if}
		{/if}
	</section>
</div>
