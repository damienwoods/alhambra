import ruamel.yaml as yaml
from collections import Counter 
from .util import *
from . import tiletypes

class tileset_dict(dict):
    def __init__( self, val ):
        dict.__init__(self, val)
        if 'ends' in self.keys():
            self['ends'] = named_list(self['ends'])
        else:
            self['tiles'] = named_list()
        if 'tiles' in self.keys():
            self['tiles'] = named_list(self['tiles'])
        else:
            self['tiles'] = named_list()


    def check_consistent( self ):
        # * END LIST The end list itself must be consistent.
        # ** Each end must be of understood type
        # ** Each end must have a valid sequence or no sequence
        # ** There must be no more than one instance of each name
        # ** WARN if there are ends with no namecounts
        # * TILE LIST
        # ** each tile must be of understood type (must parse)
        for tile in self['tiles']:
            parsed = tiletypes.tfactory.parse( tile )
            # ** the tile type edotparen must be consistent, if it has one
            if parsed.edotparen:
                tiletypes.check_edotparen_consistency( parsed.edotparen )
            else:
                log.warning("tile type {} has no edotparen".format(tile['type']))
            # ** each tile must have no sequence, or a valid sequence
            if 'fullseqs' in tile.keys():
                parsed.check_sequence()
            # ** each tile must have the right number of ends
            if 'ends' in tile.keys():
                assert len(parsed._endtypes) == len(tile['ends'])
        # ** ends in the tile list must be consistent (must merge)
        endsfromtiles = tiletypes.endlist_from_tilelist(self['tiles']) 
        # ** there must be no more than one tile with each name
        self['tiles'].check_consistent()
        # ** WARN if any end that appears does not have a complement used or vice versa
        # ** WARN if there are tiles with no name
        # * TILE + END
        # ** The tile and end lists must merge validly (checks sequences, adjacents, types, complements)
        fullendlist = merge_endlists(self['ends'],endsfromtiles)
        
        # ** WARN if tilelist has end references not in ends
        # 
        # ** WARN if merge is not equal to the endlist
        # ** WARN if endlist has ends not used in tilelist
        # * ADAPTERS / SEEDS
        # ** seeds must be of understood type
        # ** adapter locations must be valid
        # ** each adapter must have no sequence or a consistent sequence
        # *** the RH strand must match the associated tile
        # *** the ends in the sequence must match the ends in the endlist
        # *** the LH sequence must be validly binding to both RH and origami
        # ** each adapter must have valid definition, which means for us:
        # *** if both tile mimic and ends are specified, they must match
        
    def summary( self ):
        pass
        

def load_tileset_dict( *args, **kwargs ):
    return tileset_dict( yaml.load( *args, **kwargs ) )
