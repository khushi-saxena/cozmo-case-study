import numpy as np
from scipy import ndimage


def wall_grid(wall_xz_rect, grid_shape, origin, cell, min_support=4):
    """Rasterise wall points onto the floor grid."""
    g = np.floor(wall_xz_rect / cell).astype(int) - origin
    ok = ((g[:, 0] >= 0) & (g[:, 1] >= 0) &
          (g[:, 0] < grid_shape[0]) & (g[:, 1] < grid_shape[1]))
    cnt = np.zeros(grid_shape, int)
    np.add.at(cnt, (g[ok, 0], g[ok, 1]), 1)
    w = cnt >= min_support
    return ndimage.binary_dilation(w, iterations=1)


def segment_rooms(floor_grid, walls, cell, erode=1, min_room_m2=0.8):
    """Rooms are floor regions separated by walls.

    Eroding the floor alone does not work: a walk-in closet or a wide
    doorway is wider than the erosion ever gets before the room itself
    vanishes. Cutting the wall cells out first is what actually separates
    spaces, because walls are the thing that separates spaces."""
    free = floor_grid & ~walls
    core = ndimage.binary_erosion(free, iterations=erode) if erode else free
    lbl, n = ndimage.label(core)
    if n == 0:
        return np.where(floor_grid, 1, 0), 1

    sizes = ndimage.sum(core, lbl, range(1, n + 1))
    keep = [i + 1 for i, s in enumerate(sizes) if s * cell * cell >= min_room_m2]
    if not keep:
        return np.where(floor_grid, 1, 0), 1
    relabel = np.zeros(n + 1, int)
    for new, old in enumerate(keep, 1):
        relabel[old] = new
    lbl = relabel[lbl]

    # hand every floor cell, doorways included, to the nearest room core
    _, (iy, ix) = ndimage.distance_transform_edt(lbl == 0, return_indices=True)
    rooms = lbl[iy, ix]
    rooms[~floor_grid] = 0
    return rooms, len(keep)


def adjacency(rooms, cell, min_shared_m=0.4):
    pairs = {}
    H, W = rooms.shape
    for dy, dx in [(0, 1), (1, 0)]:
        a = rooms[:H - dy, :W - dx]
        b = rooms[dy:, dx:]
        m = (a != b) & (a > 0) & (b > 0)
        for ra, rb in zip(a[m], b[m]):
            key = (int(min(ra, rb)), int(max(ra, rb)))
            pairs[key] = pairs.get(key, 0) + 1
    return [{"room_a": f"room_{a}", "room_b": f"room_{b}",
             "shared_border_m": float(n * cell)}
            for (a, b), n in pairs.items() if n * cell >= min_shared_m]
