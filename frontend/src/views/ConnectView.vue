<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { Globe, Laptop, KeyRound } from 'lucide-vue-next'
import { api } from '../api'
import type { Alias, ApiKey, ConnectInfo } from '../types'
import { fail } from '../stores/toast'
import CodeBlock from '../components/CodeBlock.vue'
import CopyButton from '../components/CopyButton.vue'
import { buildSnippets } from '../snippets'

const info = ref<ConnectInfo | null>(null)
const keys = ref<ApiKey[]>([])
const aliases = ref<Alias[]>([])
const keyId = ref<number | null>(null)
const keyValue = ref('')
const model = ref('default')
const where = ref<'remote' | 'local'>('remote')
const tab = ref('opencode')

onMounted(async () => {
  try {
    const [c, k, a] = await Promise.all([api.get<ConnectInfo>('/api/connect'), api.get<ApiKey[]>('/api/keys'), api.get<Alias[]>('/api/aliases')])
    info.value = c; keys.value = k.filter((x) => !x.revoked); aliases.value = a
    if (keys.value.length) await pickKey(keys.value[0].id)
  } catch (e) { fail('Could not load connection info', e) }
})
async function pickKey(id: number) {
  keyId.value = id
  try { keyValue.value = (await api.get<{ key: string }>(`/api/keys/${id}/reveal`)).key } catch (e) { fail('Could not load key', e) }
}
const openai = computed(() => (where.value === 'remote' ? info.value?.openai_base_url : info.value?.local_openai_base_url) || '')
const anthropic = computed(() => (where.value === 'remote' ? info.value?.anthropic_base_url : info.value?.local_anthropic_base_url) || '')
const allModels = computed(() => [...(info.value?.aliases || []), ...(info.value?.models || [])])
const snippets = computed(() => buildSnippets({ openai: openai.value, anthropic: anthropic.value, key: keyValue.value || '<YOUR_GATEWAY_KEY>', model: model.value, models: allModels.value }))
</script>

<template>
  <div class="page">
    <div class="page-header">
      <div>
        <h1>Connect</h1>
        <p>Point any OpenAI- or Anthropic-compatible tool at the gateway. Snippets below include your selected key.</p>
      </div>
    </div>

    <div class="endpoints">
      <div class="card ep">
        <div class="eh"><Globe :size="16" /> OpenAI-compatible base URL</div>
        <div class="row"><code>{{ openai }}</code><CopyButton :text="openai" /></div>
        <div class="muted small">/chat/completions · /completions · /embeddings · /models · /responses</div>
      </div>
      <div class="card ep">
        <div class="eh"><Globe :size="16" /> Anthropic-compatible base URL</div>
        <div class="row"><code>{{ anthropic }}</code><CopyButton :text="anthropic" /></div>
        <div class="muted small">SDK appends /v1/messages · use x-api-key or Bearer auth</div>
      </div>
      <div class="card ep">
        <div class="eh"><KeyRound :size="16" /> API key</div>
        <div class="row">
          <select class="input" :value="keyId ?? ''" @change="pickKey(+($event.target as HTMLSelectElement).value)"><option v-for="k in keys" :key="k.id" :value="k.id">{{ k.name }}</option></select>
          <CopyButton :text="keyValue" />
        </div>
        <div class="muted small"><RouterLink to="/keys">Manage keys →</RouterLink></div>
      </div>
    </div>

    <div class="card" style="margin-top: 18px">
      <div class="card-header">
        <div class="tabs"><button v-for="s in snippets" :key="s.id" :class="{ active: tab === s.id }" :aria-pressed="tab === s.id" @click="tab = s.id">{{ s.title }}</button></div>
        <div class="toolbar">
          <div class="segmented"><button :class="{ active: where === 'remote' }" :aria-pressed="where === 'remote'" @click="where = 'remote'"><Globe :size="12" /> Remote</button><button :class="{ active: where === 'local' }" :aria-pressed="where === 'local'" @click="where = 'local'"><Laptop :size="12" /> On server</button></div>
          <select v-model="model" class="input" style="width: 210px"><option v-for="m in allModels" :key="m" :value="m">{{ m }}</option></select>
        </div>
      </div>
      <div class="card-body">
        <template v-for="s in snippets" :key="s.id">
          <div v-if="s.id === tab">
            <p v-if="s.note" class="muted" style="margin: 0 0 12px">{{ s.note }}</p>
            <CodeBlock :code="s.code" :title="s.file" />
          </div>
        </template>
      </div>
    </div>

    <div class="card" style="margin-top: 18px">
      <div class="card-header"><div><h3>Available model names</h3><div class="sub">Use any of these as the "model" parameter</div></div></div>
      <div class="card-body models">
        <span v-for="a in aliases.filter((a) => a.live)" :key="a.id" class="badge badge-primary mono" :title="a.target?.display_name">{{ a.name }} → {{ a.target?.model_name }}</span>
        <span v-for="m in info?.models" :key="m" class="badge mono">{{ m }}</span>
      </div>
    </div>
  </div>
</template>

<style scoped>
.endpoints { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 14px; }
.ep { padding: 16px; display: flex; flex-direction: column; gap: 10px; }
.eh { display: flex; align-items: center; gap: 8px; font-weight: 500; font-size: 12.5px; color: var(--text-2); }
.ep code { flex: 1; background: var(--bg); border: 1px solid var(--border); border-radius: var(--radius-sm); padding: 7px 10px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.small { font-size: 12px; }
.tabs { display: flex; flex-wrap: wrap; gap: 2px; }
.tabs button { border: 0; background: transparent; padding: 6px 10px; border-radius: var(--radius-sm); font: 500 13px var(--font); color: var(--text-2); cursor: pointer; }
.tabs button:hover { background: var(--bg-hover); }
.tabs button.active { background: var(--ink); color: var(--on-ink); }
.card-header { flex-wrap: wrap; }
.segmented button { display: inline-flex; align-items: center; gap: 5px; }
.models { display: flex; flex-wrap: wrap; gap: 8px; }
@media (max-width: 1000px) { .endpoints { grid-template-columns: 1fr; } }
</style>
