<script lang="ts">
	import { enhance } from '$app/forms';
	let { data, form } = $props();
</script>

<svelte:head><title>Confirm email · Account Portal</title></svelte:head>

<div class="wow-card mx-auto max-w-sm p-8">
	{#if form?.success}
		<h1 class="wow-heading mb-3 text-xl">Email updated</h1>
		<p class="text-sm text-parchment/70">
			The email for <b>{form.username}</b> is now <b>{form.newEmail}</b>.
		</p>
	{:else if data.invalid}
		<h1 class="wow-heading mb-3 text-xl">Link not valid</h1>
		<p class="text-sm text-parchment/70">{data.invalid}</p>
	{:else}
		<h1 class="wow-heading mb-3 text-xl">Confirm email change</h1>
		<p class="mb-4 text-sm text-parchment/70">
			Set <b>{data.newEmail}</b> as the email for your game account?
		</p>
		<form method="POST" use:enhance>
			{#if form?.message}<p class="mb-2 text-sm text-red-400">{form.message}</p>{/if}
			<button class="btn-wow w-full py-2.5">Confirm change</button>
		</form>
	{/if}
</div>
