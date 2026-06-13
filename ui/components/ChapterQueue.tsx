'use client'
import { useCallback } from 'react'
import type { Chapter } from '@/lib/types'
import type { PipelineState } from '@/hooks/usePipelineState'
import { resetChapter, deleteChapterAudio, audioUrl } from '@/lib/api'
import { toast } from './Toasts'

interface Props {
  chapters: Chapter[]
  pipe: PipelineState
  onChaptersChanged: () => void
}

const STATUS_DOT: Record<Chapter['status'], string> = {
  pending:   'bg-dot-pending',
  diarized:  'bg-dot-diarized',
  tts_done:  'bg-dot-tts',
  assembled: 'bg-dot-complete',
  complete:  'bg-dot-complete',
  error:     'bg-dot-error',
}

const STATUS_LABEL: Record<Chapter['status'], string> = {
  pending:   'pending',
  diarized:  'diarized',
  tts_done:  'tts done',
  assembled: 'assembled',
  complete:  'complete',
  error:     'error',
}

export function ChapterQueue({ chapters, pipe, onChaptersChanged }: Props) {
  const handleReset = useCallback(async (ch: Chapter) => {
    try {
      await resetChapter(ch.id)
      toast(`Chapter ${ch.chapter_index + 1} reset to pending`, 'chrome')
      onChaptersChanged()
    } catch (e) {
      toast((e as Error).message, 'crimson')
    }
  }, [onChaptersChanged])

  const handleDeleteAudio = useCallback(async (ch: Chapter) => {
    try {
      await deleteChapterAudio(ch.id)
      toast(`Audio deleted for chapter ${ch.chapter_index + 1}`, 'chrome')
      onChaptersChanged()
    } catch (e) {
      toast((e as Error).message, 'crimson')
    }
  }, [onChaptersChanged])

  if (!chapters.length) {
    return (
      <div className="flex items-center justify-center h-40 text-ink-ghost text-xs font-mono">
        no chapters loaded
      </div>
    )
  }

  const complete = chapters.filter(c => c.status === 'complete').length
  const pct = chapters.length ? Math.round((complete / chapters.length) * 100) : 0

  return (
    <div className="flex flex-col gap-3">
      {/* Summary bar */}
      <div className="flex items-center gap-3 px-1">
        <span className="label">Progress</span>
        <div className="progress-track flex-1">
          <span className="progress-fill" style={{ width: `${pct}%` }} />
        </div>
        <span className="font-mono text-[11px] text-ink-muted">{complete} / {chapters.length}</span>
      </div>

      {/* Chapter strip */}
      <div className="flex flex-wrap gap-1 px-1">
        {chapters.map(ch => {
          const isActive = pipe.activeChIdx === ch.chapter_index && pipe.state === 'running'
          return (
            <div
              key={ch.id}
              title={`${ch.title} — ${STATUS_LABEL[ch.status]}`}
              className={`w-4 h-4 rounded-sm cursor-default transition-all ${STATUS_DOT[ch.status]} ${isActive ? 'animate-glowpulse ring-1 ring-ink-primary' : ''}`}
            />
          )
        })}
      </div>

      <div className="weaver-thread my-1" />

      {/* Chapter list */}
      <div className="flex flex-col gap-1 max-h-[560px] overflow-y-auto">
        {chapters.map(ch => {
          const isActive = pipe.activeChIdx === ch.chapter_index && pipe.state === 'running'
          return (
            <div
              key={ch.id}
              className={`memory-card px-3 py-2 flex items-center gap-3 ${isActive ? 'memory-card--ready animate-glowpulse' : ''}`}
            >
              <span className={`w-2 h-2 rounded-full flex-shrink-0 ${STATUS_DOT[ch.status]}`} />

              <span className="font-mono text-[11px] text-ink-muted w-8 flex-shrink-0">
                {String(ch.chapter_index + 1).padStart(3, '0')}
              </span>

              <span className="flex-1 text-xs text-ink-secondary truncate">
                {ch.title || `Chapter ${ch.chapter_index + 1}`}
              </span>

              <span className={`chip text-[10px] ${ch.status === 'error' ? 'chip-red' : ch.status === 'complete' ? 'chip-green' : ''}`}>
                {STATUS_LABEL[ch.status]}
              </span>

              {/* Audio playback */}
              {(ch.status === 'assembled' || ch.status === 'complete') && (
                <audio
                  controls
                  src={audioUrl(ch.id)}
                  className="h-7 w-32 opacity-60 hover:opacity-100 transition-opacity"
                />
              )}

              {/* Actions */}
              <div className="flex gap-1">
                {(ch.status === 'assembled' || ch.status === 'complete') && (
                  <button
                    className="btn-ghost text-[9px] px-2 py-1"
                    onClick={() => handleDeleteAudio(ch)}
                    title="Delete assembled audio and reset for redo"
                  >
                    ✕ audio
                  </button>
                )}
                {(ch.status === 'error' || ch.status === 'diarized' || ch.status === 'tts_done') && (
                  <button
                    className="btn-ghost text-[9px] px-2 py-1"
                    onClick={() => handleReset(ch)}
                    title="Reset to pending"
                  >
                    reset
                  </button>
                )}
              </div>

              {/* Error message */}
              {ch.status === 'error' && ch.error_message && (
                <span className="text-blood-text font-mono text-[10px] max-w-[200px] truncate" title={ch.error_message}>
                  {ch.error_message}
                </span>
              )}
            </div>
          )
        })}
      </div>
    </div>
  )
}
