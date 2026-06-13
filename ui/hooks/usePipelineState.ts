'use client'
import { useReducer, useCallback } from 'react'
import type { Chapter, SSEEvent } from '@/lib/types'

export interface PipelineState {
  state:        'idle' | 'running' | 'paused' | 'stopping'
  projectId:    number | null
  activeChIdx:  number | null
  activeLine:   number | null
  totalLines:   number | null
  activeStage:  string | null
  chapters:     Chapter[]
  lastEvent:    SSEEvent | null
}

type Action =
  | { type: 'SET_CHAPTERS'; chapters: Chapter[] }
  | { type: 'SET_PIPELINE_STATE'; state: PipelineState['state']; projectId?: number }
  | { type: 'SSE'; event: SSEEvent }
  | { type: 'RESET' }

const INIT: PipelineState = {
  state: 'idle', projectId: null,
  activeChIdx: null, activeLine: null, totalLines: null,
  activeStage: null, chapters: [], lastEvent: null,
}

function reducer(s: PipelineState, a: Action): PipelineState {
  switch (a.type) {
    case 'SET_CHAPTERS':
      return { ...s, chapters: a.chapters }

    case 'SET_PIPELINE_STATE':
      return { ...s, state: a.state, projectId: a.projectId ?? s.projectId }

    case 'RESET':
      return INIT

    case 'SSE': {
      const e = a.event
      let next = { ...s, lastEvent: e }

      if (e.type === 'pipeline_start')  next.state = 'running'
      if (e.type === 'pipeline_pause')  next.state = 'paused'
      if (e.type === 'pipeline_resume') next.state = 'running'
      if (e.type === 'pipeline_stop' || e.type === 'pipeline_complete') next.state = 'idle'

      if (e.chapter_index !== undefined) next.activeChIdx  = e.chapter_index
      if (e.line_index    !== undefined) next.activeLine   = e.line_index
      if (e.total_lines   !== undefined) next.totalLines   = e.total_lines
      if (e.stage         !== undefined) next.activeStage  = e.stage

      if (e.type === 'chapter_status' && e.chapter_index !== undefined && e.status) {
        next.chapters = s.chapters.map(c =>
          c.chapter_index === e.chapter_index
            ? { ...c, status: e.status as Chapter['status'] }
            : c
        )
      }

      if (e.type === 'chapter_error' && e.chapter_index !== undefined) {
        next.chapters = s.chapters.map(c =>
          c.chapter_index === e.chapter_index
            ? { ...c, status: 'error', error_message: e.message }
            : c
        )
      }

      return next
    }
    default:
      return s
  }
}

export function usePipelineState() {
  const [state, dispatch] = useReducer(reducer, INIT)

  const setChapters  = useCallback((ch: Chapter[]) => dispatch({ type: 'SET_CHAPTERS', chapters: ch }), [])
  const setPipeline  = useCallback(
    (st: PipelineState['state'], pid?: number) => dispatch({ type: 'SET_PIPELINE_STATE', state: st, projectId: pid }),
    []
  )
  const handleSSE    = useCallback((e: SSEEvent) => dispatch({ type: 'SSE', event: e }), [])
  const reset        = useCallback(() => dispatch({ type: 'RESET' }), [])

  return { state, setChapters, setPipeline, handleSSE, reset }
}
