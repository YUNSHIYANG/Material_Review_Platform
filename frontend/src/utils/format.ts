// 后端统一存储 UTC 时间且序列化为无时区 ISO 串（如 2026-08-07T01:42:00）。
// 这里按 UTC 解析，再固定转换为东八区（Asia/Shanghai）显示，避免浏览器时区差异。
export function formatTime(s?: string | null): string {
  if (!s) return '-'
  const t = /(?:Z|[+-]\d{2}:\d{2})$/.test(s) ? s : s + 'Z'
  return new Date(t).toLocaleString('zh-CN', { timeZone: 'Asia/Shanghai', hour12: false })
}

export function statusTagType(status: string): 'success' | 'danger' | 'warning' | 'info' | 'primary' {
  switch (status) {
    case 'passed':
      return 'success'
    case 'rejected':
      return 'danger'
    case 'withdrawn':
    case 'returned':
      return 'info'
    case 'pending_admin_intervention':
      return 'danger'
    default:
      return 'warning'
  }
}

export function resultText(result: boolean | null): string {
  if (result === null) return '—'
  return result ? '通过' : '不通过'
}
