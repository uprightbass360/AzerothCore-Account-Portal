<script lang="ts">
	import { enhance } from '$app/forms';
	import { resolve } from '$app/paths';
	import FieldErrors from '$lib/components/FieldErrors.svelte';
	let { data, form } = $props();
</script>

<div class="mx-auto max-w-sm rounded border border-stone-300 bg-white p-6 shadow-sm">
	{#if data.invalid}
		<h1 class="mb-2 text-lg font-semibold">Invite not valid</h1>
		<p class="text-sm text-stone-600">{data.invalid}</p>
	{:else if form?.success}
		<h1 class="mb-2 text-lg font-semibold">Account created</h1>
		<p class="text-sm text-stone-600">
			Your account <b>{form.username}</b> is ready. Use it in the game client, or
			<a href={resolve('/login')} class="underline">log in to the portal</a> to manage it.
		</p>
	{:else}
		<h1 class="mb-1 text-lg font-semibold">Create your account</h1>
		<p class="mb-4 text-sm text-stone-500">Invited: {data.email}</p>
		<form method="POST" use:enhance>
			<label class="mb-1 block text-sm" for="username">Username</label>
			<input
				id="username"
				name="username"
				value={form?.values?.username ?? ''}
				class="w-full rounded border border-stone-300 px-3 py-2"
			/>
			<FieldErrors errors={form?.errors?.username} />
			<label class="mt-3 mb-1 block text-sm" for="password">Password</label>
			<input
				id="password"
				name="password"
				type="password"
				class="w-full rounded border border-stone-300 px-3 py-2"
			/>
			<FieldErrors errors={form?.errors?.password} />
			<label class="mt-3 mb-1 block text-sm" for="confirm">Confirm password</label>
			<input
				id="confirm"
				name="confirm"
				type="password"
				class="w-full rounded border border-stone-300 px-3 py-2"
			/>
			<FieldErrors errors={form?.errors?.confirm} />
			{#if form?.message}<p class="mt-2 text-sm text-red-600">{form.message}</p>{/if}
			<button class="mt-4 w-full rounded bg-stone-900 py-2 text-stone-100">Create account</button>
		</form>
		<p class="mt-3 text-xs text-stone-500">
			Username: 3–20 letters or numbers. Password: 8–16 characters (game client limit).
		</p>
	{/if}
</div>
