'use client'
import type { PipelineState } from '@/hooks/usePipelineState'
import { pausePipeline, resumePipeline, stopPipeline } from '@/lib/api'
import { toast } from './Toasts'

interface Props {
  pipe: PipelineState
  onStartRequest: () => void
}

const STAGE_LABELS: Record<string, string> = {
  llm:      'Diarizing',
  tts:      'Synthesising',
  assemble: 'Assembling',
  m4b:      'Exporting',
}

export function CommandStrip({ pipe, onStartRequest }: Props) {
  const isRunning  = pipe.state === 'running'
  const isPaused   = pipe.state === 'paused'
  const isStopping = pipe.state === 'stopping'
  const isActive   = isRunning || isPaused || isStopping

  const stageLabel = pipe.activeStage ? (STAGE_LABELS[pipe.activeStage] ?? pipe.activeStage) : null
  const lineLabel  =
    pipe.activeLine !== null && pipe.totalLines !== null
      ? `${pipe.activeLine + 1} / ${pipe.totalLines}`
      : null
  const chLabel = pipe.activeChIdx !== null ? `ch ${pipe.activeChIdx + 1}` : null

  async function handlePauseResume() {
    try {
      if (isRunning) await pausePipeline()
      else if (isPaused) await resumePipeline()
    } catch (e) {
      toast((e as Error).message, 'crimson')
    }
  }

  async function handleStop() {
    try { await stopPipeline() } catch (e) { toast((e as Error).message, 'crimson') }
  }

  return (
    <header className="glass-panel sticky top-0 z-20 px-6 py-3 flex items-center gap-4">
      <span className="font-display text-sm font-bold tracking-[0.22em] uppercase text-ink-hot flicker">
        Verbatim
      </span>

      <div className="weaver-thread flex-1 mx-2" />

      {/* Status pill */}
      {isActive && (
        <div className="flex items-center gap-2 font-mono text-[11px] text-ink-muted">
          {isRunning && (
            <span className="flex gap-[2px] items-end h-3">
              {[0, 1, 2].map(i => (
                <span
                  key={i}
                  className="w-[3px] bg-ink-primary rounded-sm animate-equalize"
                  style={{ height: '100%', animationDelay: `${i * 0.18}s` }}
                />
              ))}
            </span>
          )}
          {isPaused   && <span className="text-dot-diarized">⏸</span>}
          {isStopping && <span className="opacity-50 animate-breathe">stopping</span>}
          {chLabel    && <span>{chLabel}</span>}
          {stageLabel && <span className="text-ink-ghost">·</span>}
          {stageLabel && <span>{stageLabel}</span>}
          {lineLabel  && <span className="text-ink-ghost">·</span>}
          {lineLabel  && <span>{lineLabel}</span>}
        </div>
      )}

      {/* Controls */}
      {!isActive && (
        <button className="btn-primary text-[10px]" onClick={onStartRequest}>
          Start Pipeline
        </button>
      )}
      {isActive && (
        <div className="flex gap-2">
          <button
            className="btn text-[10px]"
            onClick={handlePauseResume}
            disabled={isStopping}
          >
            {isRunning ? 'Pause' : isPaused ? 'Resume' : '…'}
          </button>
          <button
            className="btn-danger text-[10px]"
            onClick={handleStop}
            disabled={isStopping}
          >
            Stop
          </button>
        </div>
      )}
    </header>
  )
}
