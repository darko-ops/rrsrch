/**
 * Icons lucide-react doesn't have, drawn in its style (24-unit box, round 2px strokes, currentColor).
 */
import React from 'react';

/** A molecule: three atoms and their bonds. Explore's icon. */
export function Molecule({ size = 24, strokeWidth = 2, color = 'currentColor', ...rest }) {
  return (
    <svg xmlns="http://www.w3.org/2000/svg" width={size} height={size} viewBox="0 0 24 24" fill="none"
      stroke={color} strokeWidth={strokeWidth} strokeLinecap="round" strokeLinejoin="round" aria-hidden="true" {...rest}>
      <circle cx="6" cy="17" r="3" />
      <circle cx="18" cy="17" r="3" />
      <circle cx="12" cy="6" r="3" />
      <path d="M10.5 8.6 7.5 14.4" />
      <path d="M13.5 8.6l3 5.8" />
      <path d="M9 17h6" />
    </svg>
  );
}
