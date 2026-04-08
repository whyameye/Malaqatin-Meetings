#!/usr/bin/env python3
"""
Generate sweep path graph data for a region in Malaqatin-Meetings.

Extracts the skeleton of a region from the region ID map, builds a graph
of nodes (endpoints + branch points) and edges (path segments with radius
at each waypoint), and writes it as JSON for the sweep renderer.

Usage:
  python3 generate_sweep_path.py <region_id_map.png> <region_id> <output.json>
  python3 generate_sweep_path.py <region_id_map.png> <region_id> <output.json> --min-seg 20 --downsample 5

Options:
  --min-seg N     Prune segments shorter than N pixels (default: 15)
  --downsample N  Keep every Nth waypoint along segments (default: 4)
  --debug         Save debug images to /tmp/
"""

import numpy as np
from PIL import Image, ImageDraw
from scipy.ndimage import distance_transform_edt
from skimage.morphology import skeletonize
import json, sys, argparse, math


def decode_ids(arr):
    """Decode region ID map per perform.html: id = R|(G<<8) if B>=250 else -1"""
    R = arr[:, :, 0].astype(np.int32)
    G = arr[:, :, 1].astype(np.int32)
    B = arr[:, :, 2].astype(np.int32)
    return np.where(B >= 250, R | (G << 8), -1)


def build_skeleton_graph(skel, dist, min_seg, downsample):
    """
    Convert skeleton image to a graph of nodes and edges.

    Returns:
        nodes: list of {id, x, y, r, type}  (type: 'endpoint' or 'branch')
        edges: list of {id, from, to, points: [[x,y,r],...], length}
    """
    H, W = skel.shape
    ys, xs = np.where(skel)
    skel_set = set(zip(ys.tolist(), xs.tolist()))

    def neighbors8(y, x):
        for dy in (-1, 0, 1):
            for dx in (-1, 0, 1):
                if dy == 0 and dx == 0:
                    continue
                ny, nx = y + dy, x + dx
                if 0 <= ny < H and 0 <= nx < W and (ny, nx) in skel_set:
                    yield ny, nx

    # Classify each skeleton pixel by neighbor count
    nb_count = {}
    for (y, x) in skel_set:
        nb_count[(y, x)] = sum(1 for _ in neighbors8(y, x))

    # Nodes: pixels with neighbor count != 2 (endpoints=1, branches=3+, isolated=0)
    node_pts = {pt for pt, n in nb_count.items() if n != 2}

    # Assign node IDs
    node_id_map = {pt: i for i, pt in enumerate(sorted(node_pts))}
    nodes = []
    for pt, nid in node_id_map.items():
        y, x = pt
        r = float(dist[y, x])
        ntype = 'endpoint' if nb_count[pt] == 1 else 'branch'
        nodes.append({'id': nid, 'x': int(x), 'y': int(y), 'r': round(r, 1), 'type': ntype})

    # Extract edges: DFS from each node along each outgoing neighbor
    visited_half_edges = set()  # (node_pt, next_pt) already traversed
    edges = []

    for start_pt in node_pts:
        for nb_pt in neighbors8(*start_pt):
            if (start_pt, nb_pt) in visited_half_edges:
                continue

            # Walk along regular (non-node) pixels until hitting another node
            path = [start_pt]
            prev = start_pt
            cur = nb_pt

            while cur not in node_pts:
                path.append(cur)
                # Find the single unvisited neighbor (regular pixel has exactly 2 neighbors)
                moved = False
                for ny, nx in neighbors8(*cur):
                    if (ny, nx) != prev:
                        prev = cur
                        cur = (ny, nx)
                        moved = True
                        break
                if not moved:
                    break

            path.append(cur)
            end_pt = cur

            # Mark both directions visited
            visited_half_edges.add((start_pt, nb_pt))
            if len(path) >= 2:
                visited_half_edges.add((end_pt, path[-2]))

            # Compute segment length in pixels (Euclidean arc length)
            length = 0.0
            for i in range(1, len(path)):
                dy = path[i][0] - path[i-1][0]
                dx = path[i][1] - path[i-1][1]
                length += math.sqrt(dy*dy + dx*dx)

            if length < min_seg:
                continue  # prune tiny artifact segments

            # Downsample waypoints
            sampled = path[::downsample]
            if sampled[-1] != path[-1]:
                sampled.append(path[-1])

            # Build waypoint list [x, y, r]
            waypoints = [
                [int(p[1]), int(p[0]), round(float(dist[p[0], p[1]]), 1)]
                for p in sampled
            ]

            start_id = node_id_map.get(start_pt)
            end_id = node_id_map.get(end_pt)
            edges.append({
                'id': len(edges),
                'from': start_id,
                'to': end_id,
                'points': waypoints,
                'length': round(length, 1)
            })

    return nodes, edges


def save_debug(mask, skel, nodes, edges, out_path):
    H, W = mask.shape
    vis = np.zeros((H, W, 3), dtype=np.uint8)
    vis[mask] = [80, 40, 0]   # region: dark orange
    ys, xs = np.where(skel)
    vis[ys, xs] = [255, 200, 100]  # skeleton: bright yellow

    img = Image.fromarray(vis)
    draw = ImageDraw.Draw(img)

    # Draw edges
    for edge in edges:
        pts = edge['points']
        for i in range(1, len(pts)):
            draw.line([pts[i-1][0], pts[i-1][1], pts[i][0], pts[i][1]], fill=(200, 200, 255), width=1)

    # Draw nodes
    for node in nodes:
        x, y, r = node['x'], node['y'], int(node['r'])
        color = (255, 0, 0) if node['type'] == 'endpoint' else (0, 255, 0)
        draw.ellipse([x-4, y-4, x+4, y+4], fill=color)

    img.save(out_path)
    print(f'  Debug image: {out_path}')


def main():
    parser = argparse.ArgumentParser(description='Generate sweep path JSON for a region')
    parser.add_argument('id_map', help='Region ID map PNG')
    parser.add_argument('region_id', type=int, help='Region ID to process')
    parser.add_argument('output', help='Output JSON file')
    parser.add_argument('--min-seg', type=int, default=15,
                        help='Prune segments shorter than N pixels (default: 15)')
    parser.add_argument('--downsample', type=int, default=4,
                        help='Keep every Nth skeleton pixel as waypoint (default: 4)')
    parser.add_argument('--debug', action='store_true',
                        help='Save debug images to /tmp/')
    args = parser.parse_args()

    print(f'Loading {args.id_map}...')
    img = Image.open(args.id_map).convert('RGB')
    arr = np.array(img)
    H, W = arr.shape[:2]

    print(f'Decoding region IDs...')
    ids = decode_ids(arr)
    mask = (ids == args.region_id)
    if not mask.any():
        print(f'ERROR: Region {args.region_id} not found in {args.id_map}')
        sys.exit(1)
    print(f'  Region {args.region_id}: {mask.sum():,} pixels, bbox: {np.where(mask)[1].min()},{np.where(mask)[0].min()} - {np.where(mask)[1].max()},{np.where(mask)[0].max()}')

    print('Computing distance transform...')
    dist = distance_transform_edt(mask)
    print(f'  Max radius: {dist.max():.1f}px')

    print('Skeletonizing...')
    skel = skeletonize(mask)
    print(f'  Skeleton pixels: {skel.sum():,}')

    print('Building skeleton graph...')
    nodes, edges = build_skeleton_graph(skel, dist, args.min_seg, args.downsample)

    endpoints = [n for n in nodes if n['type'] == 'endpoint']
    branches = [n for n in nodes if n['type'] == 'branch']
    print(f'  Nodes: {len(nodes)} ({len(endpoints)} endpoints, {len(branches)} branch points)')
    print(f'  Edges: {len(edges)}')
    total_waypts = sum(len(e['points']) for e in edges)
    print(f'  Total waypoints: {total_waypts:,}')

    if args.debug:
        save_debug(mask, skel, nodes, edges, '/tmp/sweep_debug.png')

    output = {
        'mapW': W,
        'mapH': H,
        'regionId': args.region_id,
        'nodes': nodes,
        'edges': edges,
    }

    with open(args.output, 'w') as f:
        json.dump(output, f)

    import os
    size_kb = os.path.getsize(args.output) / 1024
    print(f'Written {args.output} ({size_kb:.1f} KB)')


if __name__ == '__main__':
    main()
