import { createApp } from 'vue'
import App from './App.vue'
import { router } from './router'
import './styles.css'
import { installLabelLinker } from './a11y'

createApp(App).use(router).mount('#app')
installLabelLinker()
