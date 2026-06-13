import type { Project, Chapter, Character, Voice, PipelineStatus } from './types'

const BASE = '/api'

async function req<T>(
  path: string,
  options: RequestInit = {},
  expectStatus?: number
): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    headers: { 'Content-Type': 'application/json', ...options.headers },
    ...options,
  })
  if (expectStatus ? res.status !== expectStatus : !res.ok) {
    let msg = `HTTP ${res.status}`
    try { msg = ((await res.json()) as { detail?: string }).detail ?? msg } catch { /**/ }
    throw new Error(msg)
  }
  if (res.status === 204) return undefined as T
  return res.json() as Promise<T>
}

// ── Projects ────────────────────────────────────────────────────────────────

export const listProjects = (): Promise<Project[]> =>
  req<{ projects: Project[] }>('/projects').then(r => r.projects)

export const createProject = (epub: File): Promise<Project> => {
  const fd = new FormData()
  fd.append('epub', epub)
  return req<{ project: Project }>('/projects', { method: 'POST', headers: {}, body: fd }, 201)
    .then(r => r.project)
}

export const getProject = (id: number): Promise<Project> =>
  req<{ project: Project }>(`/projects/${id}`).then(r => r.project)

export const updateProfile = (
  id: number,
  data: Partial<Pick<Project, 'pov_style' | 'pov_characters'>>
): Promise<Project> =>
  req<{ project: Project }>(`/projects/${id}/profile`, {
    method: 'PATCH',
    body: JSON.stringify(data),
  }).then(r => r.project)

// ── Chapters ─────────────────────────────────────────────────────────────────

export const listChapters = (projectId: number): Promise<Chapter[]> =>
  req<{ chapters: Chapter[] }>(`/chapters/${projectId}`).then(r => r.chapters)

export const resetChapter = (chapterId: number): Promise<void> =>
  req(`/chapters/${chapterId}/reset`, { method: 'POST' })

export const deleteChapterAudio = (chapterId: number): Promise<void> =>
  req(`/chapters/${chapterId}/audio`, { method: 'DELETE' })

// ── Characters ───────────────────────────────────────────────────────────────

export const listCharacters = (projectId: number): Promise<Character[]> =>
  req<{ characters: Character[] }>(`/characters/${projectId}`).then(r => r.characters)

export const upsertCharacter = (
  projectId: number,
  data: { name: string; aliases?: string[]; emotion_hint?: string; is_pov?: boolean; status?: string }
): Promise<Character> =>
  req<{ character: Character }>(`/characters/${projectId}`, {
    method: 'POST',
    body: JSON.stringify(data),
  }, 201).then(r => r.character)

export const assignVoice = (
  _projectId: number,
  characterId: number,
  voiceName: string
): Promise<Character> =>
  req<{ character: Character }>(`/characters/${characterId}/voice`, {
    method: 'PATCH',
    body: JSON.stringify({ voice_name: voiceName }),
  }).then(r => r.character)

// ── Voices ───────────────────────────────────────────────────────────────────

export const listVoices = (): Promise<Voice[]> =>
  req<{ voices: Voice[] }>('/voices').then(r => r.voices)

export const uploadVoice = (name: string, file: File): Promise<Voice> => {
  const fd = new FormData()
  fd.append('name', name)
  fd.append('file', file)
  return req<{ voice_id: number; name: string; path: string }>(
    '/voices/upload', { method: 'POST', headers: {}, body: fd }, 201
  ).then(r => ({ id: r.voice_id, name: r.name, path: r.path, created_at: '' }))
}

export const deleteVoice = (voiceId: number): Promise<void> =>
  req(`/voices/${voiceId}`, { method: 'DELETE' })

// ── Pipeline ─────────────────────────────────────────────────────────────────

export const getPipelineStatus = (): Promise<PipelineStatus> =>
  req<PipelineStatus>('/pipeline/status')

export const startPipeline = (
  projectId: number,
  llmModelPath: string,
  ttsModelDir: string,
  chapterRange?: [number, number]
): Promise<void> =>
  req('/pipeline/start', {
    method: 'POST',
    body: JSON.stringify({
      project_id: projectId,
      llm_model_path: llmModelPath,
      tts_model_dir: ttsModelDir,
      chapter_range: chapterRange ?? null,
    }),
  })

export const pausePipeline = (): Promise<void> =>
  req('/pipeline/pause', { method: 'POST' })

export const resumePipeline = (): Promise<void> =>
  req('/pipeline/resume', { method: 'POST' })

export const stopPipeline = (): Promise<void> =>
  req('/pipeline/stop', { method: 'POST' })

// ── Export ────────────────────────────────────────────────────────────────────

export const exportM4B = (
  projectId: number,
  outputName?: string
): Promise<{ path: string }> =>
  req('/export/m4b', {
    method: 'POST',
    body: JSON.stringify({ project_id: projectId, output_filename: outputName ?? '' }),
  })

// ── Audio ─────────────────────────────────────────────────────────────────────

export const audioUrl = (chapterId: number): string => `${BASE}/audio/${chapterId}`
