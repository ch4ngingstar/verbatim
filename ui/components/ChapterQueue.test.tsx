import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { ChapterQueue } from './ChapterQueue'
import type { Chapter } from '@/lib/types'
import type { PipelineState } from '@/hooks/usePipelineState'

vi.mock('@/lib/api', () => ({
  resetChapter: vi.fn(),
  deleteChapterAudio: vi.fn(),
  audioUrl: vi.fn((id: number) => `/api/audio/${id}`),
}))

vi.mock('./Toasts', () => ({
  toast: vi.fn(),
}))

import { resetChapter, deleteChapterAudio } from '@/lib/api'

const mockResetChapter = resetChapter as ReturnType<typeof vi.fn>
const mockDeleteChapterAudio = deleteChapterAudio as ReturnType<typeof vi.fn>

const IDLE_PIPE: PipelineState = {
  state: 'idle',
  projectId: null,
  activeChIdx: null,
  activeLine: null,
  totalLines: null,
  activeStage: null,
  chapters: [],
  lastEvent: null,
}

const makeChapter = (overrides: Partial<Chapter>): Chapter => ({
  id: 1,
  project_id: 10,
  chapter_index: 0,
  title: 'Prologue',
  status: 'pending',
  created_at: '',
  ...overrides,
})

describe('ChapterQueue', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('renders chapter items from props', () => {
    const chapters: Chapter[] = [
      makeChapter({ id: 1, chapter_index: 0, title: 'Prologue', status: 'pending' }),
      makeChapter({ id: 2, chapter_index: 1, title: 'The Beginning', status: 'complete' }),
    ]
    render(
      <ChapterQueue
        chapters={chapters}
        pipe={IDLE_PIPE}
        onChaptersChanged={vi.fn()}
      />
    )
    expect(screen.getByText('Prologue')).toBeInTheDocument()
    expect(screen.getByText('The Beginning')).toBeInTheDocument()
  })

  it('renders the correct status badge text for a chapter', () => {
    const chapters: Chapter[] = [
      makeChapter({ id: 1, chapter_index: 0, title: 'Chapter One', status: 'diarized' }),
      makeChapter({ id: 2, chapter_index: 1, title: 'Chapter Two', status: 'error' }),
    ]
    render(
      <ChapterQueue
        chapters={chapters}
        pipe={IDLE_PIPE}
        onChaptersChanged={vi.fn()}
      />
    )
    expect(screen.getByText('diarized')).toBeInTheDocument()
    expect(screen.getByText('error')).toBeInTheDocument()
  })

  it('calls resetChapter when reset button is clicked', async () => {
    mockResetChapter.mockResolvedValue(undefined)
    const onChaptersChanged = vi.fn()
    const chapters: Chapter[] = [
      makeChapter({ id: 5, chapter_index: 0, title: 'Error Chapter', status: 'error' }),
    ]
    render(
      <ChapterQueue
        chapters={chapters}
        pipe={IDLE_PIPE}
        onChaptersChanged={onChaptersChanged}
      />
    )

    const resetButton = screen.getByTitle('Reset to pending')
    fireEvent.click(resetButton)

    await waitFor(() => {
      expect(mockResetChapter).toHaveBeenCalledWith(5)
    })
    expect(onChaptersChanged).toHaveBeenCalled()
  })
})
