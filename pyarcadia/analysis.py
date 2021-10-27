import os
import numpy as np
import time
import math
import functools
import matplotlib
import matplotlib.cm
import matplotlib.pyplot as plt
from tabulate import tabulate
from dataclasses import dataclass
from typing import List

def customplot(axes, title):
    def decorator(f):
        @functools.wraps(f)
        def wrapper(*args, **kwargs):
            if 'show' in kwargs:
                show = kwargs['show']
            elif len(args) > 1:
                show = args[1]
            else:
                show = False

            if 'saveas' in kwargs:
                saveas = kwargs['saveas']
            elif len(args) > 2:
                saveas = args[2]
            else:
                saveas = None

            if(show == False and saveas == None):
                raise ValueError('Either show or save the plot!')

            fig, ax = plt.subplots()

            image = f(*args, **kwargs, ax=ax)

            ax.set(xlabel=axes[0], ylabel=axes[1], title=title)
            ax.margins(0)

            if isinstance(image, list):
                image = image.pop(0)

            if isinstance(image, matplotlib.lines.Line2D):
                ax.legend()
                ax.grid()
            elif isinstance(image, matplotlib.image.AxesImage):
                plt.colorbar(image, orientation='horizontal')

            if(saveas != None):
                fn = saveas+".pdf"
                if os.path.exists(fn):
                    i = 1
                    while True:
                        fn = saveas + ("_%d" % i) + ".pdf"
                        if not os.path.exists(fn):
                            break

                        i += 1

                fig.savefig(fn, bbox_inches='tight')

            if(show == True):
                matplotlib.interactive(True)
                plt.show()
            else:
                matplotlib.interactive(False)
                plt.close(fig)

        return wrapper
    return decorator

@dataclass
class FPGAData:
    """Raw data packet from the FPGA.

    :param int word: 64-bit word from the FPGA
    """
    word: int = None

    def __index__(self):
        return self.word

    def __format__(self, format_string):
        string = ""
        word = self.word
        for i in range(0, 64, 8):
            word = word >> i*8
            string += format((word & 0xff), format_string)

        return string

    def to_hex(self):
        """Returns an hexadecimal representation of the data

        :return: Hex data
        :rtype: string
        """
        string = ""
        for i in self.to_bytes():
            string = "{0:#0{1}x} ".format(i, 4)[2:] + string

        return string

    def to_bytes(self):
        """Splits the data to 8-bit chunks

        :return: List of bytes composing the data
        :rtype: list of ints
        """
        return [(self.word >> 8*x) & 0xff for x in range(8)]

    def elaborate(self, sequence=None):
        """Elaborates the data and returns the corresponding Packet. If it
        is a Timestamp Overflow packet, updates the sequence accordingly.

        :param Sequence sequence: Optional, the sequence the data belongs to
        :returns: Data Packet of the corresponding type
        :rtype: ChipData | TestPulse | CustomWord
        """
        self.word = int(self.word)

        ctrl = self.word >> ((8*7)+4)

        # FPGA timestamp overflow
        if ctrl == 0xf:
            if sequence is not None:
                sequence.ts_sw += 1

            return None

        # Test pulse
        if ctrl == 0xa:
            return TestPulse(self)

        # Custom Word
        if ctrl == 0xc:
            return CustomWord(self)

        # Chip data
        return ChipData(self, sequence)

    @staticmethod
    def from_packets(packets):
        return [FPGAData(x) for x in packets]

@dataclass
class Pixel:
    """Represents a Pixel in the Matrix

    :param int row: Pixel row
    :param int col: Pixel col
    """

    row: int
    col: int

    def get_sec(self):
        """Returns the section the pixel belongs to

        :return: The pixel's Section
        :rtype: int
        """
        return Pixel.sec_from_col(self.col)

    def get_dcol(self):
        """Returns the double column the pixel belongs to

        :return: The pixel's Double Column
        :rtype: int
        """
        return Pixel.dcol_from_col(self.col)

    def get_corepr(self):
        """Returns the Pixel Region the pixel belongs to. This incremental
        number starts from the bottom, and takes into account the Core address
        as well.

        :return: The pixel's Pixel Region
        :rtype: int
        """
        return Pixel.corepr_from_row(self.row)

    def get_master(self):
        """Returns 0 if the pixel belogs to a Slave sub-PR or 1 if it
        belongs to a master sub-PR.

        :return: 1 if Master, 0 if Slave
        :rtype: int
        """
        return Pixel.master_from_row(self.row)

    def get_idx(self):
        """Returns the pixel index in the sub-PR

        :return: The pixel's index
        :rtype: int
        """
        return Pixel.idx_from_pos(self.row, self.col)

    def __str__(self):
        return "Pixel @ [%3d][%3d] SEC %d DCOL %d COREPR %d" % (self.row, self.col, self.get_sec(), self.get_dcol(), self.get_corepr())

    @staticmethod
    def sec_from_col(col):
        """Evaluates the Section from a pixel's X-coordinate

        :param int col: Pixel's column number
        :returns: Section index
        :rtype: int
        """
        return col >> 5

    @staticmethod
    def dcol_from_col(col):
        """Evaluates the Double Column index, in a Section, from a pixel's X-coordinate

        :param int col: Pixel's column number
        :returns: Double Column index
        :rtype: int
        """
        return (col >> 1) & 0xf

    @staticmethod
    def corepr_from_row(row):
        """Evaluates the Pixel Region index from a pixel's Y-coordinate

        :param int row: Pixel's row number
        :returns: Pixel Region index
        :rtype: int
        """
        return row >> 2

    @staticmethod
    def master_from_row(row):
        """Evaluates whether the pixel belongs to a Master or Slave sub-PR

        :param int row: Pixel's row number
        :returns: 1 if Master, 0 if Slave
        :rtype: int
        """
        return (row >> 1) & 0x1

    @staticmethod
    def idx_from_pos(row, col):
        """Evaluates the pixel's index within the sub-PR

        :param int row: Pixel's row number
        :param int col: Pixel's column number
        :returns: Pixel's index within the sub-PR
        :rtype: int
        """
        return (row & 0x1)*2 + (col & 0x1)

@dataclass
class ChipData:
    """Represents a Data Packet received from the FPGA

    :param FPGAData fpga_packet: Data packet received from the FPGA
    :param Sequence sequence: Optional, sequence the data belongs to
    """

    fpga_packet: FPGAData
    sequence: object = None

    def __post_init__(self):
        if self.sequence is None:
            self.ts_sw = 0
        else:
            self.ts_sw = self.sequence.ts

        if self.fpga_packet is None:
            self.bottom  = None
            self.hitmap  = None
            self.corepr  = None
            self.col     = None
            self.sec     = None
            self.ts      = None
            self.ts_fpga = None
            self.ser     = None
            return

        packet_bytes = self.fpga_packet.to_bytes()

        self.bottom  = (packet_bytes[0] >> 0) & 0x01
        self.hitmap  = (((packet_bytes[1] >> 0) & 0x01) << 7) | ((packet_bytes[0] >> 1) & 0x7F)
        self.corepr  = (packet_bytes[1] >> 1) & 0x7F
        self.col     = (packet_bytes[2] >> 0) & 0x0F
        self.sec     = (packet_bytes[2] >> 4) & 0x0F
        self.ts      = packet_bytes[3]
        self.ts_fpga = (packet_bytes[6] << 16) | (packet_bytes[5] << 8) | packet_bytes[4]
        self.ser     = packet_bytes[7] & 0xF

        self.extend_timestamp()

    def master_idx(self):
        """Returns an index for the Master that produced the data packet

        :returns: Master's index in the Chip
        :rtype: int
        """
        return (self.sec*16+self.col)*128+self.corepr

    def extend_timestamp(self):
        """Extends the timestamp of the data packet by using the timestamp on the FPGA
        """
        ts_fpga_msb = (self.ts_fpga & 0xffff00)
        ts_fpga_lsb = (self.ts_fpga & 0xff)
        if self.ts > ts_fpga_lsb:
            ts_fpga_msb = (ts_fpga_msb-0x100)

        self.ts_ext = (self.ts_sw << 24) | ts_fpga_msb | self.ts

    def get_pixels(self):
        """Produces a list of Pixels contained in the data packet

        :returns: List of pixels
        :rtype: list[Pixel]
        """
        pixels = []

        for pix in range(0, 8):
            if (self.hitmap >> pix) & 0b1 == 0:
                continue

            pr_row = ((pix % 4) > 1)
            pr_col = (pix % 2)

            if pix > 3:
                corepr = self.corepr
                row = 2
            else:
                corepr = self.corepr + 1 - self.bottom
                row = 0

            row += corepr*4 + pr_row
            col = self.sec*32 + self.col*2 + pr_col

            if row > 511 or col > 511:
                raise IndexError('oob %s' % str(self))

            pixels.append(Pixel(row, col))

        return pixels

    def __str__(self):
        return "%s - SER[%2d] @ [%2d][%3d][%2x] = %s (%1d)" % (self.fpga_packet.to_hex(), self.ser, self.sec, self.col, self.corepr, format(self.hitmap, '#010b'), self.bottom)

@dataclass
class TestPulse:
    """A TestPulse data packet from the FPGA

    :param FPGAData fpga_packet: 64-bit data from the FPGA
    """
    fpga_packet: FPGAData

    def __post_init__(self):
        packet_bytes = self.fpga_packet.to_bytes()
        self.ts = (packet_bytes[2] << 16) | (packet_bytes[1] << 8) | packet_bytes[0]
        self.ts_ext = self.ts

    def __str__(self):
        return "%s -      TP @ %d" % (self.fpga_packet.to_hex(), self.ts_ext)

@dataclass(eq=False)
class CustomWord:
    """A CustomWord data packet from the FPGA

    :param FPGAData fpga_packet: 64-bit data from the FPGA
    """
    fpga_packet: FPGAData = None
    message: int = None
    payload: int = None

    def __post_init__(self):
        if self.fpga_packet is None:
            return

        packet_bytes = self.fpga_packet.to_bytes()
        self.message = (packet_bytes[6] << 40) | (packet_bytes[5] << 32) | (packet_bytes[4] << 24) | (packet_bytes[3] << 16) | (packet_bytes[2] << 8) | packet_bytes[1]
        self.payload = packet_bytes[0]

    def __eq__(self, other):
        if not isinstance(other, CustomWord):
            return False

        if self.message != other.message:
            return False

        if self.payload is None or other.payload is None:
            return True
        
        if self.payload != other.payload:
            return False

        return True

    def __str__(self):
        return "%s -     MSG : 0x%x - PAYLOAD : 0x%x" % (self.fpga_packet.to_hex(), self.message, self.payload)

class SubSequence:
    """Part of a Sequence composed only by the relevant TestPulses and ChipDatas
    """
    tps: List[TestPulse] = []
    data: List[ChipData] = []

    from_word: CustomWord = None
    to_word: CustomWord = None
    incomplete: bool = True

    def __init__(self, data=None):
        if data is not None:
            self.append(data)

    def append(self, data):
        if isinstance(data, ChipData):
            self.data.append(data)
        elif isinstance(data, TestPulse):
            self.tps.append(data)
        else:
            raise ValueError("Unsupported data type %s to append to the collection" % type(data))

    def extend(self, other):
        if self.to_word is not None:
            if not self.incomplete:
                raise RuntimeError("Trying to extend a complete SubSequence")

            if self.to_word != other.to_word:
                raise ValueError("Trying to extend with a Subsequence having a different endpoint")

        self.data.extend(other.data)
        self.tps.extend(other.tps)

        self.to_word = other.to_word
        self.incomplete = other.incomplete

    def squash_data(self, fail_on_smartreadout=False):
        self.data.sort(key=lambda x: x.master_idx(), reverse=True)

        smart_readouts = 0

        # Skip to first non-smart packet
        tmp = None
        old_idx = None
        while True:
            try:
                tmp = self.data.pop(0)
            except IndexError:
                return []

            old_idx = tmp.master_idx()

            if tmp.bottom != 0 or (tmp.hitmap & 0xf) == 0:
                break

            smart_readouts += 1
            if fail_on_smartreadout is True:
                raise ValueError("Data merging doesn't support Smart Readout... yet")

        # Elaborate
        new_data = []
        for i in self.data:
            if i.bottom == 0 and (tmp.hitmap & 0xf) != 0:
                if fail_on_smartreadout is True:
                    raise ValueError("Data merging doesn't support Smart Readout... yet")

                smart_readouts += 1
                continue

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

        self.data = new_data

        return smart_readouts

    def dump(self, limit=0, start=0):
        i = 0
        toprint = []

        ts_base = None
        while limit == 0 or i < limit:
            try:
                item = self.data[start+i]
            except IndexError:
                break

            if ts_base is None:
                ts = 0
                ts_base = item.ts_ext
            else:
                ts = item.ts_ext - ts_base

            toprint.append([i, ts, str(item)])
            i += 1

        print(tabulate(toprint, headers=["#", "Timestamp", "Item"]))

class Sequence:
    queue = None
    ts_sw = 0
    subsequences = True

    def __init__(self, packets=None, subsequences=True):
        self.queue = []
        self.subsequences = subsequences

        if packets is not None:
            self.elaborate(packets)

    def __iter__(self):
        yield from self.queue

    def __getitem__(self, item):
        return self.queue[item]

    def __len__(self):
        return len(self.queue)

    def pop(self, item):
        return self.queue.pop(item)

    def elaborate(self, packets):
        for packet in packets:
            elaborated = packet.elaborate()

            if elaborated is None:
                return

            try:
                last = self.queue[-1]
            except IndexError:
                last = None

            # Processing a CustomWord
            if isinstance(elaborated, CustomWord):
                if self.subsequences and isinstance(last, SubSequence):
                    last.to_word = elaborated
                    last.incomplete = False

                self.queue.append(elaborated)
                continue

            # Processing a TestPulse or a ChipData

            # Subsequences off?
            if not self.subsequences:
                self.queue.append(elaborated)
                continue

            if last is None or isinstance(last, CustomWord):
                self.queue.append(SubSequence(elaborated))
            else:
                last.append(elaborated)

    def analyze(self, pixels_cfg, printout=True, plot=False):
        tps = 0
        hitcount = 0

        hits = np.full((512, 512), np.nan)

        # Add received hits, keep track of tps
        for p in self.queue:
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

    def dump(self, start=0, limit=0):
        i = 0
        toprint = []

        while limit == 0 or i < limit:
            try:
                item = self.queue[start+i]
            except IndexError:
                break

            toprint.append([i, str(item)])
            i += 1

        print(tabulate(toprint, headers=["#", "Packet"]))
