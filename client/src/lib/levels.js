import { CircleCheck, OctagonAlert, TriangleAlert } from 'lucide-react'

// The ONLY place risk levels are defined (NFR-06: colour + icon + text, never colour alone).
// Shapes differ too — circle, triangle, octagon — like traffic signs, so the levels
// stay distinct for colour-blind users and in greyscale.
export const LEVELS = {
  GREEN: {
    key: 'GREEN',
    color: '#2E7D32',
    soft: 'var(--color-level-green-soft)',
    text: '#FFFFFF',
    Icon: CircleCheck,
    rank: 0,
  },
  AMBER: {
    key: 'AMBER',
    color: '#F9A825',
    soft: 'var(--color-level-amber-soft)',
    text: '#18302E', // dark text on amber for WCAG AA contrast
    Icon: TriangleAlert,
    rank: 1,
  },
  RED: {
    key: 'RED',
    color: '#C62828',
    soft: 'var(--color-level-red-soft)',
    text: '#FFFFFF',
    Icon: OctagonAlert,
    rank: 2,
  },
}

// Legend order: Green → Amber → Red, top → bottom, like a traffic light read downward (spec §10.1 Mapping).
export const LEVEL_ORDER = ['GREEN', 'AMBER', 'RED']

export const NO_DATA = { key: 'NONE', color: '#8A9896', soft: '#ECEFEE', text: '#FFFFFF', Icon: null, rank: -1 }

export function level(key) {
  return LEVELS[key] || NO_DATA
}
