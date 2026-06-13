import { render, screen, waitFor } from '@testing-library/react'
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { CastingStudio } from './CastingStudio'
import type { Character, Voice } from '@/lib/types'

// Mock the entire api module
vi.mock('@/lib/api', () => ({
  listCharacters: vi.fn(),
  listVoices: vi.fn(),
  uploadVoice: vi.fn(),
  deleteVoice: vi.fn(),
  assignVoice: vi.fn(),
  upsertCharacter: vi.fn(),
}))

// Mock the toast utility to avoid side effects
vi.mock('./Toasts', () => ({
  toast: vi.fn(),
}))

import {
  listCharacters,
  listVoices,
} from '@/lib/api'

const mockListCharacters = listCharacters as ReturnType<typeof vi.fn>
const mockListVoices = listVoices as ReturnType<typeof vi.fn>

const FAKE_CHARACTERS: Character[] = [
  {
    id: 1,
    project_id: 42,
    name: 'Sunny',
    aliases: ['Sunless King'],
    emotion_hint: 'calm',
    is_pov: true,
    status: 'cast',
    voice_id: undefined,
    voice_name: undefined,
  },
  {
    id: 2,
    project_id: 42,
    name: 'Teacher',
    aliases: [],
    emotion_hint: '',
    is_pov: false,
    status: 'suggested',
    voice_id: undefined,
    voice_name: undefined,
  },
]

const FAKE_VOICES: Voice[] = [
  { id: 10, name: 'DeepVoice', path: 'voices/deep.wav', created_at: '' },
  { id: 11, name: 'WarmNarrator', path: 'voices/warm.wav', tags: 'female', created_at: '' },
]

describe('CastingStudio', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    mockListCharacters.mockResolvedValue(FAKE_CHARACTERS)
    mockListVoices.mockResolvedValue(FAKE_VOICES)
  })

  it('renders character names after loading', async () => {
    render(<CastingStudio projectId={42} />)

    await waitFor(() => {
      expect(screen.getByText('Sunny')).toBeInTheDocument()
    })
    expect(screen.getByText('Teacher')).toBeInTheDocument()
  })

  it('calls listCharacters with the correct projectId on mount', async () => {
    render(<CastingStudio projectId={42} />)

    await waitFor(() => {
      expect(mockListCharacters).toHaveBeenCalledWith(42)
    })
    expect(mockListCharacters).toHaveBeenCalledTimes(1)
  })

  it('renders voice names from the voice library', async () => {
    render(<CastingStudio projectId={42} />)

    await waitFor(() => {
      expect(screen.getAllByText('DeepVoice').length).toBeGreaterThan(0)
    })
    expect(screen.getAllByText('WarmNarrator').length).toBeGreaterThan(0)
  })
})
