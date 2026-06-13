'use client'
import { useState, useEffect, useRef } from 'react'
import { useRouter } from 'next/navigation'
import type { Project } from '@/lib/types'
import { listProjects, createProject } from '@/lib/api'
import { Toasts, toast } from '@/components/Toasts'

function ProjectCard({ project }: { project: Project }) {
  const router = useRouter()
  const completeCount = 0  // would need chapters endpoint per project for full count

  const STATUS_DOT: Record<Project['status'], string> = {
    idle:     'bg-dot-pending',
    running:  'bg-dot-running animate-glowpulse',
    paused:   'bg-dot-diarized',
    complete: 'bg-dot-complete',
    error:    'bg-dot-error',
  }

  return (
    <div
      className="memory-card p-5 cursor-pointer flex flex-col gap-3 hover:memory-card--ready transition-all"
      onClick={() => router.push(`/projects/${project.id}`)}
    >
      <div className="flex items-start gap-2">
        <span className={`w-2.5 h-2.5 rounded-full flex-shrink-0 mt-0.5 ${STATUS_DOT[project.status]}`} />
        <div className="flex-1 min-w-0">
          <h2 className="font-display text-sm font-bold text-ink-primary truncate tracking-wide">
            {project.name}
          </h2>
          {project.pov_style && (
            <p className="font-mono text-[11px] text-ink-muted mt-0.5">{project.pov_style} POV</p>
          )}
        </div>
        <span className="chip text-[10px]">{project.status}</span>
      </div>

      <div className="weaver-thread" />

      <div className="flex items-center gap-4 font-mono text-[11px] text-ink-muted">
        <span>{project.total_chapters} chapters</span>
        {project.pov_style && <span>·</span>}
        {project.pov_style && <span>{project.pov_style}</span>}
        <span className="flex-1" />
        <span className="text-ink-ghost text-[10px]">
          {new Date(project.created_at).toLocaleDateString()}
        </span>
      </div>
    </div>
  )
}

export default function LibraryPage() {
  const [projects, setProjects]   = useState<Project[]>([])
  const [loading,  setLoading]    = useState(true)
  const [dragging, setDragging]   = useState(false)
  const [creating, setCreating]   = useState(false)
  const dropRef = useRef<HTMLDivElement>(null)
  const router  = useRouter()

  async function load() {
    try {
      setProjects(await listProjects())
    } catch (e) {
      toast((e as Error).message, 'crimson')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => { void load() }, [])

  async function handleEpub(file: File) {
    if (!file.name.endsWith('.epub')) {
      toast('Only .epub files are supported', 'crimson')
      return
    }
    setCreating(true)
    try {
      const project = await createProject(file)
      toast(`Project created: ${project.name}`, 'chrome')
      router.push(`/projects/${project.id}`)
    } catch (e) {
      toast((e as Error).message, 'crimson')
      setCreating(false)
    }
  }

  function onDrop(e: React.DragEvent) {
    e.preventDefault()
    setDragging(false)
    const file = e.dataTransfer.files[0]
    if (file) void handleEpub(file)
  }

  function onFileInput(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0]
    if (file) void handleEpub(file)
    e.target.value = ''
  }

  return (
    <>
      <div className="min-h-screen flex flex-col">
        {/* Header */}
        <header className="glass-panel px-8 py-5 flex items-center gap-4">
          <h1 className="font-display text-lg font-bold tracking-[0.3em] uppercase text-ink-hot flicker">
            Verbatim
          </h1>
          <span className="font-mono text-xs text-ink-ghost">Audiobook Forge</span>
          <div className="weaver-thread flex-1 mx-4" />
          <span className="chip">{projects.length} project{projects.length !== 1 ? 's' : ''}</span>
        </header>

        {/* Main */}
        <main className="flex-1 px-8 py-10 max-w-5xl mx-auto w-full">

          {/* Drop zone */}
          <div
            ref={dropRef}
            onDragOver={e => { e.preventDefault(); setDragging(true) }}
            onDragLeave={() => setDragging(false)}
            onDrop={onDrop}
            className={`deck-card p-10 text-center flex flex-col items-center gap-4 mb-8 transition-all ${
              dragging ? 'border-ink-secondary animate-glowpulse' : ''
            } ${creating ? 'opacity-50 pointer-events-none' : ''}`}
          >
            <div className="font-display text-3xl text-ink-ghost select-none">✦</div>
            <div>
              <p className="font-display text-sm tracking-widest uppercase text-ink-secondary">
                {creating ? 'Parsing EPUB…' : dragging ? 'Drop to forge' : 'Drop an EPUB to begin'}
              </p>
              <p className="font-mono text-xs text-ink-muted mt-1">
                or{' '}
                <label className="underline cursor-pointer hover:text-ink-primary transition-colors">
                  browse
                  <input type="file" accept=".epub" className="hidden" onChange={onFileInput} />
                </label>
              </p>
            </div>
          </div>

          {/* Project grid */}
          {loading ? (
            <div className="text-ink-ghost text-xs font-mono text-center animate-breathe py-8">
              loading projects…
            </div>
          ) : projects.length === 0 ? (
            <div className="text-ink-ghost text-xs font-mono text-center py-8">
              no projects yet — drop an EPUB above
            </div>
          ) : (
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
              {projects.map(p => <ProjectCard key={p.id} project={p} />)}
            </div>
          )}
        </main>
      </div>
      <Toasts />
    </>
  )
}
