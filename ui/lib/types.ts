export type ProjectStatus = 'idle' | 'running' | 'paused' | 'complete' | 'error'
export type ChapterStatus = 'pending' | 'diarized' | 'tts_done' | 'assembled' | 'complete' | 'error'
export type CharacterStatus = 'suggested' | 'cast' | 'ignored'

export interface Project {
  id: number
  name: string
  source_epub: string
  total_chapters: number
  status: ProjectStatus
  pov_style?: string
  pov_characters?: string[]
  created_at: string
}

export interface Chapter {
  id: number
  project_id: number
  chapter_index: number
  title: string
  status: ChapterStatus
  error_message?: string
  line_count?: number
  audio_path?: string
  created_at: string
}

export interface Character {
  id: number
  project_id: number
  name: string
  aliases: string[]
  emotion_hint: string
  is_pov: boolean
  status: CharacterStatus
  voice_id?: number
  voice_name?: string
}

export interface Voice {
  id: number
  name: string
  path: string
  tags?: string
  created_at: string
}

export interface PipelineStatus {
  state: 'idle' | 'running' | 'paused' | 'stopping'
  project_id?: number
  last_event?: SSEEvent
}

export interface SSEEvent {
  type: string
  chapter_id?: number
  chapter_index?: number
  line_index?: number
  total_lines?: number
  stage?: string
  status?: string
  message?: string
  progress?: number
  ts?: number
}

export interface Toast {
  id: string
  variant: 'chrome' | 'warn' | 'crimson'
  message: string
  ttl?: number
}
