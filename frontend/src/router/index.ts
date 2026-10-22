import { createRouter, createWebHistory } from 'vue-router'

export const router = createRouter({
  history: createWebHistory(),
  routes: [
    {
      path: '/',
      name: 'overview',
      component: () => import('@/views/OverviewView.vue'),
      meta: { title: '总览' },
    },
    {
      path: '/runs',
      name: 'runs',
      component: () => import('@/views/RunsView.vue'),
      meta: { title: '运行记录' },
    },
    {
      path: '/runs/:id',
      name: 'run-detail',
      component: () => import('@/views/RunDetailView.vue'),
      meta: { title: '运行详情' },
    },
    {
      path: '/knowledge',
      name: 'knowledge',
      component: () => import('@/views/KnowledgeView.vue'),
      meta: { title: '知识库' },
    },
    {
      path: '/rules',
      name: 'rules',
      component: () => import('@/views/RulesView.vue'),
      meta: { title: '规则' },
    },
    {
      path: '/system',
      name: 'system',
      component: () => import('@/views/SystemView.vue'),
      meta: { title: '系统' },
    },
    { path: '/:pathMatch(.*)*', redirect: '/' },
  ],
})

router.afterEach((to) => {
  const title = (to.meta.title as string | undefined) ?? ''
  document.title = title ? `${title} · 迹觅·Evidence 观测台` : '迹觅·Evidence 观测台'
})
