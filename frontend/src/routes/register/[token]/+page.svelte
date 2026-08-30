<script lang="ts">
	import { untrack } from 'svelte';
	import { page } from '$app/state';
	import { enhance } from '$app/forms';
	import { resolve } from '$app/paths';
	import FieldErrors from '$lib/components/FieldErrors.svelte';
	let { data, form } = $props();

	let username = $state(untrack(() => form?.values?.username ?? ''));
	let usernameCheck = $state<{ valid: boolean; available: boolean } | null>(null);
	let checking = $state(false);
	let debounceHandle: ReturnType<typeof setTimeout> | undefined;

	$effect(() => {
		const value = username;
		usernameCheck = null;
		clearTimeout(debounceHandle);
		if (!value) return;
		checking = true;
		debounceHandle = setTimeout(async () => {
			const token = encodeURIComponent(page.params.token ?? '');
			try {
				const res = await fetch(
					`/register/${token}/check-username?username=${encodeURIComponent(value)}`
				);
				const result = await res.json();
				if (value === username) usernameCheck = result;
			} finally {
				if (value === username) checking = false;
			}
		}, 400);
		return () => clearTimeout(debounceHandle);
	});
</script>

<svelte:head><title>Create your account · Account Portal</title></svelte:head>

<div class="wow-card mx-auto max-w-sm p-8">
	{#if form?.success}
		<h1 class="wow-heading mb-3 text-xl">Account created</h1>
		<p class="text-sm text-parchment/70">
			Your account <b>{form.username}</b> is ready. Use it in the game client, or
			<a href={resolve('/login')} class="underline">log in to the portal</a> to manage it.
		</p>
	{:else if data.invalid}
		<h1 class="wow-heading mb-3 text-xl">Invite not valid</h1>
		<p class="text-sm text-parchment/70">{data.invalid}</p>
	{:else}
		<h1 class="wow-heading mb-1 text-xl">Create your account</h1>
		<p class="mb-4 text-sm text-q-poor">Invited: {data.email}</p>
		<form method="POST" use:enhance>
			<label class="mb-1 block text-sm" for="username">Username</label>
			<input
				id="username"
				name="username"
				bind:value={username}
				class="wow-input w-full px-3 py-2"
			/>
			<FieldErrors errors={form?.errors?.username} />
			{#if username && checking}
				<p class="mt-1 text-xs text-q-poor">Checking availability…</p>
			{:else if username && usernameCheck && !usernameCheck.valid}
				<p class="mt-1 text-xs text-red-400">Invalid username</p>
			{:else if username && usernameCheck && usernameCheck.available}
				<p class="mt-1 text-xs text-green-600">Username available</p>
			{:else if username && usernameCheck && !usernameCheck.available}
				<p class="mt-1 text-xs text-red-400">Username already taken</p>
			{/if}
			<label class="mt-3 mb-1 block text-sm" for="password">Password</label>
			<input id="password" name="password" type="password" class="wow-input w-full px-3 py-2" />
			<FieldErrors errors={form?.errors?.password} />
			<label class="mt-3 mb-1 block text-sm" for="confirm">Confirm password</label>
			<input id="confirm" name="confirm" type="password" class="wow-input w-full px-3 py-2" />
			<FieldErrors errors={form?.errors?.confirm} />
			{#if form?.message}<p class="mt-2 text-sm text-red-400">{form.message}</p>{/if}
			<button class="btn-wow mt-6 w-full py-2.5">Create account</button>
		</form>
		<p class="mt-3 text-xs text-q-poor">
			Username: 3–20 letters or numbers. Password: 8–16 characters (game client limit).
		</p>
	{/if}
</div>
