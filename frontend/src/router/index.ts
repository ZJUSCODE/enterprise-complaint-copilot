import { createRouter, createWebHistory } from 'vue-router';
import { useAuthStore } from '@/stores/auth';

const HomeView = () => import('@/views/HomeView.vue');
const CopilotView = () => import('@/views/CopilotView.vue');
const ReviewCenterView = () => import('@/views/ReviewCenterView.vue');
const AuditCenterView = () => import('@/views/AuditCenterView.vue');
const EvalReportView = () => import('@/views/EvalReportView.vue');
const PublicShowcaseView = () => import('@/views/PublicShowcaseView.vue');
const LoginView = () => import('@/views/LoginView.vue');
const DocumentManagerView = () => import('@/views/DocumentManagerView.vue');

const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: '/public', name: 'public', component: PublicShowcaseView, meta: { public: true } },
    { path: '/login', name: 'login', component: LoginView, meta: { public: true } },
    { path: '/', name: 'home', component: HomeView },
    { path: '/copilot', name: 'copilot', component: CopilotView },
    { path: '/audit', name: 'audit', component: AuditCenterView, meta: { roles: ['analyst', 'supervisor'] } },
    { path: '/eval', name: 'eval', component: EvalReportView, meta: { roles: ['analyst', 'supervisor'] } },
    { path: '/review', name: 'review', component: ReviewCenterView, meta: { roles: ['supervisor'] } },
    { path: '/documents', name: 'documents', component: DocumentManagerView, meta: { roles: ['analyst', 'supervisor'] } },
  ],
  scrollBehavior() {
    return { top: 0 };
  },
});

router.beforeEach((to) => {
  const auth = useAuthStore();
  if (to.meta.public) {
    return true;
  }
  if (!auth.isAuthenticated) {
    return { name: 'login', query: { redirect: to.fullPath } };
  }
  const roles = to.meta.roles as string[] | undefined;
  if (roles?.length && !roles.includes(auth.role)) {
    return { name: 'home' };
  }
  return true;
});

export default router;
