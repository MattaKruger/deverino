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
  ],
});

export default router;
