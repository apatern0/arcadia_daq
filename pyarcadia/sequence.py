import time
import math
import bisect
import threading
from tabulate import tabulate
"""
from tqdm import tqdm
print = tqdm.write
"""

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
        self.ts_sw = 0

        seq = self if parent is None else parent

        if packets is not None:
            for packet in packets:
                elaborated = packet.elaborate(seq)
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
        return len(self._queue) > 0 and isinstance(self._queue[-1], CustomWord)

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
                stop = lendata if i == threads-1 else (i+1)*per_thread
                workers.append(threading.Thread(name='Squasher%d' % i, target=worker, args=(data[start:stop], results[i])))
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
        if self.parent is not None and self.parent.autoread:
            elapsed = 0
            while True:
                if elapsed > self.parent.timeout:
                    raise RuntimeError("Pop timed out")

                self.parent.lock.acquire()
                if item >= len(self._queue):
                    self.parent.lock.release()
                    time.sleep(0.5)
                    elapsed += 0.5
                    continue

                tmp = self._queue[item]
                self.parent.lock.release()
                return tmp

        return self._queue[item]

    def pop(self, item=-1):
        """Pops an element from the queue, fetches more packets
        from the parent sequence if appropriate
        :param int item: Index of the element to pop
        :returns: The popped element
        :rtype: ChipData|TestPulse|CustomWord
        """

        if self.parent is not None and self.parent.autoread:
            elapsed = 0
            while True:
                if elapsed > self.parent.timeout:
                    raise RuntimeError("Pop timed out")

                self.parent.lock.acquire()
                if item >= len(self._queue):
                    self.parent.lock.release()
                    time.sleep(0.5)
                    elapsed += 0.5
                    continue

                tmp = self._queue.pop(item)
                self.parent.lock.release()
                return tmp

        return self._queue.pop(item)

    def filter_double_injections(self, us_on=10, fe_ntol=4, fe_ptol=4, tp_ntol=4, tp_ptol=1):
        """Filters spurious injections due to the falling edge of the
        Test Pulse coupling with the injection circuitry in the FEs.

        :param int t_off: Delta of the TP falling edge w.r.t. the rising
        """
        if self.parent is None:
            raise RuntimeError("The SubSequence doesn't have a valid parent Sequence. Unable to continue")

        if self.parent.chip is None:
            raise RuntimeError("The Sequence doesn't have a valid linked Chip. Unable to continue")

        # t_on is in FPGA CCs. Translate into timestamp counts
        ts_delta = int(us_on/self.parent.chip.ts_us)

        t0 = time.time()
        tps = [tp.ts_ext for tp in self.get_tps()]
        data = [data for data in self.get_data()]
        #print("Sorting took {}".format(time.time()-t0)); t0=time.time()

        # Parallel analysis
        def split_packets(data, data_ser):
            for packet in data:
                data_ser[packet.ser].append(packet)

        data_ser = [[] for i in range(16)]
        if len(data) > 1000:
            per_thread = 600
            workers = []
            threads = math.floor(len(data)/per_thread)

            for thread in range(threads):
                ub = min(((thread+1)*per_thread), len(data))
                t = threading.Thread(name='Splitter%d' % thread, target=split_packets, args=(data[thread*600:ub], data_ser, ))
                t.start()
                workers.append(t)

            for t in range(threads):
                workers[t].join()

        else:
            split_packets(data, data_ser)

        #print("Splitting took {}".format(time.time()-t0)); t0=time.time()

        # Parallel analysis
        def parse_packets(tps, data):
            parsed = []
            for packet in data:
                # Check whether it corresponds to a Test Pulse
                found_tp = bisect.bisect_left(tps, packet.ts_ext - 5 - tp_ntol)
                found_tp = found_tp != len(tps) and tps[found_tp] <= packet.ts_ext - 5 + tp_ptol

                # Check whether there is an already parsed packet which matches
                found_re = bisect.bisect_left(parsed, packet.ts_ext - ts_delta - fe_ntol)
                found_re = found_re != len(parsed) and parsed[found_re] <= packet.ts_ext - ts_delta + fe_ptol

                if not found_re and not found_tp:
                    packet.tag = 'isolated'

                elif found_re and not found_tp:
                    packet.tag = 'falling edge'

                elif not found_re and found_tp:
                    packet.tag = 'rising edge'
                    parsed.append(packet.ts_ext)

                elif found_re and found_tp:
                    packet.tag = 'ambiguous'
                    parsed.append(packet.ts_ext)

        for thread in range(16):
            threads = []

            t = threading.Thread(name='Parser%d' % thread, target=parse_packets, args=(tps, data_ser[thread]))
            t.start()
            threads.append(t)

        for t in threads:
            t.join()

        #print("Parsing took {}".format(time.time()-t0)); t0=time.time()

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
    tries = 5
    _queue = None
    _popped = None
    timeout = 15

    def __init__(self, packets=None, autoread=False, chip=None):
        self.autoread = autoread
        self.chip = chip
        self._queue = []
        self._popped = []

        self.lock = threading.Lock()
        self.autoread_thread = None
        if autoread:
            self.autoread_start()

        if packets is None:
            return

        self.elaborate_auto(packets)

    def __autoread(self):
        while self.autoread:
            packets = self.chip.readout()
            tmp = Sequence()
            tmp.elaborate_auto(packets)

            self.lock.acquire()
            self.extend(tmp)
            self.lock.release()
            time.sleep(1E-3)

    def autoread_start(self):
        self.autoread = True
        self.autoread_thread = threading.Thread(name='Autoreader', target=self.__autoread)
        self.autoread_thread.start()

    def elaborate_auto(self, packets):
        t0 = time.time()
        if len(packets) < 600:
            self.elaborate(packets)
        else:
            self.elaborate_parallel(packets)

        #print("Elaboration took {}".format(time.time()-t0)); t0=time.time()

    def elaborate_parallel(self, packets):
        per_thread = 500
        threads = math.ceil(len(packets)/per_thread)
        if threads > 8:
            threads = 8
            per_thread = math.ceil(len(packets)/8)

        workers = []
        sequences = [Sequence() for _ in range(threads)]
        for i in range(threads):
            stop = len(packets) if i == threads-1 else (i+1)*per_thread
            thread = threading.Thread(name='Elaborator%d' % i, target=sequences[i].elaborate, args=(packets[i*per_thread:stop], ))
            thread.start()
            workers.append(thread)

        for i in range(threads):
            workers[i].join(timeout=1)
            self.extend(sequences[i])

    def __getitem__(self, item):
        if self.autoread:
            elapsed = 0
            while True:
                if elapsed > self.timeout:
                    raise RuntimeError("Pop timed out")

                self.lock.acquire()
                if item >= len(self._queue) or not self._queue[item].is_complete():
                    self.lock.release()
                    time.sleep(0.5)
                    continue

                tmp = self._queue[item]
                self.lock.release()
                return tmp

        return self._queue[item]

    def __len__(self):
        return len(self._queue)

    def pop(self, item=-1, log=False):
        """Pops an element from the queue, fetches more packets
        if autoread is enabled
        :param int item: Index of the element to pop
        :param int tries: Max number of tries to reach subseq completeness
        :returns: The popped element
        :rtype: SubSequence
        """

        if self.autoread:
            elapsed = 0
            while True:
                if elapsed > self.timeout:
                    raise RuntimeError("Pop timed out")

                self.lock.acquire()
                if item >= len(self._queue) or not self._queue[item].is_complete():
                    self.lock.release()
                    time.sleep(0.5)
                    elapsed += 0.5
                    continue

                tmp = self._queue.pop(item)
                self.lock.release()

                if log:
                    self._popped.append(tmp)

                return tmp

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
                self._queue.append(SubSequence(parent=self))

            self._queue[-1].append(elaborated)

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

    def total_length(self):
        total = 0
        for i in self._queue:
            total += len(i)

        return total

    def extend(self, other):
        """Extend the current Sequence with another one"""

        # Trivial case
        if len(other._queue) == 0:
            return

        # Merge middle subsequences, if necessary
        if len(self._queue) > 0 and not self._queue[-1].is_complete():
            self._queue[-1].extend(other._queue.pop(0))

        # Timestamp adjustment
        for subsequence in other._queue:
            subsequence.parent = self

            for packet in subsequence._queue:
                if isinstance(packet, (TestPulse, ChipData)):
                    packet.ts_sw += self.ts_sw
                    packet.extend_timestamp()

        self.ts_sw += other.ts_sw

        if len(self._queue) == 0:
            self._queue = other._queue
        else:
            self._queue.extend(other._queue)

        """
        print("New sequence %s:" % self)
        for i in self._queue:
            print("--%s" % i)
            for j in i._queue:
                print("----%s" % j)
        """
