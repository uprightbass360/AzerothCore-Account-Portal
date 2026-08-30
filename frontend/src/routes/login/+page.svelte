<script lang="ts">
	import { enhance } from '$app/forms';
	import FieldErrors from '$lib/components/FieldErrors.svelte';
	let { data, form } = $props();

	let submitFailed = $state(false);
	// Surfaces failures that happen before the action runs (e.g. an origin
	// mismatch rejecting the POST) — otherwise the form fails silently.
	const reportErrors = () => {
		submitFailed = false;
		return async ({
			result,
			update
		}: {
			result: { type: string };
			update: () => Promise<void>;
		}) => {
			if (result.type === 'error') submitFailed = true;
			else await update();
		};
	};
</script>

<svelte:head><title>Log in · Account Portal</title></svelte:head>

<div class="wow-card mx-auto max-w-sm p-8">
	{#if form?.twofa}
		<h1 class="wow-heading mb-5 text-center text-xl">Two-factor authentication</h1>
		<form method="POST" action="?/twofa" use:enhance={reportErrors}>
			<input type="hidden" name="username" value={form.username} />
			<input type="hidden" name="password" value={form.password} />
			<label class="mb-1 block text-sm" for="code">6-digit code</label>
			<input
				id="code"
				name="code"
				inputmode="numeric"
				autocomplete="one-time-code"
				class="wow-input w-full px-3 py-2"
			/>
			<FieldErrors errors={form?.errors?.code} />
			{#if form?.message}<p class="mt-2 text-sm text-red-400">{form.message}</p>{/if}
			{#if submitFailed}
				<p class="mt-2 text-sm text-red-400">
					Sign-in could not be submitted — reload the page and try again{#if data.origin}, using
						<a class="wow-link" href={data.origin}>{data.origin}</a>{/if}.
				</p>
			{/if}
			<button class="btn-wow mt-6 w-full py-2.5">Verify</button>
		</form>
	{:else}
		<div class="mb-6 text-center">
			<h1 class="wow-title text-3xl">Account Portal</h1>
			<p class="mt-2 text-sm text-q-poor">Log in with your game account</p>
		</div>
		<form method="POST" action="?/login" use:enhance={reportErrors}>
			<label class="mb-1 block text-sm" for="username">Username</label>
			<input
				id="username"
				name="username"
				value={form?.values?.username ?? ''}
				class="wow-input w-full px-3 py-2"
			/>
			<FieldErrors errors={form?.errors?.username} />
			<label class="mt-3 mb-1 block text-sm" for="password">Password</label>
			<input id="password" name="password" type="password" class="wow-input w-full px-3 py-2" />
			<FieldErrors errors={form?.errors?.password} />
			{#if form?.message}<p class="mt-2 text-sm text-red-400">{form.message}</p>{/if}
			{#if submitFailed}
				<p class="mt-2 text-sm text-red-400">
					Sign-in could not be submitted — reload the page and try again{#if data.origin}, using
						<a class="wow-link" href={data.origin}>{data.origin}</a>{/if}.
				</p>
			{/if}
			<button class="btn-wow mt-6 w-full py-2.5">Log in</button>
		</form>
	{/if}
</div>
