import itertools
from .util import comp
import re
from .tiles import TileList
from .sensitivitynew import _fakesingles

_OE = [2, 3, 0, 1]
_ENDER = [3, 2, 1, 0]


def _generic_branch(direction, tiles, tile, n, f=False):
    # Generic branch finder.  MUST USE ALL SINGLES (EG, FAKESINGLE)
    branches = []
    if n == 0:
        return [([tile], tile['ends'][_ENDER[direction]])]
    for tn in tiles:
        if (tile['ends'][direction] == comp(tn['ends'][_OE[direction]])):
            branches += [
                ([tile] + x, y)
                for x, y in _generic_branch(direction, tiles, tn, n - 1)
            ]
    return branches


def _north_branch(ts, t, n, f=False):
    # North branch finder.  1/3 single-single, 1/5 single-hdouble,
    # 2/3 hdouble-single
    branches = []
    if re.match('(tile_daoe_5up|tile_daoe_3up)', t.structure.name):
        l = 1
        ne = 1
        if n == 0:
            return [([t], t['ends'][2])]
    elif re.match('tile_daoe_doublehoriz_35up', t.structure.name):
        l = 2
        ne = 2
        if n == 0:
            return [([t], t['ends'][3])]
        elif n == -1:
            return [([t], t['ends'][4])]
    elif f and re.match('tile_daoe_doublevert_35up', t.structure.name):
        l = 1
        ne = 1
    else:
        return []
    for tile in ts['tiles']:
        if re.match('(tile_daoe_5up|tile_daoe_3up)', tile.structure.name):
            if (t['ends'][ne] == comp(tile['ends'][3])):
                branches += [([t] + x, y)
                             for x, y in _north_branch(ts, tile, n - l)]
        if re.match('tile_daoe_doublehoriz_35up', tile.structure.name):
            if (t['ends'][ne] == comp(tile['ends'][5])):
                branches += [([t] + x, y)
                             for x, y in _north_branch(ts, tile, n - l - 1)]
    return branches


def _south_branch(ts, t, n, f=False):
    # South branch finder.
    branches = []
    if re.match('(tile_daoe_5up|tile_daoe_3up)', t.structure.name):
        l = 1
        se = 2
        if n == 0:
            return [([t], t['ends'][1])]
    elif re.match('tile_daoe_doublevert_35up', t.structure.name):
        l = 2
        se = 3
        if n == 0:
            return [([t], t['ends'][2])]
        elif n == -1:
            return [([t], t['ends'][1])]
    elif f and re.match('tile_daoe_doublehoriz_35up', t.structure.name):
        l = 1
        se = 4
    else:
        return []
    for tile in ts['tiles']:
        if re.match('(tile_daoe_5up|tile_daoe_3up)', tile.structure.name):
            if t['ends'][se] == comp(tile['ends'][0]):
                branches += [([t] + x, y)
                             for x, y in _south_branch(ts, tile, n - l)]
        if re.match('tile_daoe_doublevert_35up', tile.structure.name):
            if t['ends'][se] == comp(tile['ends'][0]):
                branches += [([t] + x, y)
                             for x, y in _south_branch(ts, tile, n - l - 1)]
    return branches


def _EWmatch(ese, ene, t):
    """For "southeast" and "northeast" facing ends (ne below se), and a tile, check
    whether the tile can attach."""
    return (ese == comp(t['ends'][0])) and (ene == comp(t['ends'][-1]))


def _latticedefect_tile(ts, tile, n=2):
    """With n tiles in each branch, can tile t form a lattice defect?"""
    n2 = _north_branch(ts, tile, n, f=True)
    s2 = _south_branch(ts, tile, n, f=True)
    neighborhoods = itertools.product(n2, s2)
    res = []
    for n in neighborhoods:
        res += [(n, tile) for tile in ts.tiles
                if _EWmatch(n[0][1], n[1][1], tile)]
    return res


def _latticedefect_tile_new(tiles, tile, direction='e', n=2):
    """With n tiles in each branch, can tile t form a lattice defect?"""
    d1, d2 = {'e': (1, 2), 'w': (0, 3), 'n': (0, 1), 's': (2, 3)}[direction]
    b1 = _generic_branch(d1, tiles, tile, n)
    b2 = _generic_branch(d2, tiles, tile, n)
    neighborhoods = itertools.product(b1, b2)
    res = []
    for n in neighborhoods:
        res += [(n, tile) for tile in tiles
                if ((n[0][1] == comp(tile['ends'][_OE[_ENDER[d1]]])) and (
                    n[1][1] == comp(tile['ends'][_OE[_ENDER[d2]]])))]
    return res


def _ppld(res):
    """pretty-print lattice defects, to some extent.  W is the initial tile, N/S are the
    north/south branches, and E is the tile that attaches to those branches."""
    return [
        "W:" + n[0][0][0]['name'] + " " + "N:[" + ",".join(
            t['name'] for t in n[0][0][1:]) + "] " + "S:[" + ",".join(
                t['name'] for t in n[1][0][1:]) + "] " + "E:" + tt['name']
        for n, tt in res
    ]


def latticedefects_new(ts, direction='e', depth=2, pp=True, rotate=False):
    if depth < 2:
        raise ValueError(
            "Depth cannot be less than 2, received {}.".format(depth))
    tiles = _fakesingles(ts.tiles)
    rtiles = _fakesingles(
        TileList([x for x in ts.tiles if 'fake' not in x.keys()]) + sum([
            x.rotations for x in ts.tiles if 'fake' not in x.keys()
        ], TileList()))
    if rotate:
        tll = rtiles
    else:
        tll = tiles
    alldefects = sum((_latticedefect_tile_new(
        tll, tile, direction=direction, n=depth) for tile in tll), [])
    if pp:
        return _ppld(alldefects)
    else:
        return alldefects


def latticedefects(ts, depth=2, pp=True):
    if depth < 2:
        raise ValueError(
            "Depth cannot be less than 2, received {}.".format(depth))
    alldefects = sum((_latticedefect_tile(ts, tile, depth)
                      for tile in ts.tiles), [])
    if pp:
        return _ppld(alldefects)
    else:
        return alldefects
