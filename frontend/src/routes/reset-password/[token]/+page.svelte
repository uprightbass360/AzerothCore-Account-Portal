<script lang="ts">
	import { enhance } from '$app/forms';
	import { resolve } from '$app/paths';
	import FieldErrors from '$lib/components/FieldErrors.svelte';
	let { data, form } = $props();
</script>

<svelte:head><title>Set new password · Account Portal</title></svelte:head>

<div class="wow-card mx-auto max-w-sm p-8">
	{#if form?.success}
		<h1 class="wow-heading mb-3 text-xl">Password updated</h1>
		<p class="text-sm text-parchment/70">
			The password for <b>{form.username}</b> has been set. Use it in the game client, or
			<a href={resolve('/login')} class="wow-link">log in to the portal</a>.
		</p>
	{:else if data.invalid}
		<h1 class="wow-heading mb-3 text-xl">Link not valid</h1>
		<p class="text-sm text-parchment/70">{data.invalid}</p>
	{:else}
		<h1 class="wow-heading mb-1 text-xl">Set a new password</h1>
		<p class="mb-4 text-sm text-q-poor">
			An administrator reset the password for <b>{data.username}</b>. Choose a new one.
		</p>
		<form method="POST" use:enhance>
			<label class="mb-1 block text-sm" for="new_password">New password</label>
			<input
				id="new_password"
				name="new_password"
				type="password"
				class="wow-input w-full px-3 py-2"
			/>
			<FieldErrors errors={form?.errors?.new_password} />
			<label class="mt-3 mb-1 block text-sm" for="confirm">Confirm password</label>
			<input id="confirm" name="confirm" type="password" class="wow-input w-full px-3 py-2" />
			<FieldErrors errors={form?.errors?.confirm} />
			{#if data.totpRequired}
				<label class="mt-3 mb-1 block text-sm" for="code">Current 2FA code</label>
				<input id="code" name="code" inputmode="numeric" class="wow-input w-32 px-3 py-2" />
				<FieldErrors errors={form?.errors?.code} />
			{/if}
			{#if form?.message}<p class="mt-2 text-sm text-red-400">{form.message}</p>{/if}
			<button class="btn-wow mt-6 w-full py-2.5">Set password</button>
		</form>
		<p class="mt-3 text-xs text-q-poor">Password: 8–16 characters (game client limit).</p>
	{/if}
</div>
