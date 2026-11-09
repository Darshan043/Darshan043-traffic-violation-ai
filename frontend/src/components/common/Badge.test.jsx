import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import Badge from './Badge.jsx'

describe('Badge result labels', () => {
  it.each([
    ['NO_HELMET', 'No helmet'],
    ['NO_SEATBELT', 'No seatbelt'],
    ['NEEDS_REVIEW', 'Needs review'],
    ['unclear', 'Needs review'],
    ['HELMET', 'Helmet compliant'],
    ['SEATBELT', 'Seatbelt compliant'],
    ['COMPLIANCE', 'Compliant'],
    ['confirmed', 'Confirmed'],
    ['rejected', 'Rejected'],
    ['not_required', 'No review needed'],
  ])('shows a text label for %s', (value, label) => {
    render(<Badge value={value} />)
    expect(screen.getByText(label)).toBeInTheDocument()
  })
})
