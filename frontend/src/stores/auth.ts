import { defineStore } from 'pinia'
import http from '@/api'

export interface Me {
  id: number
  username: string
  role: string
  real_name: string
  email?: string
  need_password_change?: boolean
}

export const useAuthStore = defineStore('auth', {
  state: () => ({
    token: localStorage.getItem('token') || '',
    user: null as Me | null,
  }),
  getters: {
    role: (s) => s.user?.role || '',
    isLoggedIn: (s) => !!s.token,
  },
  actions: {
    async login(username: string, password: string) {
      const { data } = await http.post('/auth/login', { username, password })
      this.token = data.access_token
      localStorage.setItem('token', data.access_token)
      this.user = {
        id: 0,
        username: data.username,
        role: data.role,
        real_name: data.real_name,
        need_password_change: data.need_password_change,
      }
      return data
    },
    async fetchMe() {
      if (!this.token) return null
      try {
        const { data } = await http.get('/auth/me')
        this.user = data
        return data
      } catch {
        return null
      }
    },
    logout() {
      this.token = ''
      this.user = null
      localStorage.removeItem('token')
    },
  },
})
