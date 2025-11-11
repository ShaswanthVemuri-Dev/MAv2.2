
"""
icons_color_algorithm.py
------------------------
Algorithm to recolor icon SVGs based on AI outputs using a color manifest,
and optionally render PNGs (default 200x200).

Dependencies (runtime):
- Python 3.9+
- cairosvg (optional, only for PNG conversion)

Inputs:
- icons.sv.storage.py     (raw unchanged SVGs; exposes ICON_SVGS, get_icon)
- icons.color.manifest.json (color slots + defaults and map_by_color)

Only these slots are supported:
- background (applies default #B8B8B8; if manifest maps #009DFF -> #B8B8B8, we apply by default)
- ascent1 (main body/liquid color from AI)
- ascent2 (derived from ascent1 if relevant icon)
- cap (cap color for relevant icons)

We DO NOT touch strokes, size, or any other attributes.
"""

from __future__ import annotations
import json
import re
from dataclasses import dataclass
from typing import Dict, Optional, Any, List, Tuple
from pathlib import Path

# Optional dependency: cairosvg for PNG conversion
try:
    import cairosvg  # type: ignore
    _HAS_CAIROSVG = True
except Exception:  # pragma: no cover
    cairosvg = None
    _HAS_CAIROSVG = False


HEX_RE = re.compile(r'^#([0-9a-fA-F]{3}|[0-9a-fA-F]{6})$')

def normalize_hex(c: str) -> str:
    c = c.strip().lower()
    if HEX_RE.fullmatch(c):
        if len(c) == 4:  # #rgb → #rrggbb
            r, g, b = c[1], c[2], c[3]
            return f"#{r}{r}{g}{g}{b}{b}"
        return c
    return c  # leave non-hex as-is (e.g., rgb(...))

def clamp(v: int) -> int:
    return max(0, min(255, v))

def darken_hex(hex_color: str, pct: float = 0.15) -> str:
    """Darken a hex color by pct (0..1)."""
    h = normalize_hex(hex_color)
    if not HEX_RE.fullmatch(h):
        return h
    r = int(h[1:3], 16)
    g = int(h[3:5], 16)
    b = int(h[5:7], 16)
    r = clamp(int(r * (1 - pct)))
    g = clamp(int(g * (1 - pct)))
    b = clamp(int(b * (1 - pct)))
    return f"#{r:02x}{g:02x}{b:02x}"

# Fixed blacks that must never be changed
FIXED_BLACKS = {"#000000", "#111827", "#0b0b0b", "#0a0a0a"}

@dataclass
class ColorInputs:
    background: Optional[str] = None
    ascent1: Optional[str] = None
    ascent2: Optional[str] = None
    cap: Optional[str] = None

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "ColorInputs":
        return cls(
            background=d.get("background"),
            ascent1=d.get("ascent1"),
            ascent2=d.get("ascent2"),
            cap=d.get("cap"),
        )

def _load_storage(storage_path: Path):
    # Import the storage module dynamically
    import importlib.util, sys
    spec = importlib.util.spec_from_file_location("icons_svl_storage", str(storage_path))
    mod = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(mod)  # type: ignore
    return mod

def load_manifest(manifest_path: Path) -> Dict[str, Any]:
    with open(manifest_path, "r", encoding="utf-8") as f:
        return json.load(f)

def _replace_fill_all(svg: str, old: str, new: str) -> str:
    """Replace all occurrences of fill="old" with fill="new" (case-insensitive for color)."""
    if not old or old == new:
        return svg
    old_norm = normalize_hex(old)
    new_norm = normalize_hex(new)
    # Replace exact matches of fill="..."
    return re.sub(
        rf'fill="{re.escape(old_norm)}"',
        f'fill="{new_norm}"',
        svg
    )

def _derive_ascent2_from_ascent1(ascent1: str) -> str:
    """Project rule: if ascent1 is white -> D6D6D6; else darken by 15%."""
    a1 = normalize_hex(ascent1 or "")
    if a1 in ("#fff", "#ffffff"):
        return "#d6d6d6"
    return darken_hex(a1, pct=0.15)

def recolor_svg(
    icon_key: str,
    ai_colors: ColorInputs,
    storage_module,
    manifest: Dict[str, Any]
) -> str:
    """
    Apply the manifest rules and AI colors to produce a recolored SVG string.
    Only replaces allowed fills; does not alter strokes, strokeWidth, or size.
    """
    svg = storage_module.get_icon(icon_key)
    slots = {s["role"]: s for s in manifest["icons"][icon_key]["slots"]}

    # BACKGROUND
    bg_slot = slots.get("background")
    if bg_slot:
        bg_default = bg_slot["default_color"]
        # If AI provided a background, use it; else if apply_default_if_ai_missing, map old -> default
        bg_color_to_use = ai_colors.background or (bg_default if bg_slot.get("apply_default_if_ai_missing") else None)
        if bg_color_to_use:
            map_by = bg_slot.get("map_by_color")
            if map_by:
                svg = _replace_fill_all(svg, map_by, bg_color_to_use)

    # ASCENT1
    a1_slot = slots.get("ascent1")
    if a1_slot:
        a1_new = ai_colors.ascent1 or a1_slot["default_color"]
        old = a1_slot.get("map_by_color", a1_slot["default_color"])
        svg = _replace_fill_all(svg, old, a1_new)

    # ASCENT2
    a2_slot = slots.get("ascent2")
    if a2_slot:
        # If AI supplied ascent2 use it; else derive from ascent1 (which may be default if not supplied)
        if ai_colors.ascent2:
            a2_new = ai_colors.ascent2
        else:
            a1_effective = ai_colors.ascent1 or (a1_slot["default_color"] if a1_slot else a2_slot["default_color"])
            a2_new = _derive_ascent2_from_ascent1(a1_effective)
        old = a2_slot.get("map_by_color", a2_slot["default_color"])
        svg = _replace_fill_all(svg, old, a2_new)

    # CAP
    cap_slot = slots.get("cap")
    if cap_slot:
        cap_new = ai_colors.cap or cap_slot["default_color"]
        old = cap_slot.get("map_by_color", cap_slot["default_color"])
        svg = _replace_fill_all(svg, old, cap_new)

    return svg

def svg_to_png(svg: str, out_path: Path, size_px: int = 200) -> None:
    """
    Render SVG to PNG of size size_px x size_px. Requires cairosvg.
    If cairosvg is not available, raises RuntimeError.
    """
    if not _HAS_CAIROSVG:  # pragma: no cover
        raise RuntimeError("cairosvg is not installed. Install with `pip install cairosvg`.")
    cairosvg.svg2png(bytestring=svg.encode("utf-8"), write_to=str(out_path), output_width=size_px, output_height=size_px)

def process_request(
    icon_key: str,
    ai_input: Dict[str, Any],
    storage_path: Path,
    manifest_path: Path,
    png_out: Optional[Path] = None,
    png_size: int = 200
) -> Dict[str, Any]:
    """
    Process a single icon recolor request.
    ai_input keys can include: background, ascent1, ascent2, cap (all optional).
    Returns a dict with svg (string), and optionally png_path if rendered.
    """
    storage_module = _load_storage(storage_path)
    manifest = load_manifest(manifest_path)

    colors = ColorInputs.from_dict(ai_input)
    svg = recolor_svg(icon_key, colors, storage_module, manifest)
    result = {"icon": icon_key, "svg": svg}

    if png_out is not None:
        svg_to_png(svg, png_out, png_size)
        result["png_path"] = str(png_out)

    return result

def process_batch(
    requests: List[Tuple[str, Dict[str, Any]]],
    storage_path: Path,
    manifest_path: Path,
    out_dir: Optional[Path] = None,
    png_size: int = 200,
    parallel: bool = True,
    max_workers: Optional[int] = None
) -> List[Dict[str, Any]]:
    """
    Process a list of (icon_key, ai_input) requests.
    If out_dir is provided, PNGs will be written to that directory (one per icon).
    """
    from concurrent.futures import ThreadPoolExecutor, as_completed

    def _one(req: Tuple[str, Dict[str, Any]]) -> Dict[str, Any]:
        key, ai = req
        png_path = None
        if out_dir:
            out_dir.mkdir(parents=True, exist_ok=True)
            png_path = out_dir / f"{key}_{png_size}.png"
        return process_request(
            icon_key=key,
            ai_input=ai,
            storage_path=storage_path,
            manifest_path=manifest_path,
            png_out=png_path,
            png_size=png_size
        )

    if parallel and len(requests) > 1:
        results: List[Dict[str, Any]] = []
        with ThreadPoolExecutor(max_workers=max_workers) as ex:
            futs = [ex.submit(_one, r) for r in requests]
            for fut in as_completed(futs):
                results.append(fut.result())
        return results

    return [_one(r) for r in requests]
