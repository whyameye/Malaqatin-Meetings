#!/usr/bin/env python3
"""
Generate region data files from a rendered outline image.

The input is a grayscale PNG where white areas are "white" regions (gaps between
outlines) and black areas are "black" regions (filled shapes like decorative bands).
Thin lines between regions are boundaries.

Algorithm:
  1. White regions: threshold >= 128, connected component labeling, keep >= MIN_PIXELS
  2. Black regions: threshold < 128, erode 2px to find seeds, grow back via watershed
  3. Children: combined flood-fill containment + bounding-box containment ("relaxed")

Produces:
  - region_id_map.png    — R,G encode region ID, B=255 for region pixels, B=0 for boundaries
  - region_meta.json     — bbox, centroid, size, type for each region
  - region_overlay.png   — transparent PNG with random-colored regions
  - region_children.json — parent→children mapping

To create the input file from an SVG:
  inkscape outline.svg --export-filename outlines_render.png \\
    --export-width 2731 --export-height 2048 \\
    --export-background '#ffffff' --export-background-opacity 1.0

Usage:
  python3 generate_regions.py <rendered_outline.png> [--prefix PREFIX] [--outdir DIR]
  python3 generate_regions.py outlines_render.png
  python3 generate_regions.py outlines_render_scene2.png --prefix scene2_
"""

import argparse
import json
import sys
from pathlib import Path

import numpy as np
from PIL import Image
from scipy import ndimage
from scipy.ndimage import binary_erosion, watershed_ift


MIN_PIXELS = 50
PARENT_MIN_SIZE = 5000
CHILDREN_BBOX_MARGIN = 10
CHILDREN_SIZE_RATIO = 0.5
EROSION_ITERATIONS = 2
FLOOD_FILL_PAD = 5


def find_white_regions(arr):
    """Find white regions via connected component labeling."""
    print('Finding white regions...')
    white_binary = (arr >= 128).astype(np.int32)
    white_labeled, white_count = ndimage.label(white_binary)
    white_sizes = ndimage.sum(white_binary, white_labeled, range(1, white_count + 1))
    white_valid = [
        (i + 1, int(white_sizes[i]))
        for i in range(white_count)
        if white_sizes[i] >= MIN_PIXELS
    ]
    print(f'  Found {len(white_valid)} white regions (of {white_count} total, min {MIN_PIXELS}px)')
    return white_labeled, white_valid


def find_black_regions(arr):
    """Find black regions via erosion + watershed growth."""
    print('Finding black regions...')
    black = (arr < 128).astype(np.uint8)

    # Erode to find seed points (cores of each black shape)
    eroded = binary_erosion(black, iterations=EROSION_ITERATIONS)
    black_labeled_eroded, black_count = ndimage.label(eroded.astype(np.int32))
    black_sizes = ndimage.sum(eroded, black_labeled_eroded, range(1, black_count + 1))
    black_valid_ids = set(
        i + 1 for i, s in enumerate(black_sizes) if s >= MIN_PIXELS
    )
    print(f'  Found {len(black_valid_ids)} seed regions (of {black_count} total)')

    # Clean seed labels: remove small seeds
    seed_labels = black_labeled_eroded.copy()
    for i in range(1, black_count + 1):
        if i not in black_valid_ids:
            seed_labels[seed_labels == i] = 0

    # Grow seeds back to fill original black mask via watershed
    print('  Growing seeds via watershed...')
    black_mask = black.astype(bool)
    watershed_input = np.where(black_mask, np.uint8(0), np.uint8(255))
    grown_labels = watershed_ift(
        watershed_input.astype(np.uint16),
        seed_labels.astype(np.int32)
    )
    grown_labels[~black_mask] = 0

    # Validate grown regions
    final_black_valid = []
    for rid in black_valid_ids:
        mask_size = int((grown_labels == rid).sum())
        if mask_size >= MIN_PIXELS:
            final_black_valid.append((rid, mask_size))

    print(f'  Final black regions: {len(final_black_valid)}')
    return grown_labels, final_black_valid


def combine_regions(arr, white_labeled, white_valid, grown_labels, black_valid):
    """Combine white and black regions into a single map."""
    print('Combining regions...')
    h, w = arr.shape
    combined = np.zeros((h, w), dtype=np.int32)
    all_regions = []
    idx = 0

    # White regions first
    for r_id, r_size in white_valid:
        mask = white_labeled == r_id
        combined[mask] = idx + 1
        ys, xs = np.where(mask)
        all_regions.append({
            'idx': idx, 'type': 'white', 'size': r_size,
            'cx': int(xs.mean()), 'cy': int(ys.mean()),
            'bbox': [int(xs.min()), int(ys.min()), int(xs.max()), int(ys.max())]
        })
        idx += 1

    # Black regions
    for r_id, r_size in black_valid:
        mask = grown_labels == r_id
        combined[mask] = idx + 1
        ys, xs = np.where(mask)
        all_regions.append({
            'idx': idx, 'type': 'black', 'size': int(mask.sum()),
            'cx': int(xs.mean()), 'cy': int(ys.mean()),
            'bbox': [int(xs.min()), int(ys.min()), int(xs.max()), int(ys.max())]
        })
        idx += 1

    white_count = sum(1 for r in all_regions if r['type'] == 'white')
    black_count = sum(1 for r in all_regions if r['type'] == 'black')
    print(f'  Total: {len(all_regions)} regions (white={white_count}, black={black_count})')
    return combined, all_regions


def build_id_map(combined, all_regions):
    """Build the region ID map PNG."""
    print('Building ID map...')
    h, w = combined.shape
    id_map = np.zeros((h, w, 3), dtype=np.uint8)

    for i in range(len(all_regions)):
        mask = combined == (i + 1)
        id_map[mask, 0] = i & 0xFF          # R = low byte of ID
        id_map[mask, 1] = (i >> 8) & 0xFF   # G = high byte of ID
        id_map[mask, 2] = 255               # B = marker (255 = region pixel)

    return id_map


def build_overlay(combined, all_regions):
    """Build a transparent overlay PNG with random-colored regions."""
    print('Building overlay...')
    h, w = combined.shape
    np.random.seed(42)
    colors = np.random.randint(50, 255, size=(len(all_regions), 3), dtype=np.uint8)
    overlay = np.zeros((h, w, 4), dtype=np.uint8)

    for i in range(len(all_regions)):
        mask = combined == (i + 1)
        overlay[mask, 0] = colors[i, 0]
        overlay[mask, 1] = colors[i, 1]
        overlay[mask, 2] = colors[i, 2]
        overlay[mask, 3] = 128

    return overlay


def compute_children(meta, id_map):
    """
    Compute parent-child relationships using two combined methods:
    1. Flood-fill containment: treat parent pixels as walls, check if child is enclosed
    2. Bounding-box containment: child bbox fully inside parent bbox with margin

    This "relaxed" approach handles cases where parent boundaries have small gaps.
    """
    print('Computing parent-child relationships...')

    r_ch = id_map[:, :, 0].astype(np.int32)
    g_ch = id_map[:, :, 1].astype(np.int32)
    m_ch = id_map[:, :, 2]
    pixel_ids = np.where(m_ch >= 250, r_ch | (g_ch << 8), -1)
    h, w = pixel_ids.shape

    parent_candidates = [
        (int(k), v) for k, v in meta.items()
        if v['size'] >= PARENT_MIN_SIZE
    ]

    children = {}

    for pid, pmeta in parent_candidates:
        pbbox = pmeta['bbox']
        psize = pmeta['size']

        # Method 1: flood-fill containment
        pad = FLOOD_FILL_PAD
        x0 = max(0, pbbox[0] - pad)
        y0 = max(0, pbbox[1] - pad)
        x1 = min(w, pbbox[2] + pad + 1)
        y1 = min(h, pbbox[3] + pad + 1)

        crop = pixel_ids[y0:y1, x0:x1]
        wall = (crop == pid)
        passable = (~wall).astype(np.int32)
        labeled, num = ndimage.label(passable)

        # Find labels that touch the crop border (not enclosed)
        border_labels = set()
        border_labels.update(labeled[0, :].tolist())
        border_labels.update(labeled[-1, :].tolist())
        border_labels.update(labeled[:, 0].tolist())
        border_labels.update(labeled[:, -1].tolist())
        border_labels.discard(0)

        flood_children = set()
        for cid_str, cmeta in meta.items():
            cid = int(cid_str)
            if cid == pid or cmeta['size'] >= psize:
                continue
            cx, cy = cmeta['cx'], cmeta['cy']
            if cx < x0 or cx >= x1 or cy < y0 or cy >= y1:
                continue
            local_label = labeled[cy - y0, cx - x0]
            if local_label > 0 and local_label not in border_labels:
                flood_children.add(cid)

        # Method 2: bounding-box containment with margin
        margin = CHILDREN_BBOX_MARGIN
        bbox_children = set()
        for cid_str, cmeta in meta.items():
            cid = int(cid_str)
            if cid == pid or cmeta['size'] >= psize * CHILDREN_SIZE_RATIO:
                continue
            cb = cmeta['bbox']
            if (cb[0] >= pbbox[0] + margin and cb[1] >= pbbox[1] + margin and
                    cb[2] <= pbbox[2] - margin and cb[3] <= pbbox[3] - margin):
                bbox_children.add(cid)

        # Combine both methods
        all_kids = sorted(flood_children | bbox_children)
        if all_kids:
            children[str(pid)] = all_kids

    print(f'  Found {len(children)} parent regions')
    return children


def main():
    parser = argparse.ArgumentParser(
        description='Generate region data files from a rendered outline image'
    )
    parser.add_argument('input_image', help='Path to rendered outline PNG (grayscale)')
    parser.add_argument('--prefix', default='', help='Output filename prefix (e.g. "scene2_")')
    parser.add_argument('--outdir', default='.', help='Output directory (default: current)')
    args = parser.parse_args()

    input_path = Path(args.input_image)
    if not input_path.exists():
        print(f'Error: {input_path} not found', file=sys.stderr)
        sys.exit(1)

    outdir = Path(args.outdir)
    outdir.mkdir(parents=True, exist_ok=True)

    # Load rendered outlines as grayscale
    print(f'Loading {input_path}...')
    img = Image.open(input_path).convert('L')
    arr = np.array(img)
    print(f'Image size: {arr.shape[1]}x{arr.shape[0]}')

    # Step 1: Find white regions
    white_labeled, white_valid = find_white_regions(arr)

    # Step 2: Find black regions (erosion + watershed)
    grown_labels, black_valid = find_black_regions(arr)

    # Step 3: Combine into single region map
    combined, all_regions = combine_regions(arr, white_labeled, white_valid, grown_labels, black_valid)

    # Step 4: Build outputs
    id_map = build_id_map(combined, all_regions)
    overlay = build_overlay(combined, all_regions)

    meta = {str(r['idx']): r for r in all_regions}

    children = compute_children(meta, id_map)

    # Save outputs
    prefix = args.prefix

    id_map_path = outdir / f'{prefix}region_id_map.png'
    Image.fromarray(id_map, 'RGB').save(id_map_path)
    print(f'Saved {id_map_path}')

    meta_path = outdir / f'{prefix}region_meta.json'
    with open(meta_path, 'w') as f:
        json.dump(meta, f)
    print(f'Saved {meta_path}')

    overlay_path = outdir / f'{prefix}region_overlay.png'
    Image.fromarray(overlay, 'RGBA').save(overlay_path)
    print(f'Saved {overlay_path}')

    children_path = outdir / f'{prefix}region_children.json'
    with open(children_path, 'w') as f:
        json.dump(children, f, indent=2)
    print(f'Saved {children_path}')

    print(f'\nDone! Generated {len(all_regions)} regions.')


if __name__ == '__main__':
    main()
