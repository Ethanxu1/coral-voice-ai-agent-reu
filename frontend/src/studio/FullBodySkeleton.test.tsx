import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'

import { FullBodySkeleton, UpperBodySkeleton } from './FullBodySkeleton'
import type { Landmark } from './types'

function fullBodyLandmarks(): Landmark[] {
  return Array.from({ length: 33 }, (_, index) => ({
    x: 0.2 + index * 0.015,
    y: 0.1 + index * 0.02,
    z: 0,
    visibility: 0.95,
  }))
}

describe('FullBodySkeleton', () => {
  it('renders torso and both legs', () => {
    render(<FullBodySkeleton landmarks={fullBodyLandmarks()} />)

    expect(screen.getByTestId('bone-left-hip-left-knee')).toBeInTheDocument()
    expect(screen.getByTestId('bone-left-knee-left-ankle')).toBeInTheDocument()
    expect(screen.getByTestId('bone-right-knee-right-ankle')).toBeInTheDocument()
  })

  it('omits non-finite bones instead of emitting unsafe SVG coordinates', () => {
    const landmarks = fullBodyLandmarks()
    landmarks[27].x = Number.NaN

    render(<FullBodySkeleton landmarks={landmarks} />)

    expect(screen.queryByTestId('bone-left-knee-left-ankle')).not.toBeInTheDocument()
  })

  it('renders only the head and arm chain in upper-body mode', () => {
    render(<UpperBodySkeleton landmarks={fullBodyLandmarks()} />)

    expect(screen.getByTestId('bone-left-upper-arm')).toBeInTheDocument()
    expect(screen.queryByTestId('bone-left-torso')).not.toBeInTheDocument()
    expect(screen.queryByTestId('bone-left-knee-left-ankle')).not.toBeInTheDocument()
  })
})
