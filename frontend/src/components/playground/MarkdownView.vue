<script setup lang="ts">
import { computed } from 'vue'
import MarkdownIt from 'markdown-it'
import hljs from 'highlight.js/lib/core'
import bash from 'highlight.js/lib/languages/bash'
import python from 'highlight.js/lib/languages/python'
import javascript from 'highlight.js/lib/languages/javascript'
import typescript from 'highlight.js/lib/languages/typescript'
import json from 'highlight.js/lib/languages/json'
import yaml from 'highlight.js/lib/languages/yaml'
import xml from 'highlight.js/lib/languages/xml'
import css from 'highlight.js/lib/languages/css'
import sql from 'highlight.js/lib/languages/sql'
import go from 'highlight.js/lib/languages/go'
import rust from 'highlight.js/lib/languages/rust'
import java from 'highlight.js/lib/languages/java'
import cpp from 'highlight.js/lib/languages/cpp'
import csharp from 'highlight.js/lib/languages/csharp'
import diff from 'highlight.js/lib/languages/diff'
import markdown from 'highlight.js/lib/languages/markdown'
import ini from 'highlight.js/lib/languages/ini'
import dockerfile from 'highlight.js/lib/languages/dockerfile'
import { ok, fail } from '../../stores/toast'

const langs: Record<string, unknown> = { bash, python, javascript, typescript, json, yaml, xml, css, sql, go, rust, java, cpp, csharp, diff, markdown, ini, dockerfile }
for (const [n, l] of Object.entries(langs)) if (!hljs.getLanguage(n)) hljs.registerLanguage(n, l as Parameters<typeof hljs.registerLanguage>[1])
hljs.registerAliases(['sh', 'shell', 'zsh', 'console'], { languageName: 'bash' })
hljs.registerAliases(['py'], { languageName: 'python' })
hljs.registerAliases(['js', 'jsx', 'mjs'], { languageName: 'javascript' })
hljs.registerAliases(['ts', 'tsx', 'vue'], { languageName: 'typescript' })
hljs.registerAliases(['html', 'svg'], { languageName: 'xml' })
hljs.registerAliases(['yml'], { languageName: 'yaml' })
hljs.registerAliases(['toml'], { languageName: 'ini' })

const md: MarkdownIt = new MarkdownIt({ html: false, linkify: true, breaks: false, typographer: false })
const esc = md.utils.escapeHtml
md.renderer.rules.fence = (tokens, idx) => {
  const t = tokens[idx]
  const lang = (t.info || '').trim().split(/\s+/)[0].toLowerCase()
  let body: string
  try { body = lang && hljs.getLanguage(lang) ? hljs.highlight(t.content, { language: lang, ignoreIllegals: true }).value : esc(t.content) } catch { body = esc(t.content) }
  return '<div class="md-code"><div class="md-code-bar"><span>' + esc(lang || 'text') + '</span><button type="button" class="md-copy" data-copy="1">Copy</button></div><pre><code class="hljs">' + body + '</code></pre></div>'
}
const defaultLink = md.renderer.rules.link_open || ((tokens, idx, options, _env, self) => self.renderToken(tokens, idx, options))
md.renderer.rules.link_open = (tokens, idx, options, env, self) => {
  tokens[idx].attrSet('target', '_blank')
  tokens[idx].attrSet('rel', 'noopener noreferrer')
  return defaultLink(tokens, idx, options, env, self)
}

const props = defineProps<{ source: string; streaming?: boolean }>()
const html = computed(() => md.render(props.source || ''))

async function onClick(e: MouseEvent) {
  const btn = (e.target as HTMLElement).closest('[data-copy]') as HTMLButtonElement | null
  if (!btn) return
  const code = btn.closest('.md-code')?.querySelector('code')?.textContent ?? ''
  try {
    if (navigator.clipboard && window.isSecureContext) await navigator.clipboard.writeText(code)
    else {
      const ta = document.createElement('textarea'); ta.value = code; document.body.appendChild(ta); ta.select(); document.execCommand('copy'); ta.remove()
    }
    btn.textContent = 'Copied'
    btn.classList.add('done')
    setTimeout(() => { btn.textContent = 'Copy'; btn.classList.remove('done') }, 1500)
    if (code.length > 2000) ok('Code copied to clipboard')
  } catch (err) { fail('Copy failed', err) }
}
</script>

<template>
  <div class="md" :class="{ streaming }" @click="onClick" v-html="html" />
</template>

<style scoped>
.md { font-size: 14px; line-height: 1.65; color: var(--text); word-wrap: break-word; overflow-wrap: anywhere; }
.md :deep(> *:first-child) { margin-top: 0; }
.md :deep(> *:last-child) { margin-bottom: 0; }
.md :deep(p) { margin: 0 0 10px; }
.md :deep(h1), .md :deep(h2), .md :deep(h3), .md :deep(h4) { margin: 16px 0 8px; font-weight: 600; line-height: 1.3; }
.md :deep(h1) { font-size: 19px; } .md :deep(h2) { font-size: 17px; } .md :deep(h3) { font-size: 15px; } .md :deep(h4) { font-size: 14px; }
.md :deep(ul), .md :deep(ol) { margin: 0 0 10px; padding-left: 22px; }
.md :deep(li) { margin: 3px 0; }
.md :deep(li > p) { margin: 0; }
.md :deep(blockquote) { margin: 0 0 10px; padding: 2px 12px; border-left: 2px solid var(--primary); color: var(--text-2); }
.md :deep(hr) { border: 0; border-top: 1px solid var(--border); margin: 14px 0; }
.md :deep(a) { color: var(--primary); text-decoration: underline; text-underline-offset: 2px; }
.md :deep(table) { border-collapse: collapse; margin: 0 0 12px; font-size: 13px; display: block; overflow-x: auto; max-width: 100%; }
.md :deep(th), .md :deep(td) { border: 1px solid var(--border); padding: 6px 10px; text-align: left; }
.md :deep(th) { background: var(--bg-subtle); font-weight: 600; }
.md :deep(:not(pre) > code) { background: var(--bg-subtle); border: 1px solid var(--border); border-radius: 3px; padding: 0 4px; font-size: 12.5px; }
.md :deep(.md-code) { color-scheme: dark; scrollbar-color: var(--code-border) transparent; background: var(--code-bg); border-radius: var(--radius); overflow: hidden; border: 1px solid var(--code-border); margin: 4px 0 12px; }
.md :deep(.md-code-bar) { display: flex; justify-content: space-between; align-items: center; padding: 4px 6px 4px 14px; background: var(--code-bar); border-bottom: 1px solid var(--code-border); font: 11px var(--font-code); color: var(--code-muted); }
.md :deep(.md-copy) { font: 500 11px var(--font); color: var(--code-muted); background: transparent; border: 1px solid var(--code-border); border-radius: 3px; padding: 2px 8px; cursor: pointer; }
.md :deep(.md-copy:hover) { color: var(--code-text); background: rgba(236, 230, 220, .06); }
.md :deep(.md-copy.done) { color: var(--hl-string); border-color: color-mix(in srgb, var(--hl-string) 40%, transparent); }
.md :deep(pre) { margin: 0; padding: 12px 16px; overflow-x: auto; line-height: 1.65; color: var(--code-text); }
.md :deep(pre code) { font-size: 12.5px; }
.md.streaming :deep(> *:last-child)::after { content: ''; display: inline-block; width: 6px; height: 14px; margin-left: 2px; vertical-align: -2px; background: var(--primary); animation: blink 1s steps(2) infinite; }
@keyframes blink { 50% { opacity: 0; } }
/* warm highlight.js theme (code blocks are dark in both modes; tokens in styles.css) */
.md :deep(.hljs-comment), .md :deep(.hljs-quote) { color: var(--hl-comment); font-style: italic; }
.md :deep(.hljs-keyword), .md :deep(.hljs-selector-tag), .md :deep(.hljs-built_in), .md :deep(.hljs-meta .hljs-keyword) { color: var(--hl-keyword); }
.md :deep(.hljs-string), .md :deep(.hljs-regexp), .md :deep(.hljs-addition), .md :deep(.hljs-meta .hljs-string) { color: var(--hl-string); }
.md :deep(.hljs-number), .md :deep(.hljs-literal), .md :deep(.hljs-symbol), .md :deep(.hljs-bullet) { color: var(--hl-number); }
.md :deep(.hljs-title), .md :deep(.hljs-title.function_), .md :deep(.hljs-section) { color: var(--hl-title); }
.md :deep(.hljs-attr), .md :deep(.hljs-attribute), .md :deep(.hljs-variable), .md :deep(.hljs-template-variable), .md :deep(.hljs-property) { color: var(--hl-attr); }
.md :deep(.hljs-type), .md :deep(.hljs-class .hljs-title), .md :deep(.hljs-title.class_) { color: var(--hl-title); }
.md :deep(.hljs-tag), .md :deep(.hljs-name) { color: var(--hl-tag); }
.md :deep(.hljs-deletion) { color: var(--hl-del); }
.md :deep(.hljs-meta) { color: var(--hl-meta); }
.md :deep(.hljs-emphasis) { font-style: italic; }
.md :deep(.hljs-strong) { font-weight: 600; }
</style>
