import re
import collections
import copy


REGEX_NOTE = re.compile("([a-gA-GRr])([b#]*)([0-9]*)([.]*)([',]*)")


### Parse a simple symbolic representation
###


def parse_accidental(acc):
    n = len(acc) if acc else 0
    return -n if "b" in acc else n


def parse_octave(string):
    """5 is central octave. Return 5 as a fall-back"""

    if string:
        size = string.count(string[0])
        return size + 4 if string[0] == "'" else -size + 5
    else:
        return 5


def parse_dur(dur, dots):
    value = 1.0 / int(dur) * 4
    return value + (value/2.0) if dots else value


def parse_note(note, volume=120, prev_octave=5, prev_dur=1):
    note_names = "c # d # e f # g # a # b".split()
    m = REGEX_NOTE.match(note)
    pitch, acc, dur, dots, octv = m.groups()

    octave = parse_octave(octv) if octv else prev_octave
    duration = parse_dur(dur, dots) if dur else prev_dur

    if pitch in ["r", "R"]:
        return Rest(duration)
    else:
        note_number = note_names.index(pitch.lower()) + parse_accidental(acc)
        return note_number, octave, duration, volume

    
def parse_notes(notes, volume=120):
    prev_octave = 5 # default octave
    prev_dur = 1    # default duration is 1/4, or 1 in the MIDI library

    result = []
    for item in notes:
        args = parse_note(item, volume, prev_octave, prev_dur)
        if isinstance(args, Rest):
            result.append(args)
            dur = args.dur
        else:
            number, octave, dur, vol = args
            result.append(Note(number, octave, dur, vol))
            prev_octave = octave
            
        prev_dur = dur

    return result


def parse_score(filename):
    with open(filename) as score:
        notes = []
        for line in score:
            notes.extend([note for note in line.split()])
        return parse_notes(notes)

    
class MusiclibError(Exception):
    pass


class Rest(object):
    def __init__(self, dur=1):
        self.dur = dur

    def __repr__(self):
        return "<Rest: {0}>".format(self.dur)

    def __eq__(self, other):
        return self.dur == other.dur

    def note_list(self):
        # return the same number of arguments as a note, so genmidi can unpack it
        return -1, 0, self.dur, 0

    def stretch_dur(self, factor):
        return Rest(self.dur * factor)


class Note(object):
    def __init__(self, value=0, octave=5, dur=1, volume=100):
        if isinstance(value, str):
            self.value, self.octave, self.dur, self.volume = parse_note(value)
        else:
            offset, val = divmod(value, 12)
            self.value = val
            self.octave = octave + offset
            self.dur = dur
            self.volume = volume

    def __eq__(self, other):
        return self.value == other.value and self.dur == other.dur and self.octave == other.octave

    def __sub__(self, other):
        return self.midi_number - other.midi_number

    def __repr__(self):
        return "<Note: {0}.{1}>".format(self.value, self.octave)

    @property
    def midi_number(self):
        return self.value + (self.octave * 12)

    def __note_octave(self, octave):
        """Return a note value in terms of a given octave octave

           n = Note(11, 4)
           __note_octave(n, 5) = -1
        """

        return self.value + ((self.octave - octave) * 12)

    def note_list(self):
        return self.value, self.octave, self.dur, self.volume

    def transposition(self, index):
        return Note(self.value + index, self.octave, self.dur, self.volume)

    def inversion(self, index=0, initial_octave=None):
        value = self.__note_octave(initial_octave) if initial_octave else self.value
        octv = initial_octave if initial_octave else self.octave
        note_value = (2 * index) - value
        return Note(note_value, octv, self.dur, self.volume)

    def stretch_dur(self, factor):
        return Note(self.value, self.octave, self.dur * factor, self.volume)


class NoteSeq(collections.MutableSequence):
    @staticmethod
    def _is_note_or_rest(args):
        return all([True if isinstance(x, Note) or isinstance(x, Rest) else False for x in args])
        
    def __init__(self, args=[]):
        if isinstance(args, str):
            self.items = parse_notes(args.split())
        elif isinstance(args, collections.Iterable):
            if self._is_note_or_rest(args):
                self.items = args
            else:
                raise MusiclibError("Every argument have to be a Note or a Rest.")
        else:
            raise MusiclibError("NoteSeq doesn't accept this type of data.")
            

    def __iter__(self):
        for x in self.items:
            yield x
    
    def __delitem__(self, i):
        del self.items[i]

    def __getitem__(self, i):
        if isinstance(i, int):
            return self.items[i]
        else:
            return NoteSeq(self.items[i])

    def __len__(self):
        return len(self.items)

    def __setitem__(self, i, value):
        self.items[i] = value

    def __repr__(self):
        return "<Seq: {0}>".format(self.items)

    def __eq__(self, other):
        if len(self) == len(other):
            return all(x == y for x, y in zip(self.items, other.items))

    def __add__(self, other):
        return NoteSeq(self.items + other.items)

    def __mul__(self, n):
        return NoteSeq(self.items * n)

    def note_list(self):
        return [x.note_list() for x in self.items]

    def retrograde(self):
        return NoteSeq(list(reversed(self.items)))

    def insert(self, i, value):
        self.items.insert(i, value)

    def transposition(self, index):
        return NoteSeq([x.transposition(index) if isinstance(x, Note) else x
                        for x in self.items])

    def _note_or_integer(self, item):
        return Note(item) if isinstance(item, int) else item

    def transposition_startswith(self, note_start):
        note = self._note_or_integer(note_start)
        return self.transposition(note - self.items[0])

    def inversion(self, index=0):
        initial_octave = self.items[0].octave
        return NoteSeq([x.inversion(index, initial_octave) if isinstance(x, Note)
                        else x for x in self.items])

    def inversion_startswith(self, note_start):
        note = self._note_or_integer(note_start)
        inv = self.transposition_startswith(Note(0, note.octave)).inversion()
        return inv.transposition_startswith(note)

    def rotate(self, n=1):
        modn = n % len(self)
        result = self.items[modn:] + self.items[0:modn]
        return NoteSeq(result)

    def stretch_dur(self, factor):
        return NoteSeq([x.stretch_dur(factor) for x in self.items])

    def intervals(self):
        v1 = [x.value for x in self]
        v2 = [x.value for x in self.rotate()]
        
        return [y - x for x, y in zip(v1, v2[:-1])]

    def stretch_inverval(self, factor):
        intervals = [x + factor for x in self.intervals()]
        note = copy.copy(self[0])
        result = NoteSeq([note])
        for i in intervals:
            note = note.transposition(i)
            result.append(note)
        return result

    # Aliases
    transp_startswith = transposition_startswith
    inv_startswith = inversion_startswith