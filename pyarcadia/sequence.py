import time
import math
from threading import Thread
from tabulate import tabulate

from .daq import Chip
from .data import ChipData, TestPulse, CustomWord

class SubSequence:
    """A SubSequence is a chain of data packets received from the FPGA
    containing either ChipData, TestPulse, or CustomWord types.

    Can be paired to a parent Sequence to allow for auto readout.

    :param FPGAData packets: Initialization packets from FPGA
    :param Sequence parent: Optional, parent Sequence
    """

    parent = None
    complete = False
    _queue = None

    def __init__(self, packets=None, parent=None):
        self._queue = []
        self.parent = parent

        if packets is not None:
            for packet in packets:
                elaborated = packet.elaborate()
                if elaborated is not None:
                    self.append(elaborated)

    def __len__(self):
        return len(self._queue)

    def get_data(self):
        """Returns the data packets in the SubSequence
        :returns: All the data packets
        :rtype: List[ChipData]
        """
        return [x for x in self._queue if isinstance(x, ChipData)]

    def get_tps(self):
        """Returns the test pulses in the SubSequence
        :returns: All the test pulses
        :rtype: List[TestPulse]
        """
        return [x for x in self._queue if isinstance(x, TestPulse)]

    def get_words(self):
        """Returns the custom words in the SubSequence
        :returns: All the Custom Words
        :rtype: List[CustomWord]
        """
        return [x for x in self._queue if isinstance(x, CustomWord)]

    def is_complete(self):
        """Returns True if the SubSequence is complete and terminated
        with a CustomWord, otherwise False
        :rtype: bool
        """
        return isinstance(self._queue[-1], CustomWord)

    def append(self, data):
        """Appends a new packet to the SubSequence
        :param ChipData|TestPulse|CustomWord data: packet to attach
        """
        self._queue.append(data)

    def extend(self, other):
        """Extends the current SubSequence with another one
        :param SubSequence other: SubSequence whose packets will be imported
        """
        self._queue.extend(other._queue)

    def squash_data(self, threads=None):
        """Merges packets from the same Master by OR-ing the pixels
        they contain.

        Doesn't currently support Smart Readout packets
        """

        # Worker
        def worker(data, results):
            # Elaborate
            new_data = []
            tmp = data[0]
            old_idx = data[0].master_idx()

            for i in data:
                this_idx = i.master_idx()

                if this_idx != old_idx:
                    tmp.bottom = 1
                    new_data.append(tmp)
                    tmp = i
                else:
                    tmp.hitmap |= i.hitmap

                old_idx = this_idx

            # Account for any last loner
            new_data.append(tmp)
            results.extend(new_data)

        # Initialize processing
        data = self.get_data()

        # Remove smart packets
        data = [x for x in data if x.bottom == 1 or (x.hitmap & 0xf) == 0]
        lendata = len(data)

        if lendata == 0:
            return []

        start_time = time.time()
        data.sort(key=lambda x: x.master_idx(), reverse=True)

        if threads is None:
            threads = max(1, min(8, int(lendata/2048)))

        per_thread = int(math.ceil(lendata/threads))

        if threads > 1:
            workers = []
            results = []
            for i in range(threads):
                results.append([])
                start = i*per_thread
                stop = lendata if i == threads-1 else (i+1)*per_thread-1
                workers.append(Thread(target=worker, args=(data[start:stop], results[i])))
                workers[i].start()

            for i in range(threads):
                workers[i].join()

            flat = [item for sublist in results for item in sublist]
        else:
            flat = data

        # Last mergeup
        flat_results = []
        worker(flat, flat_results)

        time_delta = time.time() - start_time
        #print("Squashed %d data to %d in %s us w/ %d threads" % (lendata, len(flat_results), time_delta*1E6, threads))

        return flat_results

    def __getitem__(self, item):
        try:
            return self._queue[item]
        except IndexError:
            if self.parent is not None and self.parent.autoread:
                self.parent.read_more()

            return self._queue[item]

    def pop(self, item=-1):
        """Pops an element from the queue, fetches more packets
        from the parent sequence if appropriate
        :param int item: Index of the element to pop
        :returns: The popped element
        :rtype: ChipData|TestPulse|CustomWord
        """
        try:
            return self._queue.pop(item)
        except IndexError:
            if self.parent is not None and self.parent.autoread:
                self.parent.read_more()

            return self._queue.pop(item)

    def dump(self, limit=0, start=0):
        """Prints a dump of the packets contained in the SubSequence.
        :param int limit: How many packets to show
        :param int start: Index of the first packet to show
        """
        i = 0
        toprint = []

        ts_base = None
        while limit == 0 or i < limit:
            try:
                item = self._queue[start+i]
            except IndexError:
                break

            if not hasattr(item, 'ts_ext'):
                time = 'nan'
            else:
                if ts_base is None:
                    time = 0
                    ts_base = item.ts_ext
                else:
                    time = item.ts_ext - ts_base

            toprint.append([i, time, str(item)])
            i += 1

        print("Dumping %s:" % self)
        print(tabulate(toprint, headers=["#", "Timestamp", "Item"]))


class Sequence:
    """A Sequence is a hierarchical structure which organizes the data
    coming from the FPGA by using CustomWords. It splits the packets
    received into SubSequences, creating a new one once a CustomWord
    is detected in the data stream.
    """
    chip: object = None
    ts_sw = 0
    autoread = False
    timeout = 50
    tries = 5
    _queue = None
    _popped = None

    def __init__(self, packets=None, autoread=False, chip=None, timeout=50):
        self.autoread = autoread
        self.chip = chip
        self.timeout = timeout
        self._queue = []
        self._popped = []

        if packets is not None:
            self.elaborate(packets)

    def __getitem__(self, item):
        try:
            return self._queue[item]
        except IndexError:
            if self.autoread:
                self.read_more()

            return self._queue[item]

    def __len__(self):
        return len(self._queue)

    def pop(self, item=-1, tries=10, log=False):
        """Pops an element from the queue, fetches more packets
        if autoread is enabled
        :param int item: Index of the element to pop
        :param int tries: Max number of tries to reach subseq completeness
        :returns: The popped element
        :rtype: SubSequence
        """
        if self.autoread:
            for _ in range(tries):
                if item >= len(self._queue):
                    self.read_more()
                    continue

                if not self._queue[item].is_complete():
                    try:
                        self.read_more()
                    except StopIteration:
                        continue

                break

        if log:
            self._popped.append(self._queue[item])

        return self._queue.pop(item)

    def elaborate(self, packets):
        """Elaborates new FPGA packets and inserts them in existing SubSequences
        :param FPGAData packets: The packets to process
        """
        for packet in packets:
            elaborated = packet.elaborate(self)

            if elaborated is None:
                continue

            if len(self._queue) == 0 or self._queue[-1].is_complete():
                self._queue.append(SubSequence())

            self._queue[-1].append(elaborated)

    def read_more(self):
        """Triggers a readout from the FPGA, and elaborates the data
        """
        if not isinstance(self.chip, Chip):
            raise RuntimeError("This sequence doesn't have a chip handle to use!")

        self.elaborate(self.chip.readout(timeout=self.timeout))

    def dump(self, limit=0, start=0):
        """Prints a dump of the packets contained in the SubSequence.
        :param int limit: How many packets to show
        :param int start: Index of the first packet to show
        """
        i = 0
        toprint = []

        while limit == 0 or i < limit:
            try:
                item = self._queue[start+i]
            except IndexError:
                break

            toprint.append([i, str(item)])
            i += 1

        print("Dumping %s:" % self)
        print(tabulate(toprint, headers=["#", "Item"]))

"""
    def analyze(self, pixels_cfg, printout=True, plot=False):
        tps = 0
        hitcount = 0

        hits = np.full((512, 512), np.nan)

        # Add received hits, keep track of tps
        for p in self._queue:
            if isinstance(p, TestPulse):
                tps += 1
                continue

            if not isinstance(p, ChipData):
                continue

            # Is ChipData
            pixels = p.get_pixels()
            for pix in pixels:
                if np.isnan(hits[pix.row][pix.col]):
                    hits[pix.row][pix.col] = 1
                else:
                    hits[pix.row][pix.col] += 1

                hitcount += 1

        # Now subtract from what's expected
        injectable = np.argwhere(pixels_cfg == 0b01)
        for (row, col) in injectable:
            if np.isnan(hits[row][col]):
                hits[row][col] = -1
            else:
                hits[row][col] -= tps

        # Report differences
        unexpected = np.argwhere(np.logical_and(~np.isnan(hits), hits != 0))

        toprint = []
        for (row, col) in unexpected:
            h = str(abs(hits[row][col])) + " (" + ("excess" if hits[row][col] > 0 else "missing") + ")"

            sec = Pixel.sec_from_col(col)
            dcol = Pixel.dcol_from_col(col)
            corepr = Pixel.corepr_from_row(row)
            master = Pixel.master_from_row(row)
            idx = Pixel.idx_from_pos(row, col)
            cfg = format(pixels_cfg[row][col], '#04b')

            toprint.append([sec, dcol, corepr, master, idx, row, col, h, cfg])

        if printout:
            print("Injectables: %d x %d TPs = %d -> Received: %d" % (len(injectable), tps, len(injectable)*tps, hitcount))
            print(tabulate(toprint, headers=["Sec", "DCol", "CorePr", "Master", "Idx", "Row", "Col", "Unexpected Balance", "Pixel Cfg"]))

        if plot:
            @customplot(('Row (#)', 'Col (#)'), 'Baseline distribution')
            def aplot(matrix, show=True, saveas=None, ax=None):
                cmap = matplotlib.cm.jet
                cmap.set_bad('gray',1.)
                image = ax.imshow(matrix, interpolation='none', cmap=cmap)

                for i in range(1,16):
                    plt.axvline(x=i*32-0.5,color='black')
                return image

            aplot(hits, show=True)

        return toprint
"""
