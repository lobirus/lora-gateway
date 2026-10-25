export interface SnippetCtx { openai: string; anthropic: string; key: string; model: string; models: string[] }

export interface Snippet { id: string; title: string; file: string; lang: string; code: string; note?: string }

export function buildSnippets(c: SnippetCtx): Snippet[] {
  const ms = c.models.length ? c.models : [c.model]
  const opencodeModels = Object.fromEntries(ms.map((m) => [m, { name: m }]))
  return [
    {
      id: 'malac', title: 'malac (recommended)', file: '~/.malac/config.toml', lang: 'toml',
      note: 'malac is the recommended client (github.com/lobirus/malac). Store the key once with: printf %s "$LORA_GATEWAY_API_KEY" | malac provider add lora --api-key-stdin, or keep it in the LORA_GATEWAY_API_KEY env var as below. Switch models with /model or F4.',
      code: `model = "lora/${c.model}"
small_model = "lora/${ms.includes('fast') ? 'fast' : c.model}"
${ms.includes('vision') ? 'vision_model = "lora/vision"\n' : ''}
[providers.lora]
kind = "openai"
base_url = "${c.openai}"
api_key_env = "LORA_GATEWAY_API_KEY"
models = [${ms.map((m) => `"${m}"`).join(', ')}]

# The same gateway also speaks the Anthropic Messages API.
[providers.lora-anthropic]
kind = "anthropic"
base_url = "${c.anthropic}"
api_key_env = "LORA_GATEWAY_API_KEY"
models = [${ms.map((m) => `"${m}"`).join(', ')}]

[profiles.fast]
model = "lora/${ms.includes('fast') ? 'fast' : c.model}"
${ms.includes('smart') ? '\n[profiles.smart]\nmodel = "lora/smart"\n' : ''}`,
    },
    {
      id: 'opencode', title: 'OpenCode', file: '~/.config/opencode/opencode.json', lang: 'json',
      note: 'Export LORA_GATEWAY_API_KEY in your shell, then pick a model with /models (shown as "Lora Gateway").',
      code: JSON.stringify({
        $schema: 'https://opencode.ai/config.json',
        provider: {
          gateway: {
            npm: '@ai-sdk/openai-compatible',
            name: 'Lora Gateway',
            options: { baseURL: c.openai, apiKey: '{env:LORA_GATEWAY_API_KEY}' },
            models: opencodeModels,
          },
        },
        model: `gateway/${c.model}`,
        small_model: `gateway/${ms.includes('fast') ? 'fast' : c.model}`,
      }, null, 2),
    },
    {
      id: 'hermes', title: 'Hermes Agent', file: '~/.hermes/config.yaml', lang: 'yaml',
      note: 'Uses Hermes\' "custom" provider (any OpenAI-compatible endpoint). Switch models with --model or /model.',
      code: `model:
  provider: "custom"
  base_url: "${c.openai}"
  api_key: "${c.key}"
  default: "${c.model}"
`,
    },
    {
      id: 'jcode', title: 'jcode', file: 'shell (writes ~/.jcode/config.toml)', lang: 'bash',
      note: 'jcode stores the profile in ~/.jcode/config.toml; the key is read from stdin so it stays out of shell history.',
      code: `printf '%s' '${c.key}' | jcode provider add lora-gateway \\
  --base-url ${c.openai} \\
  --model ${c.model} \\
  --api-key-stdin \\
  --set-default

jcode --provider-profile lora-gateway auth-test
jcode --provider-profile lora-gateway run 'hello'`,
    },
    {
      id: 'omp', title: 'omp (oh-my-pi)', file: '~/.omp/agent/models.yml', lang: 'yaml',
      note: 'apiKey names an environment variable: export LORA_GATEWAY_API_KEY=<key>. Select with /model lora-gateway/<model>.',
      code: `providers:
  lora-gateway:
    baseUrl: ${c.openai}
    apiKey: LORA_GATEWAY_API_KEY
    api: openai-completions
    models:
${ms.map((m) => `      - id: ${m}
        name: ${m}
        contextWindow: 262144
        maxTokens: 32768`).join('\n')}
`,
    },
    {
      id: 'claude', title: 'Claude Code / Anthropic', file: 'shell', lang: 'bash',
      note: 'Anthropic Messages API (/v1/messages) is translated by the gateway to any configured model.',
      code: `export ANTHROPIC_BASE_URL=${c.anthropic}
export ANTHROPIC_AUTH_TOKEN=${c.key}
export ANTHROPIC_MODEL=${c.model}
export ANTHROPIC_SMALL_FAST_MODEL=${ms.includes('fast') ? 'fast' : c.model}
claude`,
    },
    {
      id: 'openai-py', title: 'OpenAI SDK (Python)', file: 'app.py', lang: 'python',
      code: `from openai import OpenAI

client = OpenAI(base_url="${c.openai}", api_key="${c.key}")
resp = client.chat.completions.create(
    model="${c.model}",
    messages=[{"role": "user", "content": "Hello!"}],
)
print(resp.choices[0].message.content)`,
    },
    {
      id: 'openai-ts', title: 'OpenAI SDK (TypeScript)', file: 'app.ts', lang: 'ts',
      code: `import OpenAI from 'openai'

const client = new OpenAI({ baseURL: '${c.openai}', apiKey: process.env.LORA_GATEWAY_API_KEY })
const stream = await client.chat.completions.create({
  model: '${c.model}',
  messages: [{ role: 'user', content: 'Hello!' }],
  stream: true,
})
for await (const chunk of stream) process.stdout.write(chunk.choices[0]?.delta?.content ?? '')`,
    },
    {
      id: 'anthropic-py', title: 'Anthropic SDK (Python)', file: 'app.py', lang: 'python',
      code: `import anthropic

client = anthropic.Anthropic(base_url="${c.anthropic}", api_key="${c.key}")
msg = client.messages.create(
    model="${c.model}",
    max_tokens=512,
    messages=[{"role": "user", "content": "Hello!"}],
)
print(msg.content[0].text)`,
    },
    {
      id: 'curl', title: 'curl', file: 'shell', lang: 'bash',
      code: `# OpenAI-compatible
curl ${c.openai}/chat/completions \\
  -H "Authorization: Bearer ${c.key}" \\
  -H "Content-Type: application/json" \\
  -d '{"model": "${c.model}", "messages": [{"role": "user", "content": "Hello!"}]}'

# Anthropic-compatible
curl ${c.anthropic}/v1/messages \\
  -H "x-api-key: ${c.key}" \\
  -H "anthropic-version: 2023-06-01" \\
  -H "Content-Type: application/json" \\
  -d '{"model": "${c.model}", "max_tokens": 256, "messages": [{"role": "user", "content": "Hello!"}]}'

# List models available to this key
curl ${c.openai}/models -H "Authorization: Bearer ${c.key}"`,
    },
  ]
}
