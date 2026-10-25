import { createRouter, createWebHistory } from 'vue-router'
import { isAuthed } from './stores/auth'

export const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: '/login', name: 'login', component: () => import('./views/LoginView.vue'), meta: { public: true, title: 'Sign in' } },
    {
      path: '/',
      component: () => import('./components/AppShell.vue'),
      children: [
        { path: '', name: 'dashboard', component: () => import('./views/DashboardView.vue'), meta: { title: 'Dashboard' } },
        { path: 'providers', name: 'providers', component: () => import('./views/ProvidersView.vue'), meta: { title: 'Providers' } },
        { path: 'models', name: 'models', component: () => import('./views/ModelsView.vue'), meta: { title: 'Models' } },
        { path: 'keys', name: 'keys', component: () => import('./views/KeysView.vue'), meta: { title: 'API keys' } },
        { path: 'logs', name: 'logs', component: () => import('./views/LogsView.vue'), meta: { title: 'Request logs' } },
        { path: 'playground', name: 'playground', component: () => import('./views/PlaygroundView.vue'), meta: { title: 'Playground' } },
        { path: 'connect', name: 'connect', component: () => import('./views/ConnectView.vue'), meta: { title: 'Connect' } },
        { path: 'settings', name: 'settings', component: () => import('./views/SettingsView.vue'), meta: { title: 'Settings' } },
      ],
    },
    { path: '/:pathMatch(.*)*', redirect: '/' },
  ],
})

router.beforeEach((to) => {
  if (!to.meta.public && !isAuthed()) return { name: 'login', query: to.fullPath !== '/' ? { next: to.fullPath } : {} }
  if (to.name === 'login' && isAuthed()) return { name: 'dashboard' }
})
router.afterEach((to) => {
  document.title = `${(to.meta.title as string) || 'Dashboard'} · Lora Gateway`
})
