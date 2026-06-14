import { createRouter, createWebHistory } from 'vue-router';

const router = createRouter({
  history: createWebHistory(),
  routes: [
    {
      path: '/',
      name: 'overview',
      component: () => import('@/views/OverviewView.vue'),
    },
    {
      path: '/context-map',
      name: 'context-map',
      component: () => import('@/views/ContextMapView.vue'),
    },
    {
      path: '/sessions',
      name: 'sessions',
      component: () => import('@/views/SessionsView.vue'),
    },
    {
      path: '/sessions/:id',
      name: 'session-detail',
      component: () => import('@/views/SessionDetailView.vue'),
    },
    {
      path: '/sub-agents',
      name: 'sub-agents',
      component: () => import('@/views/SubAgentsView.vue'),
    },
    {
      path: '/tokens',
      name: 'tokens',
      component: () => import('@/views/TokensView.vue'),
    },
  ],
});

export default router;
