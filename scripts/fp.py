#!/usr/bin/env python3
"""fp.py — deterministic helpers for: floor-plan image -> verified 2D overlay (stage 1) -> 3D model (stage 2).

Every number that ends up in a page passes through this file, so the same model.json always
produces the same pages. Run `python3 fp.py <command> -h` for options.

Probe commands (read the image; never used to set a WRITTEN dimension):
  info     image size + dominant colours (find the wall fill colour)
  walls    detect axis-aligned wall bands: centre, thickness, solid segments, gaps (openings)
  scan     solid/gap runs along one row or column
  bbox     bounding box of dark / coloured pixels in a region (furniture, fixtures)
  crop     enlarged crop with a pixel ruler, for looking at a detail
  fit      registration plan-cm -> px from wall centrelines + dimension-reference test
Model commands:
  check    run all consistency checks on model.json
  build1   stage-1 overlay page (image + SVG drawing + checks + open questions)
  approve  freeze the approved model (sha256 stored in model.json)
  build2   stage-2 Three.js page (refuses if model changed after approval)
  shoot    headless screenshot of a built page (needs playwright + chrome)
"""
import argparse, json, sys, math, hashlib, base64, copy, datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
ASSETS = HERE.parent / 'assets'
UNIT_CM = {'ft': 30.48, 'in': 2.54, 'm': 100.0, 'cm': 1.0, 'mm': 0.1}
THREE_VER = '0.160.0'
FIXTURE_TYPES = {'counter', 'stove', 'kitchen_sink', 'shower_tray', 'bathtub', 'toilet', 'vanity'}
TOL_CM = 0.5          # tolerance for geometric equality checks
MAX_RES_PX = 1.5      # registration residual above this is flagged


def die(msg):
    print('ERROR: ' + msg, file=sys.stderr)
    sys.exit(2)


def load_img(path):
    from PIL import Image
    import numpy as np
    im = Image.open(path).convert('RGB')
    return im, np.asarray(im).astype(int)


def parse_rgb(s):
    return tuple(int(v) for v in s.split(','))


def parse_box(s):
    v = [float(x) for x in s.split(',')]
    if len(v) != 4:
        die('box must be x1,y1,x2,y2')
    return [int(round(x)) for x in v]


def color_mask(arr, rgb, tol):
    import numpy as np
    r, g, b = rgb
    return (np.abs(arr[..., 0] - r) <= tol) & (np.abs(arr[..., 1] - g) <= tol) & (np.abs(arr[..., 2] - b) <= tol)


def runs(vec, val=True, offset=0):
    """[(start, end_inclusive)] of consecutive entries equal to val."""
    out, s = [], None
    for i, v in enumerate(vec):
        if bool(v) == val and s is None:
            s = i
        elif bool(v) != val and s is not None:
            out.append((s + offset, i - 1 + offset)); s = None
    if s is not None:
        out.append((s + offset, len(vec) - 1 + offset))
    return out


# ----------------------------------------------------------------------------- probe: info
def cmd_info(a):
    import numpy as np
    im, arr = load_img(a.image)
    q = (arr // 8) * 8 + 4
    flat = q.reshape(-1, 3)
    cols, counts = np.unique(flat, axis=0, return_counts=True)
    order = np.argsort(-counts)[:12]
    total = flat.shape[0]
    res = {'size': list(im.size), 'colours': []}
    for i in order:
        c = cols[i].tolist(); sat = max(c) - min(c); lum = sum(c) / 3
        res['colours'].append({'rgb': c, 'share': round(counts[i] / total, 4),
                               'grey': sat <= 16, 'lum': round(lum)})
    cand = [c for c in res['colours'] if c['grey'] and 40 <= c['lum'] <= 210 and c['share'] > 0.005]
    res['wall_colour_guess'] = None
    if cand:   # refine: median of all pixels near the guessed bin (bins split real colours)
        g = np.array(cand[0]['rgb'])
        near = arr.reshape(-1, 3)[(np.abs(arr.reshape(-1, 3) - g).max(1) <= 14)]
        res['wall_colour_guess'] = [int(v) for v in np.median(near, axis=0)]
    res['hint'] = ('Verify the guess: walls are usually the most common mid-grey/black fill. '
                   'Pass it to `walls --rgb R,G,B`.')
    print(json.dumps({'size': res['size'], 'wall_colour_guess': res['wall_colour_guess'], 'hint': res['hint']}))
    for c in res['colours']:
        print(f"  rgb={c['rgb']} share={c['share']:.3f} grey={c['grey']} lum={c['lum']}")


# ----------------------------------------------------------------------------- probe: walls
def inner_components_bbox(mask, min_px=150):
    """Union bbox of all wall-coloured blobs that do not touch the image border.
    Openings split a plan's walls into many blobs; frames/borders touch the edge and are skipped."""
    import numpy as np
    try:
        from scipy import ndimage
        lab, n = ndimage.label(mask)
        objs = ndimage.find_objects(lab); sizes = ndimage.sum(mask, lab, range(1, n + 1))
        boxes = []
        h, w = mask.shape
        for i, sl in enumerate(objs):
            y0, y1, x0, x1 = sl[0].start, sl[0].stop - 1, sl[1].start, sl[1].stop - 1
            if sizes[i] >= min_px and not (x0 == 0 or y0 == 0 or x1 == w - 1 or y1 == h - 1):
                boxes.append((x0, y0, x1, y1))
    except ImportError:
        from collections import deque
        h, w = mask.shape; seen = np.zeros_like(mask, dtype=bool); boxes = []
        for y0, x0 in zip(*np.nonzero(mask)):
            if seen[y0, x0]: continue
            dq = deque([(y0, x0)]); seen[y0, x0] = True; n = 0
            bx = [x0, y0, x0, y0]; border = False
            while dq:
                y, x = dq.popleft(); n += 1
                bx = [min(bx[0], x), min(bx[1], y), max(bx[2], x), max(bx[3], y)]
                if x in (0, w - 1) or y in (0, h - 1): border = True
                for dy, dx in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                    ny, nx = y + dy, x + dx
                    if 0 <= ny < h and 0 <= nx < w and mask[ny, nx] and not seen[ny, nx]:
                        seen[ny, nx] = True; dq.append((ny, nx))
            if n >= min_px and not border: boxes.append(tuple(bx))
    if not boxes: return None
    return [int(min(b[0] for b in boxes)), int(min(b[1] for b in boxes)), int(max(b[2] for b in boxes)), int(max(b[3] for b in boxes))]


def detect_lines(mask, orient, min_len, min_th, max_th):
    """Group long runs into wall bands. orient 'h' scans rows, 'v' scans columns."""
    import numpy as np
    m = mask if orient == 'h' else mask.T
    rows = []
    for i in range(m.shape[0]):
        rows.append([r for r in runs(m[i]) if r[1] - r[0] + 1 >= min_len])
    bands = []   # each: dict(i0,i1,segs(list of row segs))
    open_b = []
    for i, segs in enumerate(rows):
        nxt = []
        used = set()
        for b in open_b:
            ext = None
            for k, s in enumerate(segs):
                if k in used:
                    continue
                lo, hi = max(s[0], b['x0']), min(s[1], b['x1'])
                if hi - lo + 1 >= 0.5 * min(s[1] - s[0] + 1, b['x1'] - b['x0'] + 1):
                    ext = k; break
            if ext is None:
                bands.append(b)
            else:
                used.add(ext); s = segs[ext]
                b['i1'] = i; b['spans'].append(s)
                b['x0'] = int(np.median([p[0] for p in b['spans']])); b['x1'] = int(np.median([p[1] for p in b['spans']]))
                nxt.append(b)
        for k, s in enumerate(segs):
            if k not in used:
                nxt.append({'i0': i, 'i1': i, 'x0': s[0], 'x1': s[1], 'spans': [s]})
        open_b = nxt
    bands += open_b
    out = []
    for b in bands:
        th = b['i1'] - b['i0'] + 1
        if min_th <= th <= max_th:
            out.append({'i0': b['i0'], 'i1': b['i1'], 'x0': b['x0'], 'x1': b['x1']})
    # merge collinear bands (same rows +-1) into one line
    out.sort(key=lambda b: (b['i0'], b['x0']))
    lines = []
    for b in out:
        for L in lines:
            if abs(L['i0'] - b['i0']) <= 1 and abs(L['i1'] - b['i1']) <= 1:
                L['parts'].append(b); break
        else:
            lines.append({'i0': b['i0'], 'i1': b['i1'], 'parts': [b]})
    res = []
    H = m.shape[0]
    for L in lines:
        i0, i1 = L['i0'], L['i1']
        c = (i0 + i1) / 2
        ci = int(round(c))
        core = m[min(i0 + 1, ci):max(i1, ci + 1), :].all(axis=0)          # band rows filled
        out_a = m[i0 - 3, :] if i0 - 3 >= 0 else np.zeros(m.shape[1], bool)
        out_b = m[i1 + 3, :] if i1 + 3 < H else np.zeros(m.shape[1], bool)
        shaped = core & ~out_a & ~out_b                                   # looks like THIS wall, not a crossing one
        x0 = min(p['x0'] for p in L['parts']); x1 = max(p['x1'] for p in L['parts'])
        acc = []
        for r in runs(m[ci], True):
            if r[1] - r[0] < 1:
                continue
            if shaped[r[0]:r[1] + 1].sum() >= 3 or (r[0] <= x1 and r[1] >= x0):
                acc.append(r)
        if not acc:
            continue
        ext = [acc[0][0], acc[-1][1]]
        gaps = [(acc[k][1] + 1, acc[k + 1][0] - 1) for k in range(len(acc) - 1)]
        res.append({'orient': orient, 'band': [i0, i1], 'center_px': round(c, 1),
                    'thickness_px': i1 - i0 + 1, 'extent_px': ext,
                    'solid_px': [list(s) for s in acc], 'gaps_px': [list(g) for g in gaps if g[1] >= g[0]]})
    # drop thin duplicates that sit inside a thicker parallel band (edge artefacts)
    keep = []
    for L in res:
        inside = any(o is not L and o['band'][0] - 1 <= L['band'][0] and L['band'][1] <= o['band'][1] + 1
                     and o['thickness_px'] > L['thickness_px']
                     and not (L['extent_px'][1] < o['extent_px'][0] or L['extent_px'][0] > o['extent_px'][1]) for o in res)
        if not inside:
            keep.append(L)
    res = keep
    return res


def cmd_walls(a):
    im, arr = load_img(a.image)
    mask = color_mask(arr, parse_rgb(a.rgb), a.tol)
    if a.bbox:
        x1, y1, x2, y2 = parse_box(a.bbox)
    else:
        bb = inner_components_bbox(mask)
        if not bb:
            die('no wall-coloured blob found; check --rgb/--tol or pass --bbox')
        x1, y1, x2, y2 = bb
    sub = mask.copy(); sub[:y1, :] = False; sub[y2 + 1:, :] = False; sub[:, :x1] = False; sub[:, x2 + 1:] = False
    lines = detect_lines(sub, 'h', a.min_len, a.min_th, a.max_th) + detect_lines(sub, 'v', a.min_len, a.min_th, a.max_th)
    for k, L in enumerate(sorted(lines, key=lambda L: (L['orient'], L['center_px']))):
        L['id'] = ('H' if L['orient'] == 'h' else 'V') + str(k)
    lines.sort(key=lambda L: (L['orient'], L['center_px']))
    hs = [L for L in lines if L['orient'] == 'h']; vs = [L for L in lines if L['orient'] == 'v']
    for i, L in enumerate(hs): L['id'] = f'H{i+1}'
    for i, L in enumerate(vs): L['id'] = f'V{i+1}'
    out = {'bbox_px': [x1, y1, x2, y2], 'rgb': parse_rgb(a.rgb), 'tol': a.tol,
           'note': 'H lines: center_px is a y pixel, extents/solid/gaps are x pixels. V lines: the reverse. '
                   'Gaps are openings OR places where no wall exists; decide by looking.',
           'lines': lines}
    txt = json.dumps(out, indent=1)
    if a.out:
        Path(a.out).write_text(txt); print('wrote', a.out)
    # compact summary to stdout
    for L in lines:
        print(f"{L['id']:>4} {L['orient']} c={L['center_px']:7.1f} t={L['thickness_px']:2d}px "
              f"ext={L['extent_px']} gaps={L['gaps_px']}")


# ----------------------------------------------------------------------------- probe: scan / bbox / crop
def cmd_scan(a):
    im, arr = load_img(a.image)
    mask = color_mask(arr, parse_rgb(a.rgb), a.tol)
    if (a.row is None) == (a.col is None):
        die('give exactly one of --row / --col')
    vec = mask[a.row, :] if a.row is not None else mask[:, a.col]
    lo = a.start or 0; hi = a.end if a.end is not None else len(vec) - 1
    seg = vec[lo:hi + 1]
    print(json.dumps({'solid': runs(seg, True, lo), 'gaps': runs(seg, False, lo)}))


def cmd_bbox(a):
    import numpy as np
    im, arr = load_img(a.image)
    x1, y1, x2, y2 = parse_box(a.region)
    sub = arr[y1:y2 + 1, x1:x2 + 1]
    if a.mode == 'dark':
        m = (sub.sum(2) < a.dark) & ((sub.max(2) - sub.min(2)) < 40)
    elif a.mode == 'green':
        m = (sub[..., 1] > 110) & (sub[..., 1] > sub[..., 0] + 25) & (sub[..., 1] > sub[..., 2] + 25)
    else:
        m = color_mask(sub, parse_rgb(a.mode), a.tol)
    if a.components:   # list every separate outline in the region (furniture pieces drawn touching each other may merge)
        from scipy import ndimage
        lab, n = ndimage.label(m, structure=np.ones((3, 3)))
        comps = []
        for i, sl in enumerate(ndimage.find_objects(lab)):
            bb = [int(x1 + sl[1].start), int(y1 + sl[0].start), int(x1 + sl[1].stop - 1), int(y1 + sl[0].stop - 1)]
            if (bb[2] - bb[0]) >= a.min_size or (bb[3] - bb[1]) >= a.min_size: comps.append(bb)
        print(json.dumps({'components_px': sorted(comps)})); return
    ys, xs = np.nonzero(m)
    if not len(xs):
        print('null'); return
    bb = [int(x1 + xs.min()), int(y1 + ys.min()), int(x1 + xs.max()), int(y1 + ys.max())]
    # full-height / full-width interior lines help find headboards, backs, folds
    colfull = [int(x1 + i) for i in range(m.shape[1]) if m[:, i].sum() >= 0.8 * (bb[3] - bb[1] + 1)]
    rowfull = [int(y1 + i) for i in range(m.shape[0]) if m[i, :].sum() >= 0.8 * (bb[2] - bb[0] + 1)]
    edge = bb[0] == x1 or bb[1] == y1 or bb[2] == x2 or bb[3] == y2
    res = {'bbox_px': bb, 'full_cols': colfull, 'full_rows': rowfull}
    if edge: res['warning'] = 'bbox touches the region edge: probably a wall or neighbour got in — shrink/move the region or use --components'
    print(json.dumps(res))


def cmd_crop(a):
    from PIL import Image, ImageDraw
    im, _ = load_img(a.image)
    x1, y1, x2, y2 = parse_box(a.region); k = a.scale
    cr = im.crop((x1, y1, x2, y2)).resize((int((x2 - x1) * k), int((y2 - y1) * k)), Image.LANCZOS)
    d = ImageDraw.Draw(cr)
    for x in range((x1 // 10) * 10, x2, 10):
        X = (x - x1) * k
        if X < 0: continue
        d.line([(X, 0), (X, 18 if x % 50 == 0 else 7)], fill=(220, 0, 0))
        if x % 50 == 0: d.text((X + 2, 18), str(x), fill=(220, 0, 0))
    for y in range((y1 // 10) * 10, y2, 10):
        Y = (y - y1) * k
        if Y < 0: continue
        d.line([(0, Y), (18 if y % 50 == 0 else 7, Y)], fill=(0, 0, 220))
        if y % 50 == 0: d.text((20, Y - 5), str(y), fill=(0, 0, 220))
    cr.save(a.out); print('wrote', a.out, '(ruler: red = x px, blue = y px)')


# ----------------------------------------------------------------------------- probe: fit
def cmd_fit(a):
    """pairs.json: {"unit":"ft","walls":"walls.json","x":[[plan_coord, "V1" | px | [p0,p1]],...],"y":[...]}
    x pairs: vertical walls (their x position), y pairs: horizontal walls. Band ids/[p0,p1] enable the reference test."""
    import numpy as np
    P = json.loads(Path(a.pairs).read_text())
    u = UNIT_CM[P['unit']]
    lines = {}; thick = {}
    if P.get('walls'):   # allow line ids from `walls -o walls.json` instead of pixel numbers
        WL = json.loads(Path(P['walls']).read_text())['lines']
        lines = {L['id']: L['band'] for L in WL}; thick = {L['id']: L['thickness_px'] for L in WL}
    def norm(lst):
        out = []
        for c, p in lst:
            if isinstance(p, str):
                if p not in lines: die(f'line id {p} not found in {P.get("walls")}')
                p = lines[p]
            if isinstance(p, list):
                out.append((c * u, (p[0] + p[1]) / 2, p))
            else:
                out.append((c * u, float(p), None))
        return out
    X, Y = norm(P['x']), norm(P['y'])
    if len(X) < 2 or len(Y) < 2:
        die('need >=2 pairs per axis')
    A, b = [], []
    for c, p, _ in X: A.append([c, 1, 0]); b.append(p)
    for c, p, _ in Y: A.append([c, 0, 1]); b.append(p)
    A = np.array(A); b = np.array(b)
    sol = np.linalg.lstsq(A, b, rcond=None)[0]
    res = A @ sol - b
    s, ox, oy = sol
    # anisotropy: separate fits
    sx = np.polyfit([c for c, _, _ in X], [p for _, p, _ in X], 1)[0]
    sy = np.polyfit([c for c, _, _ in Y], [p for _, p, _ in Y], 1)[0]
    out = {'s': float(s), 'ox': float(ox), 'oy': float(oy), 'max_residual_px': float(abs(res).max()),
           'residuals_px': {'x': [round(float(r), 2) for r in res[:len(X)]], 'y': [round(float(r), 2) for r in res[len(X):]]},
           'sx': float(sx), 'sy': float(sy), 'anisotropy_pct': round(abs(sx - sy) / ((sx + sy) / 2) * 100, 2)}
    # dimension-reference test using the extreme bands (needs band pairs [p0,p1])
    ref = {}
    for axis, L in (('x', X), ('y', Y)):
        lo = min(L, key=lambda t: t[0]); hi = max(L, key=lambda t: t[0])
        span = hi[0] - lo[0]
        if lo[2] and hi[2] and span > 0:
            ref[axis] = {'center': (hi[1] - lo[1]) / span,
                         'outer_faces': (hi[2][1] + 1 - lo[2][0]) / span,
                         'inner_faces': (hi[2][0] - lo[2][1] - 1) / span}
    if 'x' in ref and 'y' in ref:
        out['reference_test'] = {k: {'sx': round(ref['x'][k], 4), 'sy': round(ref['y'][k], 4),
                                     'mismatch_pct': round(abs(ref['x'][k] - ref['y'][k]) / ref['x'][k] * 100, 2)}
                                 for k in ('center', 'outer_faces', 'inner_faces')}
        out['reference_hint'] = ('If the overall dimensions are measured to the reference with the smallest mismatch, '
                                 'x and y scales agree. Use it as evidence for meta.dim_reference, and still ask the user.')
    if thick:   # deterministic thickness estimate: median band thickness of outer (extreme) vs inner lines
        used = {'x': [p for _, p in P['x'] if isinstance(p, str)], 'y': [p for _, p in P['y'] if isinstance(p, str)]}
        outer, inner = [], []
        for ax in ('x', 'y'):
            ids = sorted(P[ax], key=lambda t: t[0]); ext = {ids[0][1], ids[-1][1]}
            for c, p in P[ax]:
                if isinstance(p, str): (outer if p in ext else inner).append(thick[p])
        half_up = lambda v: int(math.floor(v + 0.5))
        out['thickness_estimate_cm'] = {k: half_up(float(np.median(v)) / s) for k, v in (('out', outer), ('in', inner)) if v}
        out['thickness_note'] = 'median band thickness / s, rounded half-up. Use for model.thickness unless written numbers imply a value (derived).'
    out['ok'] = out['max_residual_px'] <= MAX_RES_PX
    print(json.dumps(out))
    if a.out:
        Path(a.out).write_text(json.dumps({k: out[k] for k in ('s', 'ox', 'oy', 'max_residual_px')}, indent=1))
        print('wrote', a.out)


# ----------------------------------------------------------------------------- model resolution
def vsub(p, q): return [p[0] - q[0], p[1] - q[1]]
def vdot(p, q): return p[0] * q[0] + p[1] * q[1]
def vlen(p): return math.hypot(p[0], p[1])


def seg_dist(p, a, b):
    ab = vsub(b, a); t = max(0, min(1, vdot(vsub(p, a), ab) / max(vdot(ab, ab), 1e-12)))
    q = [a[0] + ab[0] * t, a[1] + ab[1] * t]
    return vlen(vsub(p, q))


def poly_centroid(P):
    A = cx = cy = 0
    for i in range(len(P)):
        x0, y0 = P[i]; x1, y1 = P[(i + 1) % len(P)]
        c = x0 * y1 - x1 * y0; A += c; cx += (x0 + x1) * c; cy += (y0 + y1) * c
    A /= 2
    if abs(A) < 1e-9:
        return [sum(p[0] for p in P) / len(P), sum(p[1] for p in P) / len(P)], 0
    return [cx / (6 * A), cy / (6 * A)], abs(A)


def resolve(model):
    """Turn model.json (plan units + pixel estimates) into one resolved structure in cm.
    Both page templates read ONLY this structure, so they cannot disagree."""
    m = model
    unit = m['meta']['unit']
    if unit not in UNIT_CM: die(f'meta.unit must be one of {list(UNIT_CM)}')
    U = UNIT_CM[unit]
    reg = m.get('registration')
    if not reg: die('model.registration missing (run `fp.py fit`)')
    s, ox, oy = reg['s'], reg['ox'], reg['oy']
    px2 = lambda p: [(p[0] - ox) / s, (p[1] - oy) / s]
    pl = lambda p: [p[0] * U, p[1] * U]
    R = {'meta': m['meta'], 'unit_cm': U, 'reg': reg, 'walls': [], 'openings': [], 'dims': [], 'rooms': [],
         'items': [], 'flags': [], 'questions': m.get('questions', []), 'notes': m.get('notes', []),
         'heights': m.get('heights', {}), 'thickness': m['thickness']}
    th = m['thickness']
    W = {}
    for w in m['walls']:
        a, b = pl(w['a']), pl(w['b'])
        L = vlen(vsub(b, a))
        if L < 1e-6: die(f"wall {w['id']} has zero length")
        if 't_cm' in w:
            t, tst = w['t_cm'], w.get('t_status', 'estimate')
        else:
            t, tst = th[w['kind']]['cm'], th[w['kind']].get('status', 'estimate')
        rw = {'id': w['id'], 'kind': w['kind'], 'a': a, 'b': b, 'len': L, 't': t, 't_status': tst,
              'status': w.get('status', 'written'), 'desc': w.get('desc', '')}
        R['walls'].append(rw); W[w['id']] = rw
    rooms = {}
    for r in m.get('rooms', []):
        poly = [pl(p) for p in r['poly']]
        c, area = poly_centroid(poly)
        rr = {'id': r['id'], 'name': r.get('name', ''), 'label': r.get('label', ''), 'poly': poly,
              'centroid': c, 'area_m2': round(area / 1e4, 2), 'floor': r.get('floor', 'wood'),
              'lab': px2(r['label_px']) if r.get('label_px') else c, 'show_label': r.get('show_label', True)}
        if r.get('label2_px'): rr['lab2'] = px2(r['label2_px'])
        R['rooms'].append(rr); rooms[r['id']] = rr
    for o in m.get('openings', []):
        w = W.get(o['wall'])
        if not w: die(f"opening {o['id']}: unknown wall {o['wall']}")
        u = [(w['b'][0] - w['a'][0]) / w['len'], (w['b'][1] - w['a'][1]) / w['len']]
        if 'px' in o:
            dom = 0 if abs(u[0]) >= abs(u[1]) else 1
            def along(pv):
                cm_ = (pv - (ox if dom == 0 else oy)) / s
                return (cm_ - w['a'][dom]) / u[dom]
            f, t = sorted([along(o['px'][0]), along(o['px'][1] + 1)])   # +1: last solid-free pixel is inclusive
            f, t = round(f), round(t); st = o.get('status', 'estimate')
        elif 'plan' in o:
            f, t = o['plan'][0] * U, o['plan'][1] * U; st = o.get('status', 'written')
        elif 'cm' in o:
            f, t = o['cm']; st = o.get('status', 'written')
        else:
            die(f"opening {o['id']}: needs px, plan or cm")
        ro = {'id': o['id'], 'kind': o['kind'], 'wall': w['id'], 'from': f, 'to': t, 'width': round(t - f, 1),
              'status': st, 'desc': o.get('desc', ''), 'sill': o.get('sill_cm'), 'head': o.get('head_cm')}
        if o['kind'] in ('door', 'double_door'):
            target = o.get('swing_into')
            if target is None: die(f"door {o['id']}: swing_into (room id or [x,y] plan units) required")
            P = rooms[target]['centroid'] if isinstance(target, str) else pl(target)
            n = [-u[1], u[0]]
            side = vdot(n, vsub(P, w['a']))
            if abs(side) < 1e-6: die(f"door {o['id']}: swing_into point lies on the wall line")
            ro['side'] = 1 if side > 0 else -1
            ro['swing_into'] = target
            if o['kind'] == 'door':
                if o.get('hinge') not in ('a', 'b'): die(f"door {o['id']}: hinge must be 'a' or 'b'")
                ro['hinge'] = o['hinge']
        R['openings'].append(ro)
    for i, d in enumerate(m.get('dims', [])):
        rd = {'id': d.get('id', f'dim{i+1}'), 'label': d['label'], 'value': d['value'],
              'value_cm': d['value'] * U if d['value'] is not None else None, 'a': pl(d['a']), 'b': pl(d['b']),
              'lab': px2(d['label_px']), 'status': d.get('status', 'written'), 'note': d.get('note', ''),
              'faces': d.get('faces', 'reference')}
        if d.get('note_px'): rd['note_at'] = px2(d['note_px'])
        if rd['faces'] in ('outer', 'inner') and rd['value_cm']:
            # draw the dimension at its written length, centred on the centreline span (so it sits on the plan's line)
            L = vlen(vsub(rd['b'], rd['a'])); e = (rd['value_cm'] - L) / 2
            u = [(rd['b'][0] - rd['a'][0]) / L, (rd['b'][1] - rd['a'][1]) / L]
            rd['draw_a'] = [rd['a'][0] - u[0] * e, rd['a'][1] - u[1] * e]; rd['draw_b'] = [rd['b'][0] + u[0] * e, rd['b'][1] + u[1] * e]
        R['dims'].append(rd)
    for it in m.get('items', []):
        ri = {k: v for k, v in it.items() if k not in ('rect_px', 'poly_px', 'center_px', 'd_px')}
        ri.setdefault('status', 'estimate')
        ri.setdefault('cat', 'fixture' if it['type'] in FIXTURE_TYPES else 'furniture')
        if 'rect_px' in it:
            x1, y1, x2, y2 = it['rect_px']
            p1, p2 = px2([x1, y1]), px2([x2 + 1, y2 + 1])
            ri['rect'] = [round(p1[0], 1), round(p1[1], 1), round(p2[0], 1), round(p2[1], 1)]
        if 'poly_px' in it:
            ri['poly'] = [[round(v, 1) for v in px2(p)] for p in it['poly_px']]
        if 'center_px' in it:
            ri['center'] = [round(v, 1) for v in px2(it['center_px'])]
            ri['d'] = round(it.get('d_px', 40) / s, 1)
        if 'tv_px' in it:
            x1, y1, x2, y2 = it['tv_px']; p1, p2 = px2([x1, y1]), px2([x2 + 1, y2 + 1])
            ri['tv'] = [round(p1[0], 1), round(p1[1], 1), round(p2[0], 1), round(p2[1], 1)]; ri.pop('tv_px', None)
        if 'pillows_px' in it:
            ri['pillows'] = []
            for (x1, y1, x2, y2) in it['pillows_px']:
                p1, p2 = px2([x1, y1]), px2([x2 + 1, y2 + 1]); ri['pillows'].append([p1[0], p1[1], p2[0], p2[1]])
            ri.pop('pillows_px', None)
        R['items'].append(ri)
    for f in m.get('flags', []):
        rf = {'text': f['text'], 'at': px2(f['at_px'])}
        if f.get('box_px'):
            x1, y1, x2, y2 = f['box_px']; rf['box'] = px2([x1, y1]) + px2([x2, y2])
        R['flags'].append(rf)
    R['checks'] = run_checks(m, R)
    return R


# ----------------------------------------------------------------------------- checks
CHECK_TXT = {
    'he': {'uncertain': 'לא ודאי — לא משמש כמקור אמת', 'needs': 'דרוש אישור המשתמש', 'dim': 'מידה', 'to_faces': {'outer': 'עד הפנים החיצוניים', 'inner': 'עד הפנים הפנימיים'},
           'wall_implied': 'עובי קיר משתמע', 'estimate': 'הערכה', 'disagree_t': 'העובי המשתמע לא תואם להערכה', 'geo': 'גאומטריה', 'written': 'כתוב',
           'disagree': 'הגאומטריה והמידה הכתובה לא תואמות', 'dims_all': 'קווי המידה תואמים לגאומטריה', 'room': 'חדר', 'room_vs': 'תווית מול רשת המידות',
           'ends': 'כל קצה קיר נוגע בקיר אחר', 'free': 'קצוות חופשיים', 'none': 'אין', 'stub': 'קצה חופשי תקין רק בקיר-זיז; לאשר עם המשתמש',
           'loop': 'קירות החוץ יוצרים לולאה סגורה', 'outer_n': 'קירות חוץ', 'corners': 'פינות', 'open': 'הפתחים בתוך הקירות, בלי חפיפות',
           'reg': 'סטיית יישור השכבה', 'max': 'מקסימום', 'limit': 'גבול'},
    'en': {'uncertain': 'uncertain — not used as truth', 'needs': 'needs the user', 'dim': 'dim', 'to_faces': {'outer': 'to outer faces', 'inner': 'to inner faces'},
           'wall_implied': 'implied wall', 'estimate': 'estimate', 'disagree_t': 'implied thickness disagrees with the estimate', 'geo': 'geometry', 'written': 'written',
           'disagree': 'geometry and label disagree', 'dims_all': 'dimension lines match the centreline geometry', 'room': 'room', 'room_vs': 'label vs grid',
           'ends': 'every wall end meets another wall', 'free': 'free ends', 'none': 'none', 'stub': 'a free end is legal only for a stub wall; confirm with the user',
           'loop': 'outer walls form a closed loop', 'outer_n': 'outer walls', 'corners': 'corners', 'open': 'openings lie inside their walls, no overlaps',
           'reg': 'overlay registration residual', 'max': 'max', 'limit': 'limit'}}


def run_checks(m, R):
    C = []
    X = CHECK_TXT.get(m['meta'].get('lang', 'he'), CHECK_TXT['en'])
    def add(name, expr, ok, detail=''):
        C.append({'name': name, 'expr': expr, 'ok': bool(ok), 'detail': detail})
    U = R['unit_cm']; unit = m['meta']['unit']
    fmt = lambda v: (f'{v:g}' if abs(v - round(v)) > 1e-9 else str(int(round(v))))
    # declared chains (written dimensions)
    for ch in m.get('chains', []):
        tot = sum(ch['terms']); tol = ch.get('tol', 1e-6); eq = ch['equals']
        rhs = sum(eq) if isinstance(eq, list) else eq
        rtxt = (' + '.join(fmt(t) for t in eq) + f' = {fmt(rhs)}') if isinstance(eq, list) else fmt(eq)
        add(ch['name'], ' + '.join(fmt(t) for t in ch['terms']) + f' = {fmt(tot)}  ↔  {rtxt} ({unit})',
            abs(tot - rhs) <= tol, '' if abs(tot - rhs) <= tol else f'diff {fmt(tot - rhs)}')
    # each dimension vs. the geometry it is attached to
    tout = R['thickness'].get('out', {}).get('cm')
    n_ref = n_ok = 0
    for d in R['dims']:
        geo = vlen(vsub(d['b'], d['a']))
        if d['status'] == 'uncertain' or d['value_cm'] is None:
            add(f"{X['dim']} {d['id']} ({d['label']})", X['uncertain'], False, d['note'] or X['needs']); continue
        if d['faces'] in ('outer', 'inner'):
            # measured to the outer (or inner) faces: implied wall thickness = |written - centreline length|
            implied = (d['value_cm'] - geo) if d['faces'] == 'outer' else (geo - d['value_cm'])
            ok = tout is not None and abs(implied - tout) <= 3
            add(f"{X['dim']} {d['id']} ({d['label']}) {X['to_faces'][d['faces']]}", f"{d['value_cm']:.1f} − {geo:.1f} ⇒ {X['wall_implied']} {implied:.1f} cm ({X['estimate']} {tout})",
                ok, d['note'] or ('' if ok else X['disagree_t'])); continue
        n_ref += 1
        ok = abs(geo - d['value_cm']) <= TOL_CM; n_ok += ok
        if not ok:
            add(f"{X['dim']} {d['id']} ({d['label']})", f"{geo:.1f} cm {X['geo']} ↔ {d['value_cm']:.1f} cm {X['written']}", False,
                d['note'] or X['disagree'])
    add(X['dims_all'], f'{n_ok}/{n_ref}', n_ok == n_ref)
    # room label sizes vs polygon bbox
    for r, rr in zip(m.get('rooms', []), R['rooms']):
        if r.get('size'):
            xs = [p[0] for p in r['poly']]; ys = [p[1] for p in r['poly']]
            w, h = max(xs) - min(xs), max(ys) - min(ys)
            sw, sh = r['size']
            ok = (abs(w - sw) < 1e-6 and abs(h - sh) < 1e-6) or (abs(w - sh) < 1e-6 and abs(h - sw) < 1e-6)
            add(f"{X['room']} {r['id']} {X['room_vs']}", f"{fmt(w)}×{fmt(h)} ↔ {fmt(sw)}×{fmt(sh)} ({unit})", ok)
    # wall endpoints touch another wall
    free = []
    for w in R['walls']:
        for p in (w['a'], w['b']):
            if not any(o is not w and seg_dist(p, o['a'], o['b']) <= TOL_CM for o in R['walls']):
                free.append(w['id'])
    add(X['ends'], f"{X['free']}: " + (', '.join(free) or X['none']), not free, X['stub'] if free else '')
    # outer loop closure
    outs = [w for w in R['walls'] if w['kind'] == 'out']
    pts = []
    for w in outs:
        for p in (w['a'], w['b']):
            for q in pts:
                if vlen(vsub(p, q[0])) <= TOL_CM: q[1] += 1; break
            else:
                pts.append([p, 1])
    closed = bool(outs) and all(c == 2 for _, c in pts)
    add(X['loop'], f"{len(outs)} {X['outer_n']}, {len(pts)} {X['corners']}", closed)
    # openings inside their wall and not overlapping
    bad = []
    by_wall = {}
    for o in R['openings']:
        w = next(x for x in R['walls'] if x['id'] == o['wall'])
        if o['from'] < -TOL_CM or o['to'] > w['len'] + TOL_CM or o['to'] - o['from'] <= 0:
            bad.append(o['id'])
        by_wall.setdefault(o['wall'], []).append(o)
    for lst in by_wall.values():
        lst = sorted(lst, key=lambda o: o['from'])
        for p, q in zip(lst, lst[1:]):
            if q['from'] < p['to'] - TOL_CM: bad.append(f"{p['id']}/{q['id']}")
    add(X['open'], ', '.join(bad) or 'ok', not bad)
    # registration quality
    reg = m['registration']
    add(X['reg'], f"{X['max']} {reg.get('max_residual_px', float('nan')):.2f} px ({X['limit']} {MAX_RES_PX})",
        reg.get('max_residual_px', 99) <= MAX_RES_PX)
    return C


# ----------------------------------------------------------------------------- model commands
def load_model(p):
    try:
        return json.loads(Path(p).read_text())
    except json.JSONDecodeError as e:
        die(f'{p} is not valid JSON: {e}')


def model_hash(m):
    mm = copy.deepcopy(m); mm.pop('approval', None)
    return hashlib.sha256(json.dumps(mm, sort_keys=True, separators=(',', ':'), ensure_ascii=False).encode()).hexdigest()


def cmd_check(a):
    m = load_model(a.model); R = resolve(m)
    bad = [c for c in R['checks'] if not c['ok']]
    for c in R['checks']:
        print(('OK  ' if c['ok'] else 'FAIL') + f"  {c['name']}: {c['expr']}" + (f"  — {c['detail']}" if c['detail'] else ''))
    print(f"\n{len(R['walls'])} walls, {len(R['openings'])} openings, {len(R['dims'])} dims, "
          f"{len(R['rooms'])} rooms, {len(R['items'])} items, {len(R['flags'])} flags, {len(R['questions'])} questions")
    sys.exit(1 if bad and a.strict else 0)


def fill(template, **kw):
    t = (ASSETS / template).read_text()
    for k, v in kw.items():
        if k not in t: die(f'placeholder {k} missing in {template}')
        t = t.replace(k, v)
    return t


def jsdump(o):
    return json.dumps(o, ensure_ascii=False).replace('</', '<\\/')


def cmd_build1(a):
    m = load_model(a.model); R = resolve(m)
    img = Path(a.image)
    mime = 'image/png' if img.suffix.lower() == '.png' else 'image/jpeg'
    data = 'data:%s;base64,%s' % (mime, base64.b64encode(img.read_bytes()).decode())
    from PIL import Image
    w, h = Image.open(img).size
    html = fill('stage1.html', __DATA__=jsdump(R), __IMG__=data, __IMGW__=str(w), __IMGH__=str(h),
                __TITLE__=m['meta'].get('title', 'Stage 1'))
    Path(a.out).write_text(html); print('wrote', a.out)
    nf = sum(1 for c in R['checks'] if not c['ok'])
    print(f'checks: {len(R["checks"]) - nf} ok, {nf} failing; flags: {len(R["flags"])}; questions: {len(R["questions"])}')


def cmd_approve(a):
    m = load_model(a.model)
    m['approval'] = {'approved': True, 'sha256': model_hash(m),
                     'at': datetime.datetime.now().isoformat(timespec='seconds'), 'by': a.by}
    Path(a.model).write_text(json.dumps(m, indent=1, ensure_ascii=False)); print('approved; sha256', m['approval']['sha256'][:12])


def cmd_build2(a):
    m = load_model(a.model)
    ap = m.get('approval') or {}
    if not a.force:
        if not ap.get('approved'):
            die('model is not approved. Show stage 1, get the user\'s approval, then run `approve`.')
        if ap.get('sha256') != model_hash(m):
            die('model.json changed after approval. Rebuild stage 1, re-confirm with the user, run `approve` again.')
    H = m.get('heights') or {}
    need = ['ceiling', 'door_head', 'window_sill', 'window_head']
    miss = [k for k in need if not isinstance(H.get(k), (int, float))]
    if miss:
        die('heights missing: ' + ', '.join(miss) + '. Ask the user; if they do not answer, set the defaults '
            '(260/210/90/210) with heights.source.<key> = "default".')
    R = resolve(m)
    if a.three_local:
        base = str(Path(a.three_local).resolve())
        three, addons = base + '/build/three.module.js', base + '/examples/jsm/'
    else:
        three = f'https://cdn.jsdelivr.net/npm/three@{THREE_VER}/build/three.module.js'
        addons = f'https://cdn.jsdelivr.net/npm/three@{THREE_VER}/examples/jsm/'
    html = fill('stage2.html', __DATA__=jsdump(R), __THREE__=three, __ADDONS__=addons,
                __TITLE__=m['meta'].get('title', 'Stage 2'))
    Path(a.out).write_text(html); print('wrote', a.out)


def cmd_shoot(a):
    import http.server, threading, functools
    from playwright.sync_api import sync_playwright
    page = Path(a.page).resolve()
    class Quiet(http.server.SimpleHTTPRequestHandler):
        def log_message(self, *x): pass
    srv = http.server.ThreadingHTTPServer(('127.0.0.1', 0), functools.partial(Quiet, directory='/'))
    port = srv.server_address[1]
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    errs = []
    with sync_playwright() as p:
        chrome = next((c for c in ('/usr/bin/google-chrome', '/usr/bin/chromium', '/usr/bin/chromium-browser') if Path(c).exists()), None)
        b = p.chromium.launch(executable_path=chrome, args=['--use-gl=angle', '--use-angle=swiftshader', '--enable-unsafe-swiftshader'])
        pg = b.new_page(viewport={'width': a.width, 'height': a.height})
        pg.on('pageerror', lambda e: errs.append(str(e)))
        pg.on('console', lambda m: errs.append(m.text) if m.type == 'error' and 'favicon' not in m.text else None)
        pg.goto(f'http://127.0.0.1:{port}{page}'); pg.wait_for_timeout(1800)
        sh = pg.evaluate("document.getElementById('stage') ? document.getElementById('stage').scrollHeight : 0")
        if sh:   # stage-1 page: show the whole drawing (default: drawing only; --full: drawing + questions + tables)
            pg.evaluate("document.querySelector('.viewport').style.maxHeight='none'")
            if not a.full:
                pg.set_viewport_size({'width': a.width, 'height': int(sh) + 260}); pg.wait_for_timeout(300)
        for mode in a.modes.split(','):
            if mode:
                pg.evaluate(f"window.__fp && window.__fp.setMode('{mode}')"); pg.wait_for_timeout(700)
            out = a.out.replace('.png', f'_{mode}.png') if mode else a.out
            if a.full: pg.screenshot(path=out, full_page=True)
            else: pg.screenshot(path=out)
            print('wrote', out)
        b.close()
    srv.shutdown()
    print('page errors:', errs or 'none')


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sp = ap.add_subparsers(dest='cmd', required=True)
    p = sp.add_parser('info', help='image size, dominant colours, wall-colour guess'); p.add_argument('image'); p.set_defaults(f=cmd_info)
    p = sp.add_parser('walls', help='detect wall lines (H/V) with centre, thickness, gaps')
    p.add_argument('image'); p.add_argument('--rgb', required=True, help='wall fill colour R,G,B (from info)')
    p.add_argument('--tol', type=int, default=12, help='per-channel colour tolerance')
    p.add_argument('--bbox', help='x1,y1,x2,y2 search area; default = union of wall blobs not touching the image border')
    p.add_argument('--min-len', type=int, default=40, help='min run length (px) that seeds a wall line')
    p.add_argument('--min-th', type=int, default=3); p.add_argument('--max-th', type=int, default=45, help='wall thickness range (px)')
    p.add_argument('-o', '--out', help='write full JSON (needed by fit)'); p.set_defaults(f=cmd_walls)
    p = sp.add_parser('scan'); p.add_argument('image'); p.add_argument('--rgb', required=True); p.add_argument('--tol', type=int, default=12)
    p.add_argument('--row', type=int); p.add_argument('--col', type=int); p.add_argument('--start', type=int); p.add_argument('--end', type=int)
    p.set_defaults(f=cmd_scan)
    p = sp.add_parser('bbox', help='bbox of outline pixels in a region (furniture), or --components for each outline')
    p.add_argument('image'); p.add_argument('--region', required=True, help='x1,y1,x2,y2 — a few px larger than the object; keep wall bands and text OUT of it')
    p.add_argument('--mode', default='dark', help='dark | green | R,G,B'); p.add_argument('--tol', type=int, default=20)
    p.add_argument('--dark', type=int, default=300, help='sum(R,G,B) below this counts as dark')
    p.add_argument('--components', action='store_true', help='list separate outlines in the region')
    p.add_argument('--min-size', type=int, default=6); p.set_defaults(f=cmd_bbox)
    p = sp.add_parser('crop'); p.add_argument('image'); p.add_argument('--region', required=True)
    p.add_argument('--scale', type=float, default=3, help='enlargement factor (e.g. 2.5)'); p.add_argument('-o', '--out', required=True); p.set_defaults(f=cmd_crop)
    p = sp.add_parser('fit'); p.add_argument('pairs'); p.add_argument('-o', '--out'); p.set_defaults(f=cmd_fit)
    p = sp.add_parser('check'); p.add_argument('model'); p.add_argument('--strict', action='store_true'); p.set_defaults(f=cmd_check)
    p = sp.add_parser('build1'); p.add_argument('model'); p.add_argument('--image', required=True)
    p.add_argument('-o', '--out', required=True); p.set_defaults(f=cmd_build1)
    p = sp.add_parser('approve'); p.add_argument('model'); p.add_argument('--by', default='user'); p.set_defaults(f=cmd_approve)
    p = sp.add_parser('build2'); p.add_argument('model'); p.add_argument('-o', '--out', required=True)
    p.add_argument('--three-local', help='path to a local three@0.160.0 package (testing only)')
    p.add_argument('--force', action='store_true', help='skip the approval check (never for delivery)'); p.set_defaults(f=cmd_build2)
    p = sp.add_parser('shoot'); p.add_argument('page'); p.add_argument('-o', '--out', required=True)
    p.add_argument('--modes', default='', help='comma list: stage1 both,plan,src | stage2 orbit,top,walk')
    p.add_argument('--width', type=int, default=1500); p.add_argument('--height', type=int, default=900)
    p.add_argument('--full', action='store_true'); p.set_defaults(f=cmd_shoot)
    a = ap.parse_args(); a.f(a)


if __name__ == '__main__':
    main()
