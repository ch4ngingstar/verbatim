'use client'
import { useState, useEffect, useCallback } from 'react'
import type { Character, Voice } from '@/lib/types'
import { listCharacters, listVoices, uploadVoice, deleteVoice, assignVoice, upsertCharacter } from '@/lib/api'
import { toast } from './Toasts'

interface Props {
  projectId: number
}

const STATUS_COLORS: Record<Character['status'], string> = {
  suggested: 'text-ink-muted',
  cast:      'text-ink-primary',
  ignored:   'text-ink-ghost',
}

export function CastingStudio({ projectId }: Props) {
  const [characters, setCharacters] = useState<Character[]>([])
  const [voices,     setVoices]     = useState<Voice[]>([])
  const [loading,    setLoading]    = useState(true)
  const [uploadName, setUploadName] = useState('')
  const [uploadFile, setUploadFile] = useState<File | null>(null)
  const [uploading,  setUploading]  = useState(false)

  const reload = useCallback(async () => {
    try {
      const [ch, vs] = await Promise.all([listCharacters(projectId), listVoices()])
      setCharacters(ch)
      setVoices(vs)
    } catch (e) {
      toast((e as Error).message, 'crimson')
    } finally {
      setLoading(false)
    }
  }, [projectId])

  useEffect(() => { void reload() }, [reload])

  async function handleUploadVoice() {
    if (!uploadName.trim() || !uploadFile) return
    setUploading(true)
    try {
      await uploadVoice(uploadName.trim(), uploadFile)
      toast(`Voice "${uploadName.trim()}" uploaded`, 'chrome')
      setUploadName('')
      setUploadFile(null)
      await reload()
    } catch (e) {
      toast((e as Error).message, 'crimson')
    } finally {
      setUploading(false)
    }
  }

  async function handleDeleteVoice(v: Voice) {
    try {
      await deleteVoice(v.id)
      toast(`Voice "${v.name}" deleted`, 'chrome')
      await reload()
    } catch (e) {
      toast((e as Error).message, 'crimson')
    }
  }

  async function handleAssignVoice(char: Character, voiceName: string) {
    try {
      await assignVoice(projectId, char.id, voiceName)
      toast(`Assigned "${voiceName}" to ${char.name}`, 'chrome')
      await reload()
    } catch (e) {
      toast((e as Error).message, 'crimson')
    }
  }

  async function handleConfirmChar(char: Character) {
    try {
      await upsertCharacter(projectId, { name: char.name, status: 'cast' })
      await reload()
    } catch (e) {
      toast((e as Error).message, 'crimson')
    }
  }

  if (loading) {
    return (
      <div className="flex items-center justify-center h-40 text-ink-ghost text-xs font-mono animate-breathe">
        loading casting data…
      </div>
    )
  }

  return (
    <div className="flex flex-col gap-6">

      {/* ── Voice library ───────────────────────────────────────── */}
      <section>
        <div className="flex items-center gap-3 mb-3">
          <span className="label">Voice Library</span>
          <span className="chip">{voices.length}</span>
        </div>

        <div className="flex flex-col gap-1 mb-4">
          {voices.length === 0 && (
            <p className="text-ink-ghost text-xs font-mono px-1">no voices uploaded yet</p>
          )}
          {voices.map(v => (
            <div key={v.id} className="memory-card px-3 py-2 flex items-center gap-3">
              <span className="flex-1 text-xs font-mono text-ink-primary">{v.name}</span>
              {v.tags && (
                <span className="chip text-[10px]">{v.tags}</span>
              )}
              <button
                className="btn-ghost text-[9px] px-2 py-1"
                onClick={() => handleDeleteVoice(v)}
              >
                delete
              </button>
            </div>
          ))}
        </div>

        {/* Upload form */}
        <div className="deck-card p-4 flex flex-col gap-3">
          <span className="label">Upload Reference Clip</span>
          <div className="flex gap-2">
            <input
              className="input flex-1"
              placeholder="voice name (e.g. Sunny, _default)"
              value={uploadName}
              onChange={e => setUploadName(e.target.value)}
            />
          </div>
          <div className="flex items-center gap-3">
            <label className="btn cursor-pointer text-[10px]">
              Choose File
              <input
                type="file"
                accept="audio/*"
                className="hidden"
                onChange={e => setUploadFile(e.target.files?.[0] ?? null)}
              />
            </label>
            {uploadFile && (
              <span className="font-mono text-xs text-ink-muted truncate max-w-[200px]">
                {uploadFile.name}
              </span>
            )}
            <button
              className="btn-primary text-[10px] ml-auto"
              disabled={!uploadName.trim() || !uploadFile || uploading}
              onClick={handleUploadVoice}
            >
              {uploading ? 'Uploading…' : 'Upload'}
            </button>
          </div>
        </div>
      </section>

      <div className="weaver-thread" />

      {/* ── Characters ──────────────────────────────────────────── */}
      <section>
        <div className="flex items-center gap-3 mb-3">
          <span className="label">Characters</span>
          <span className="chip">{characters.length}</span>
        </div>

        {characters.length === 0 && (
          <p className="text-ink-ghost text-xs font-mono px-1">
            run the diarizer first — characters are extracted automatically
          </p>
        )}

        <div className="flex flex-col gap-1">
          {characters.map(char => (
            <div
              key={char.id}
              className={`memory-card px-3 py-2 flex items-center gap-3 ${char.status === 'ignored' ? 'opacity-40' : ''}`}
            >
              {/* Status dot */}
              <span className={`w-2 h-2 rounded-full flex-shrink-0 ${
                char.status === 'cast'
                  ? 'bg-dot-complete'
                  : char.status === 'ignored'
                  ? 'bg-dot-pending'
                  : 'bg-dot-tts'
              }`} />

              {/* Name */}
              <span className={`w-32 flex-shrink-0 text-xs font-mono ${STATUS_COLORS[char.status]}`}>
                {char.name}
                {char.is_pov && <span className="ml-1 text-[9px] text-ink-ghost">[pov]</span>}
              </span>

              {/* Aliases */}
              {char.aliases.length > 0 && (
                <span className="text-[10px] font-mono text-ink-ghost truncate max-w-[120px]">
                  {char.aliases.join(', ')}
                </span>
              )}

              {/* Emotion hint */}
              {char.emotion_hint && (
                <span className="chip text-[9px]">{char.emotion_hint}</span>
              )}

              <div className="flex-1" />

              {/* Voice selector */}
              <select
                className="input w-40 py-1"
                value={char.voice_name ?? ''}
                onChange={e => handleAssignVoice(char, e.target.value)}
              >
                <option value="">— no voice —</option>
                {voices.map(v => (
                  <option key={v.id} value={v.name}>{v.name}</option>
                ))}
              </select>

              {/* Confirm */}
              {char.status === 'suggested' && (
                <button
                  className="btn text-[9px] px-2 py-1"
                  onClick={() => handleConfirmChar(char)}
                >
                  Cast
                </button>
              )}
            </div>
          ))}
        </div>
      </section>
    </div>
  )
}
