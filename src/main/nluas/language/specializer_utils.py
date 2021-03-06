"""
.. The SpecalizerTools module performs basic operations to gather information from a SemSpec
    and output an n-tuple.

.. moduleauthor:: Sean Trott <seantrott@icsi.berkeley.edu>


------
See LICENSE.txt for licensing information.
------

"""


from nluas.utils import update, Struct


def updated(d, *maps, **entries):
    """A "functional" version of update...
    """
    dd = dict(**d) if isinstance(d, dict) else Struct(d)
    return update(dd, *maps, **entries)

# This just defines the interface
class NullSpecializer(object):
    def specialize(self, fs):
        """Specialize fs into task-specific structures.
        """
        abstract  # @UndefinedVariable

class DebuggingSpecializer(NullSpecializer):
    def __init__(self):
        self.debug_mode = False

        # Original input sentence
        self._sentence = None

    """ Sets debug_mode to ON/OFF """
    def set_debug(self):
        self.debug_mode = not self.debug_mode


class ReferentResolutionException(Exception):
    def __init__(self, message):
        self.message = message


class FeatureStructException(Exception):
    def __init__(self, message):
        self.message = message

class MoodException(FeatureStructException):
    def __init__(self, message):
        self.message = message


class TemplateException(Exception):
    def __init__(self, message):
        self.message = message

class UtilitySpecializer(DebuggingSpecializer):
    def __init__(self, analyzer):
        self._stacked = []
        DebuggingSpecializer.__init__(self)
        self.analyzer = analyzer
        self.mappings = self.analyzer.get_mappings()
        self.event = True
        self.addressees = list() # For discourse analysis, distinct from _stacked list, which is used for general referent resolution



    def is_compatible(self, typesystem, role1, role2):
        return self.analyzer.issubtype(typesystem, role1, role2) or self.analyzer.issubtype(typesystem, role2, role1)

    """ Input PROCESS, searches SemSpec for Adverb Modifiers. Currently just returns speed,
    but could easily be modified to return general manner information. This might be made more complex
    if we wanted to describe more complex motor routines with adverbs. """
    def get_actionDescriptor(self, process):
        tempSpeed = .5
        returned=dict(speed=tempSpeed)
        if hasattr(process, "speed") and str(process.speed) != "None":
            tempSpeed = float(process.speed)
            returned['speed'] = float(process.speed)
        for i in process.__features__.values():
            for role, filler in i.__items__():
                if filler.typesystem() == 'SCHEMA' and self.analyzer.issubtype('SCHEMA', filler.type(), 'AdverbModification'):
                    if process.index() == filler.modifiedThing.index():
                        if (filler.value) and (filler.property.type() == "speed"):
                            newSpeed = float(filler.value)
                            if min(newSpeed, tempSpeed) < .5:
                                #return min(newSpeed, tempSpeed)
                                returned['speed'] = min(newSpeed, tempSpeed)
                            else:
                                returned['speed'] = max(newSpeed, tempSpeed)
                                #return max(newSpeed, tempSpeed)
                            #return float(filler.value)
                        elif (filler.value) and (filler.property.type() == "process_kind"):
                            returned['collaborative'] = filler.value.type()
                            #return filler.value.type()
                        else:
                            returned['collaborative'] = False
                            #return False
        return returned

    """ This returns a string of the specified relation of the landmark to the other RD, based on the values
    and mappings encoded in the SemSpec. This needs to be fixed substantially.
    """
    def get_locationDescriptor(self, goal):
        #location = {}
        location = ''
        for i in goal.__features__.values():
            for role, filler in i.__items__():
                if filler.type() == "Support":
                    if filler.supporter.index() == goal.index():
                        return "on"
                if filler.type() == 'Sidedness':
                    if filler.back.index() == goal.index():
                        return 'behind' #location = 'behind'
                elif filler.type() == 'BoundedObject':
                    if filler.interior.index() == goal.index():
                        if hasattr(i, "m") and i.m.type() == "TrajectorLandmark":
                            return "in"
                        elif hasattr(i, "m") and i.m.type() == "SPG":
                            return 'into'
                elif filler.type() == "NEAR_Locative":
                    if filler.p.proximalArea.index() == goal.index(): #i.m.profiledArea.index():
                        location = 'near'
                        #location['relation'] = 'near'
                elif filler.type() == "AT_Locative":
                    if filler.p.proximalArea.index() == goal.index():
                        location = 'at'
                        #location['relation'] = 'at'
        return location

    def invert_pointers(self, goal):
        final = {}
        for i in goal.__features__.values():
            for roles, filler in i.__items__():
                # Checks: filler is schema, it exists, and it has a temporalitly
                if filler.typesystem() == "SCHEMA" and filler.has_filler():
                    for k, v in filler.__items__():
                        if v.index() == goal.index():
                            if filler.type() not in final:
                                final[filler.type()] = []
                            final[filler.type()].append(filler)
        return final


    def get_processDescriptor(self, process, referent):
        """ Retrieves information about a process, according to existing templates. Meant to be implemented
        in specific extensions of this interface.

        Can be overwritten as needed -- here, it calls the params_for_compound to gather essentially an embedded n-tuple.
        """
        return list(self.params_for_compound(process))

    """ Meant to match 'one-anaphora' with the antecedent. As in, "move to the big red box, then move to another one". Or,
    'He likes the painting by Picasso, and I like the one by Dali.' Not yet entirely clear what information to encode
    besides object type. """
    def resolve_anaphoricOne(self, item):
        popper = list(self._stacked)
        while len(popper) > 0:
            ref = popper.pop()
            while ('location' in ref or 'locationDescriptor' in ref or 'referent' in ref['objectDescriptor']) and len(popper) > 0:
                ref = popper.pop()
            if item.givenness.type() == 'distinct':
                return {'objectDescriptor': {'type': ref['objectDescriptor']['type'], 'givenness': 'distinct'}}
            else:
                test = self.get_objectDescriptor(item, resolving=True)
                merged = self.merge_descriptors(ref['objectDescriptor'], test)
                return {'objectDescriptor': merged}
        raise ReferentResolutionException("Sorry, I don't know what you mean by 'one'.")


    def merge_descriptors(self, old, new):
        """ Merges object descriptors from OLD and NEW. Objective: move descriptions / properties from OLD
        into NEW unless NEW conflicts. If a property conflicts, then use the property in NEW. """
        if 'referent' in new and new['referent'] in ['anaphora', 'antecedent']:
            new.pop("referent")
        for key, value in old.items():
            if key == 'type':
                new[key] = old[key]
            if not key in new:
                new[key] = old[key]
        return new


    """ Simple reference resolution gadget, meant to unify object pronouns with potential
    antecedents. """
    def resolve_referents(self, item, antecedents = None, actionary=None, pred=None):
        #self.find_closest_antecedent([7,8])
        if antecedents is None:
            antecedents = self._stacked
        popper = list(antecedents)
        while len(popper) > 0:
            ref = popper.pop()
            if self.resolves(ref, actionary, pred) and self.compatible_referents(item, ref['objectDescriptor']):
                if 'partDescriptor' in ref:
                    return ref['partDescriptor']
                ref = self.clean_referent(ref)
                return ref
        return {'objectDescriptor':item}
        #raise ReferentResolutionException("Sorry, I did not find a suitable referent found in past descriptions.")

    def clean_referent(self, ref):
        ref['objectDescriptor'].pop('property', None)
        return ref

    def find_closest_antecedent(self, target):
        """ Takes in target span/word, ranks previous spans. """
        ranks = []
        for k in self.np_spans:
            #if self.analyzer.issubtype("CONSTRUCTION", k[0], "Pronoun"):
            span = k[2]
            if span[0] < target[0] and span[1] < target[1]:
                ranks.insert(0, k)
        #print(ranks)


    def ordering(self, fs, ref):
        for index, value in fs.rootconstituent.__features__.items():
            if hasattr(value, "m") and value.m and value.m.type() == "RD":
                print(index)
                #print(repr(value))
                print(value.m.ontological_category.type())
                #temp = self.get_objectDescriptor(value.m)
                #print(temp)

    def compatible_referents(self, pronoun, ref):
        for key, value in pronoun.items():
            if key in ref and key != "referent" and (value and ref[key]):
                if not self.is_compatible("ONTOLOGY", value, ref[key]):
                    return False
        return True

    """ Returns a boolean on whether or not the "popped" value works in the context provided. """
    def resolves(self, popped, actionary=None, pred=None):
        if actionary == 'be2' or actionary == 'be':
            if 'location' in popped or 'locationDescriptor' in popped:
                return 'relation' in pred
            else:
                if 'referent' in popped:
                    test = popped['referent'].replace('_', '-')
                    return self.analyzer.issubtype('ONTOLOGY', test, 'physicalEntity')
                else:
                    return self.analyzer.issubtype('ONTOLOGY', popped['objectDescriptor']['type'], 'physicalEntity')
        if actionary == 'forceapplication' or actionary == 'move':
            if 'location' in popped or 'locationDescriptor' in popped:
                return False
            if 'partDescriptor' in popped:
                pd = popped['partDescriptor']['objectDescriptor']
                if 'referent' in pd:
                    return self.analyzer.issubtype('ONTOLOGY', pd['referent'].replace('_', '-'), 'moveable')
                else:
                    return self.analyzer.issubtype('ONTOLOGY', pd['type'], 'moveable')
            else:
                if 'objectDescriptor' in popped and 'type' in popped['objectDescriptor']:
                    return self.analyzer.issubtype('ONTOLOGY', popped['objectDescriptor']['type'], 'moveable')
                return False
        # If no actionary passed in, no need to check for context
        return True

    def replace_mappings(self, ntuple):
        """ This is supposed to replace all of the mappings in the ntuple with values from the action ontology, if applicable. """
        n = ntuple
        if type(ntuple) == Struct:
            n = ntuple.__dict__
        for k,v in n.items():
            if type(v) == dict or type(v) == Struct:
                n[k]= self.replace_mappings(v)
            elif type(v) == list:
                for value in v:
                    value = self.replace_mappings(value)
            elif v is None:
                continue
            elif v in self.mappings:
                n[k] = self.mappings[v]
                v = self.mappings[v]
        return n

    def map_ontologies(self, ntuple):
        """ This is supposed to replace all of the mappings in the ntuple with values from the action ontology, if applicable. """
        n = ntuple
        for k, v in ntuple.items():
            if isinstance(v, dict):
                n[k] = self.map_ontologies(v)
            elif isinstance(v, list):
                for value in v:
                    value = self.map_ontologies(value)
            elif v is None:
                continue
            elif v in self.mappings:
                n[k] = self.mappings[v]
                v = self.mappings[v]
        return n
