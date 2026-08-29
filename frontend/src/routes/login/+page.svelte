<script lang="ts">
	import { enhance } from '$app/forms';
	import FieldErrors from '$lib/components/FieldErrors.svelte';
	let { form } = $props();
</script>

<div class="mx-auto max-w-sm rounded border border-stone-300 bg-white p-6 shadow-sm">
	{#if form?.twofa}
		<h1 class="mb-4 text-lg font-semibold">Two-factor authentication</h1>
		<form method="POST" action="?/twofa" use:enhance>
			<input type="hidden" name="username" value={form.username} />
			<input type="hidden" name="password" value={form.password} />
			<label class="mb-1 block text-sm" for="code">6-digit code</label>
			<input
				id="code"
				name="code"
				inputmode="numeric"
				autocomplete="one-time-code"
				class="w-full rounded border border-stone-300 px-3 py-2"
			/>
			<FieldErrors errors={form?.errors?.code} />
			{#if form?.message}<p class="mt-2 text-sm text-red-600">{form.message}</p>{/if}
			<button class="mt-4 w-full rounded bg-stone-900 py-2 text-stone-100">Verify</button>
		</form>
	{:else}
		<h1 class="mb-4 text-lg font-semibold">Log in</h1>
		<form method="POST" action="?/login" use:enhance>
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
			{#if form?.message}<p class="mt-2 text-sm text-red-600">{form.message}</p>{/if}
			<button class="mt-4 w-full rounded bg-stone-900 py-2 text-stone-100">Log in</button>
		</form>
	{/if}
</div>
