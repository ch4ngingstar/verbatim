'use client'
import { useState, useEffect, useCallback } from 'react'
import { useParams, useRouter } from 'next/navigation'
import type { Project } from '@/lib/types'
import {
  getProject, listChapters, getPipelineStatus,
  startPipeline, exportM4B,
} from '@/lib/api'
import { useSSE } from '@/hooks/useSSE'
import { usePipelineState } from '@/hooks/usePipelineState'
import { CommandStrip } from '@/components/CommandStrip'
import { ChapterQueue } from '@/components/ChapterQueue'
import { CastingStudio } from '@/components/CastingStudio'
import { Toasts, toast } from '@/components/Toasts'

type Tab = 'command' | 'casting'

// Start-pipeline modal state
interface StartForm {
  llmPath:    string
  ttsDir:     string
  rangeFrom:  string
  rangeTo:    string
}

const DEFAULT_FORM: StartForm = {
  llmPath:   '',
  ttsDir:    'index-tts/checkpoints',
  rangeFrom: '',
  rangeTo:   '',
}

export default function ProjectPage() {
  const { id }   = useParams<{ id: string }>()
  const router   = useRouter()
  const projectId = Number(id)

  const [project,  setProject]  = useState<Project | null>(null)
  const [tab,      setTab]      = useState<Tab>('command')
  const [showForm, setShowForm] = useState(false)
  const [form,     setForm]     = useState<StartForm>(DEFAULT_FORM)
  const [starting, setStarting] = useState(false)
  const [exporting, setExporting] = useState(false)

  const { state: pipe, setChapters, setPipeline, handleSSE, reset } = usePipelineState()

  // SSE — always connected on this page
  useSSE(useCallback((e) => {
    handleSSE(e)
    if (e.type === 'chapter_error' && e.message) {
      toast(`ch${(e.chapter_index ?? 0) + 1}: ${e.message}`, 'crimson', 8000)
    }
  }, [handleSSE]))

  const loadChapters = useCallback(async () => {
    try {
      const chapters = await listChapters(projectId)
      setChapters(chapters)
    } catch (e) {
      toast((e as Error).message, 'crimson')
    }
  }, [projectId, setChapters])

  useEffect(() => {
    async function init() {
      try {
        const [proj, status] = await Promise.all([
          getProject(projectId),
          getPipelineStatus(),
        ])
        setProject(proj)
        if (status.state !== 'idle') setPipeline(status.state, status.project_id)
        await loadChapters()
      } catch {
        toast('Failed to load project', 'crimson')
        router.push('/')
      }
    }
    void init()
  }, [projectId, loadChapters, setPipeline, router])

  async function handleStart() {
    if (!form.llmPath.trim()) { toast('LLM model path is required', 'warn'); return }
    const rangeFrom = form.rangeFrom ? parseInt(form.rangeFrom, 10) : undefined
    const rangeTo   = form.rangeTo   ? parseInt(form.rangeTo,   10) : undefined
    const range = (rangeFrom !== undefined && rangeTo !== undefined)
      ? [rangeFrom, rangeTo] as [number, number]
      : undefined
    setStarting(true)
    try {
      await startPipeline(projectId, form.llmPath.trim(), form.ttsDir.trim(), range)
      setPipeline('running', projectId)
      setShowForm(false)
      setTab('command')
      toast('Pipeline started', 'chrome')
    } catch (e) {
      toast((e as Error).message, 'crimson')
    } finally {
      setStarting(false)
    }
  }

  async function handleExport() {
    setExporting(true)
    try {
      const { path } = await exportM4B(projectId)
      toast(`M4B exported: ${path}`, 'chrome', 8000)
    } catch (e) {
      toast((e as Error).message, 'crimson')
    } finally {
      setExporting(false)
    }
  }

  return (
    <>
      <div className="min-h-screen flex flex-col">
        <CommandStrip pipe={pipe} onStartRequest={() => setShowForm(true)} />

        {/* Breadcrumb */}
        <div className="px-6 py-3 flex items-center gap-2 font-mono text-[11px] text-ink-muted border-b border-edge">
          <button className="hover:text-ink-primary transition-colors" onClick={() => router.push('/')}>
            Library
          </button>
          <span className="text-ink-ghost">›</span>
          <span className="text-ink-secondary">{project?.name ?? '…'}</span>
          {project?.pov_style && <>
            <span className="text-ink-ghost">·</span>
            <span>{project.pov_style} POV</span>
          </>}
          <div className="flex-1" />
          {project && (
            <button
              className="btn text-[9px] px-2 py-1"
              onClick={handleExport}
              disabled={exporting}
            >
              {exporting ? 'Exporting…' : 'Export M4B'}
            </button>
          )}
        </div>

        {/* Tabs */}
        <div className="px-6 pt-3 pb-0 flex gap-1 border-b border-edge">
          {(['command', 'casting'] as Tab[]).map(t => (
            <button
              key={t}
              onClick={() => setTab(t)}
              className={`px-4 py-2 font-display text-[11px] tracking-widest uppercase transition-colors border-b-2 -mb-px ${
                tab === t
                  ? 'text-ink-primary border-ink-primary'
                  : 'text-ink-muted border-transparent hover:text-ink-secondary'
              }`}
            >
              {t === 'command' ? 'Command Deck' : 'Casting Studio'}
            </button>
          ))}
        </div>

        {/* Tab content */}
        <main className="flex-1 px-6 py-6 max-w-5xl mx-auto w-full">
          {tab === 'command' && (
            <ChapterQueue
              chapters={pipe.chapters}
              pipe={pipe}
              onChaptersChanged={loadChapters}
            />
          )}
          {tab === 'casting' && project && (
            <CastingStudio projectId={project.id} />
          )}
        </main>
      </div>

      {/* Start pipeline modal */}
      {showForm && (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center"
          style={{ background: 'rgba(0,0,0,0.75)', backdropFilter: 'blur(6px)' }}
          onClick={e => { if (e.target === e.currentTarget) setShowForm(false) }}
        >
          <div className="deck-card p-6 w-[480px] flex flex-col gap-5 animate-fade-in">
            <h2 className="font-display text-sm font-bold tracking-[0.2em] uppercase text-ink-hot">
              Start Pipeline
            </h2>

            <div className="flex flex-col gap-3">
              <div>
                <label className="label block mb-1">LLM Model Path *</label>
                <input
                  className="input w-full"
                  placeholder="models/Qwen3-14B-Q4_K_M.gguf"
                  value={form.llmPath}
                  onChange={e => setForm(f => ({ ...f, llmPath: e.target.value }))}
                />
              </div>
              <div>
                <label className="label block mb-1">TTS Model Dir</label>
                <input
                  className="input w-full"
                  value={form.ttsDir}
                  onChange={e => setForm(f => ({ ...f, ttsDir: e.target.value }))}
                />
              </div>
              <div className="flex gap-3">
                <div className="flex-1">
                  <label className="label block mb-1">From Chapter</label>
                  <input
                    className="input w-full"
                    placeholder="1"
                    value={form.rangeFrom}
                    onChange={e => setForm(f => ({ ...f, rangeFrom: e.target.value }))}
                  />
                </div>
                <div className="flex-1">
                  <label className="label block mb-1">To Chapter</label>
                  <input
                    className="input w-full"
                    placeholder={project?.total_chapters?.toString() ?? ''}
                    value={form.rangeTo}
                    onChange={e => setForm(f => ({ ...f, rangeTo: e.target.value }))}
                  />
                </div>
              </div>
            </div>

            <div className="flex gap-3 justify-end">
              <button className="btn-ghost text-[10px]" onClick={() => setShowForm(false)}>
                Cancel
              </button>
              <button
                className="btn-primary text-[10px]"
                onClick={handleStart}
                disabled={starting || !form.llmPath.trim()}
              >
                {starting ? 'Starting…' : 'Start'}
              </button>
            </div>
          </div>
        </div>
      )}

      <Toasts />
    </>
  )
}
