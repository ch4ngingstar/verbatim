'use client'
import { useEffect, useRef, useCallback } from 'react'
import type { SSEEvent } from '@/lib/types'

// SSE must connect directly (not through Next.js rewrites) to avoid response buffering.
const _API = (process.env.NEXT_PUBLIC_API_URL ?? 'http://localhost:8000').replace(/\/$/, '')
const SSE_URL = `${_API}/api/events`
const RECONNECT_BASE_MS = 1500
const RECONNECT_MAX_MS  = 30_000

export function useSSE(onEvent: (e: SSEEvent) => void, enabled = true) {
  const esRef     = useRef<EventSource | null>(null)
  const cbRef     = useRef(onEvent)
  const delayRef  = useRef(RECONNECT_BASE_MS)
  const timerRef  = useRef<ReturnType<typeof setTimeout> | null>(null)
  const mountedRef = useRef(true)

  cbRef.current = onEvent

  const connect = useCallback(() => {
    if (!mountedRef.current) return
    const es = new EventSource(SSE_URL)
    esRef.current = es

    es.onmessage = (raw) => {
      try {
        const evt = JSON.parse(raw.data) as SSEEvent
        cbRef.current(evt)
      } catch { /**/ }
      delayRef.current = RECONNECT_BASE_MS
    }

    es.onerror = () => {
      es.close()
      esRef.current = null
      if (!mountedRef.current) return
      timerRef.current = setTimeout(() => {
        delayRef.current = Math.min(delayRef.current * 2, RECONNECT_MAX_MS)
        connect()
      }, delayRef.current)
    }
  }, [])

  useEffect(() => {
    mountedRef.current = true
    if (enabled) connect()
    return () => {
      mountedRef.current = false
      esRef.current?.close()
      if (timerRef.current) clearTimeout(timerRef.current)
    }
  }, [enabled, connect])
}
