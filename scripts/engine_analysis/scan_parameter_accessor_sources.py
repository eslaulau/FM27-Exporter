#!/usr/bin/env python3
"""Locate writers/readers for the MATCH_PLAYER parameter vector and team coefficients.

This wraps the repository's PE/.pdata + Capstone field scanner. 0x4704100
uses a dynamic byte index at MATCH_PLAYER+0x480+parameter_id, while its
context modifiers read a compact coefficient block at TEAM+0x149E4..0x14A00.
"""
from __future__ import annotations

import scan_direction_generator_fields as direction_scan\n\nscanner = direction_scan.scanner

# Parameter IDs passed to 0x4704100 are byte indices into this contiguous array.
# Add every byte displacement because some initializers/copies use fixed offsets,
# while the accessor itself uses a dynamic index and exposes only the base disp.
for offset in range(0x480, 0x4C5):
    scanner.FIELD_LABELS[offset] = (
        f"MATCH_PLAYER_PARAMETER_VECTOR_BYTE_{offset - 0x480:02X}"
    )

# Integer coefficients read through MATCH_PLAYER's team/context pointer +0x280.
for offset in range(0x149E4, 0x14A01, 4):
    scanner.FIELD_LABELS[offset] = (
        f"TEAM_PARAMETER_MODIFIER_COEFFICIENT_{offset - 0x149E4:02X}"
    )

if __name__ == "__main__":
    scanner.main()
