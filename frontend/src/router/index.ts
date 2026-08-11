import { createRouter, createWebHistory } from 'vue-router'
import { useAuthStore } from '@/stores/auth'

const HomeView = () => import('@/views/LoginView.vue')
const ChangePasswordView = () => import('@/views/ChangePasswordView.vue')
const TeamDashboard = () => import('@/views/team/TeamDashboard.vue')
const TeamSubmit = () => import('@/views/team/TeamSubmit.vue')
const SubmissionDetail = () => import('@/views/team/SubmissionDetail.vue')
const StaffTodos = () => import('@/views/staff/StaffTodos.vue')
const StaffReview = () => import('@/views/staff/StaffReview.vue')
const AdminTodos = () => import('@/views/admin/AdminTodos.vue')
const AdminReview = () => import('@/views/admin/AdminReview.vue')
const SuperDashboard = () => import('@/views/super/SuperDashboard.vue')
const UserManage = () => import('@/views/super/UserManage.vue')
const SubmissionManage = () => import('@/views/super/SubmissionManage.vue')
const InterveneDetail = () => import('@/views/super/InterveneDetail.vue')
const EmailLogs = () => import('@/views/super/EmailLogs.vue')
const SystemConfig = () => import('@/views/super/SystemConfig.vue')
const LoadMonitor = () => import('@/views/super/LoadMonitor.vue')
const AuditLogs = () => import('@/views/super/AuditLogs.vue')

const roleHome: Record<string, string> = {
  team: '/team',
  staff: '/staff',
  admin: '/admin',
  super_admin: '/super',
}

const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: '/login', component: HomeView, meta: { layout: false } },
    { path: '/change-password', component: ChangePasswordView, meta: { layout: false } },
    { path: '/team', component: TeamDashboard, meta: { role: 'team' } },
    { path: '/team/submit', component: TeamSubmit, meta: { role: 'team' } },
    { path: '/team/submissions/:id', component: SubmissionDetail, meta: { role: 'team' } },
    { path: '/staff', component: StaffTodos, meta: { role: 'staff' } },
    { path: '/staff/submissions/:id', component: StaffReview, meta: { role: 'staff' } },
    { path: '/admin', component: AdminTodos, meta: { role: 'admin' } },
    { path: '/admin/submissions/:id', component: AdminReview, meta: { role: 'admin' } },
    { path: '/super', component: SuperDashboard, meta: { role: 'super_admin' } },
    { path: '/super/users', component: UserManage, meta: { role: 'super_admin' } },
    { path: '/super/submissions', component: SubmissionManage, meta: { role: 'super_admin' } },
    { path: '/super/submissions/:id', component: InterveneDetail, meta: { role: 'super_admin' } },
    { path: '/super/emails', component: EmailLogs, meta: { role: 'super_admin' } },
    { path: '/super/config', component: SystemConfig, meta: { role: 'super_admin' } },
    { path: '/super/load', component: LoadMonitor, meta: { role: 'super_admin' } },
    { path: '/super/audit', component: AuditLogs, meta: { role: 'super_admin' } },
    { path: '/', redirect: '/login' },
    { path: '/:pathMatch(.*)*', redirect: '/login' },
  ],
})

router.beforeEach(async (to) => {
  const auth = useAuthStore()
  if (to.path === '/login') {
    if (auth.isLoggedIn) {
      if (!auth.user) {
        // 有 token 但用户信息未加载：先校验 token，有效则进入对应首页，无效则清理并显示登录页
        const me = await auth.fetchMe()
        if (me) return roleHome[me.role] || '/'
        auth.logout()
      } else {
        return roleHome[auth.role] || '/'
      }
    }
    return true
  }
  if (!auth.isLoggedIn) return '/login'
  if (!auth.user) {
    const me = await auth.fetchMe()
    if (!me) return '/login'
  }
  if (to.path !== '/change-password' && auth.user?.need_password_change) {
    return '/change-password'
  }
  const required = to.meta.role as string | undefined
  if (required && auth.role !== required) {
    return roleHome[auth.role] || '/'
  }
  return true
})

export default router
