<script lang="ts">
	let { errors }: { errors?: string[] } = $props();
</script>

{#if errors?.length}
	<p class="mt-1 text-sm text-red-600">{errors[0]}</p>
{/if}
