'use client'
import { useState, useCallback, useEffect, useRef } from 'react'
import type { Toast } from '@/lib/types'

let _push: ((t: Omit<Toast, 'id'>) => void) | null = null

export function toast(msg: string, variant: Toast['variant'] = 'chrome', ttl = 4000) {
  _push?.({ message: msg, variant, ttl })
}

export function Toasts() {
  const [toasts, setToasts] = useState<Toast[]>([])
  const timers = useRef<Map<string, ReturnType<typeof setTimeout>>>(new Map())

  const dismiss = useCallback((id: string) => {
    setToasts(prev => prev.filter(t => t.id !== id))
    const timer = timers.current.get(id)
    if (timer) { clearTimeout(timer); timers.current.delete(id) }
  }, [])

  const push = useCallback((t: Omit<Toast, 'id'>) => {
    const id = `${Date.now()}-${Math.random().toString(36).slice(2)}`
    setToasts(prev => [...prev.slice(-4), { ...t, id }])
    if (t.ttl) {
      timers.current.set(id, setTimeout(() => dismiss(id), t.ttl))
    }
  }, [dismiss])

  useEffect(() => { _push = push; return () => { _push = null } }, [push])

  if (!toasts.length) return null
  return (
    <div className="fixed bottom-5 right-5 z-50 flex flex-col gap-2 items-end">
      {toasts.map(t => (
        <div
          key={t.id}
          className={`spell-toast spell-toast--${t.variant} animate-toast-in cursor-pointer`}
          onClick={() => dismiss(t.id)}
        >
          <span className="spell-bracket">[</span>
          <span className="flex-1">{t.message}</span>
          <span className="spell-bracket">]</span>
        </div>
      ))}
    </div>
  )
}
