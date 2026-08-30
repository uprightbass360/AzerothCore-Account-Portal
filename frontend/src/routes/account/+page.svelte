<script lang="ts">
	import { enhance } from '$app/forms';
	import FieldErrors from '$lib/components/FieldErrors.svelte';
	let { data, form } = $props();
	const user = $derived(data.user!);
	const totpOn = $derived((user.totp_enabled || form?.enabled) && !form?.disabled);
</script>

<svelte:head><title>Your account · Account Portal</title></svelte:head>

<h1 class="wow-heading mb-8 text-2xl">Your account</h1>

<div class="grid gap-6 md:grid-cols-2">
	<section class="wow-card p-6">
		<h2 class="wow-heading mb-4 text-lg">Profile</h2>
		<dl class="text-sm">
			<dt class="text-q-poor">Username</dt>
			<dd class="mb-2">{user.username}</dd>
			<dt class="text-q-poor">Email</dt>
			<dd>{user.email ?? '—'}</dd>
		</dl>

		<h2 class="wow-heading mt-6 mb-4 text-lg">Change email</h2>
		{#if form?.emailRequested}
			<p class="mb-2 text-sm text-q-uncommon">
				Confirmation sent to {form.emailRequested}. The change applies once the link in that email
				is clicked.
			</p>
		{/if}
		<form method="POST" action="?/email" use:enhance>
			<label class="mb-1 block text-sm" for="new_email">New email address</label>
			<input
				id="new_email"
				name="new_email"
				value={form?.values?.new_email ?? ''}
				class="wow-input w-full px-3 py-2"
			/>
			<FieldErrors errors={form?.errors?.new_email} />
			{#if user.totp_enabled}
				<label class="mt-3 mb-1 block text-sm" for="email_code">Current 2FA code</label>
				<input id="email_code" name="code" inputmode="numeric" class="wow-input w-32 px-3 py-2" />
			{/if}
			{#if form?.message && form?.section === 'email'}
				<p class="mt-2 text-sm text-red-400">{form.message}</p>
			{/if}
			<button class="btn-wow mt-4 px-4 py-2 text-sm">Send confirmation</button>
		</form>
	</section>

	<section class="wow-card p-6">
		<h2 class="wow-heading mb-4 text-lg">Change password</h2>
		{#if form?.passwordChanged}
			<p class="mb-2 text-sm text-q-uncommon">Password changed. Other sessions were signed out.</p>
		{/if}
		<form method="POST" action="?/password" use:enhance>
			<label class="mb-1 block text-sm" for="current_password">Current password</label>
			<input
				id="current_password"
				name="current_password"
				type="password"
				class="wow-input w-full px-3 py-2"
			/>
			<FieldErrors errors={form?.errors?.current_password} />
			<label class="mt-3 mb-1 block text-sm" for="new_password">New password</label>
			<input
				id="new_password"
				name="new_password"
				type="password"
				class="wow-input w-full px-3 py-2"
			/>
			<FieldErrors errors={form?.errors?.new_password} />
			<label class="mt-3 mb-1 block text-sm" for="confirm">Confirm new password</label>
			<input id="confirm" name="confirm" type="password" class="wow-input w-full px-3 py-2" />
			<FieldErrors errors={form?.errors?.confirm} />
			{#if form?.message && form?.section === 'password'}
				<p class="mt-2 text-sm text-red-400">{form.message}</p>
			{/if}
			<button class="btn-wow mt-5 px-4 py-2 text-sm">Change password</button>
		</form>
	</section>

	<section class="wow-card p-6 md:col-span-2">
		<h2 class="wow-heading mb-4 text-lg">Two-factor authentication</h2>
		{#if form?.setup || form?.setupPending}
			{#if form?.setup}
				<div class="mb-3 flex items-start gap-4">
					<!-- eslint-disable-next-line svelte/no-at-html-tags -- server-generated SVG (segno) from our own backend, not user input -->
					<div class="shrink-0 bg-white p-2">{@html form.setup.qr_svg}</div>
					<div class="text-sm">
						<p class="mb-2">Scan with your authenticator app, or enter the code manually:</p>
						<code class="bg-black/50 px-2 py-1 font-mono text-questgold">{form.setup.secret}</code>
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
					class="wow-input w-40 px-3 py-2"
				/>
				<FieldErrors errors={form?.errors?.code} />
				{#if form?.message && form?.setupPending && form?.section === 'twofa'}
					<p class="mt-2 text-sm text-red-400">{form.message}</p>
				{/if}
				<button class="btn-wow mt-3 px-4 py-2 text-sm">Enable 2FA</button>
			</form>
		{:else if totpOn}
			<p class="mb-3 text-sm text-q-uncommon">2FA is enabled on your account.</p>
			<form method="POST" action="?/disable2fa" use:enhance class="flex flex-wrap items-end gap-3">
				<div>
					<label class="mb-1 block text-sm" for="d_password">Password</label>
					<input id="d_password" name="password" type="password" class="wow-input px-3 py-2" />
				</div>
				<div>
					<label class="mb-1 block text-sm" for="d_code">Current code</label>
					<input id="d_code" name="code" inputmode="numeric" class="wow-input w-32 px-3 py-2" />
				</div>
				<button class="btn-wow-danger px-4 py-2 text-sm">Disable 2FA</button>
			</form>
			{#if form?.message && form?.section === 'twofa'}<p class="mt-2 text-sm text-red-400">
					{form.message}
				</p>{/if}
		{:else}
			{#if form?.disabled}<p class="mb-2 text-sm text-parchment/70">2FA has been disabled.</p>{/if}
			<p class="mb-3 text-sm text-parchment/70">Protect your account with an authenticator app.</p>
			<form method="POST" action="?/setup2fa" use:enhance>
				<button class="btn-wow px-4 py-2 text-sm">Set up 2FA</button>
			</form>
			{#if form?.message && form?.section === 'twofa'}<p class="mt-2 text-sm text-red-400">
					{form.message}
				</p>{/if}
		{/if}
	</section>
</div>
