import os
import numpy as np
import time
import math
import functools
import matplotlib
import matplotlib.pyplot as plt
from tabulate import tabulate

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


class Data:
    word = 0
    bits = 64

    bytes = []

    def __init__(self, word=None):
        if word is not None:
            self.word = int(word)

    def __index__(self):
        return self.word

    def __format__(self, format_string):
        string = ""
        word = self.word
        for i in range(0, self.bits, 8):
            word = word >> i*8
            string += format((word & 0xff), format_string)

        return string

    def to_hex(self):
        string = ""
        wb = self.to_bytes()

        for i in wb:
            string = "{0:#0{1}x} ".format(i,4)[2:] + string

        return string

    def to_bytes(self):
        return [(self.word >> 8*x) & 0xff for x in range(8)]


class Pixel:
    row    = 0
    col    = 0

    def __init__(self, row, col):
        self.row = row
        self.col = col

    def get_sec(self):
        return Pixel.sec_from_col(self.col)

    def get_dcol(self):
        return Pixel.dcol_from_col(self.col)

    def get_corepr(self):
        return Pixel.corepr_from_row(self.row)

    def get_master(self):
        return Pixel.master_from_row(self.row)

    def get_idx(self):
        return Pixel.idx_from_pos(self.row, self.col)

    def __str__(self):
        return "Pixel @ [%3d][%3d] SEC %d DCOL %d COREPR %d" % (self.row, self.col, self.get_sec(), self.get_dcol(), self.get_corepr())

    @staticmethod
    def sec_from_col(col):
        return col >> 5

    @staticmethod
    def dcol_from_col(col):
        return (col >> 1) & 0xf

    @staticmethod
    def corepr_from_row(row):
        return row >> 2

    @staticmethod
    def master_from_row(row):
        return (row >> 1) & 0x1

    @staticmethod
    def idx_from_pos(row, col):
        return (row & 0x1)*2 + (col & 0x1)

class ChipData(Data):
    bottom  = 0
    hitmap  = 0
    corepr  = 0
    col     = 0
    sec     = 0
    ser     = 0
    ts      = 0

    ts_fpga = 0
    ts_sw   = 0
    ts_ext  = 0

    pixels = []

    def __init__(self, word=None, sequence=None):
        super().__init__(word)

        if sequence is not None:
            self.ts_sw  = sequence.ts

        if word is not None:
            wb = self.to_bytes()

            self.bottom  = (wb[0] >> 0) & 0x01
            self.hitmap  = (((wb[1] >> 0) & 0x01) << 7) | ((wb[0] >> 1) & 0x7F)
            self.corepr  = (wb[1] >> 1) & 0x7F
            self.col     = (wb[2] >> 0) & 0x0F
            self.sec     = (wb[2] >> 4) & 0x0F
            self.ts      = wb[3]
            self.ts_fpga = (wb[6] << 16) | (wb[5] << 8) | wb[4]
            self.ser     = wb[7] & 0xF

            self.ts_sw   = 0
            self.pixels = []

        self.extend_timestamp()

    def master_idx(self):
        return (self.sec*16+self.col)*128+self.corepr

    def extend_timestamp(self):
        ts_fpga_msb = (self.ts_fpga & 0xffff00)
        ts_fpga_lsb = (self.ts_fpga & 0xff)
        if (self.ts > ts_fpga_lsb):
            ts_fpga_msb = (ts_fpga_msb-0x100)

        self.ts_ext  = (self.ts_sw << 24) | ts_fpga_msb | self.ts

    def get_pixels(self):
        pixels = []

        for pix in range(0,8):
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

            if row >511 or col > 511:
                raise IndexError('oob %s' % str(self))

            p = Pixel(row, col)
            pixels.append(p)

        return pixels

    def get_prs(self):
        prs = {}

        master_hitmap = (self.hitmap >> 4)
        if master_hitmap != 0:
            prs[self.corepr] = master_hitmap

        slave_hitmap = (self.hitmap & 0xf)
        if slave_hitmap != 0:
            prs[self.corepr + 1 - self.bottom] = slave_hitmap

        return prs

    def __str__(self):
        return "%s - SER[%2d] @ [%2d][%3d][%2x] = %s (%1d)" % (self.to_hex(), self.ser, self.sec, self.col, self.corepr, format(self.hitmap, '#010b'), self.bottom)

class TestPulse(Data):
    ts = 0
    ts_sw = 0
    ts_ext = 0

    def __init__(self, word):
        super().__init__(word)
    
        wb = self.to_bytes()
        self.ts = (wb[2] << 16) | (wb[1] << 8) | wb[0]
        self.ts_ext = self.ts

    def __str__(self):
        return "%s -      TP @ %d" % (self.to_hex(), self.ts_ext)

class CustomWord(Data):
    def __init__(self, word):
        super().__init__(word)

        wb = self.to_bytes()
        self.message = (wb[6] << 40) | (wb[5] << 32) | (wb[4] << 24) | (wb[3] << 16) | (wb[2] << 8) | wb[1]
        self.payload = wb[0]

    def __str__(self):
        return "%s -     MSG : 0x%x - PAYLOAD : 0x%x" % (self.to_hex(), self.message, self.payload)

class FPGAData(Data):
    def elaborate(self, sequence=None):
        #self.logger.info("RawFPGAData: %2x - %#010b" % (self, self))
        ctrl = self.word >> ((8*7)+4)

        # FPGA timestamp overflow
        if ctrl == 0xf:
            if sequence is not None:
                sequence.ts_sw += 1

            return None

        # Test pulse
        if ctrl == 0xa:
            tp = TestPulse(self.word)

            #self.logger.info("Found test pulse @ %x" % tp.ts)
            return tp

        if ctrl == 0xc:
            c = CustomWord(self.word)

            return c

        # Chip data
        p = ChipData(self.word, sequence)
        return p

class Results:
    def __init__(self, tps=None, data=None):
        self.tps = tps if tps is not None else []
        self.data = data if data is not None else []
        self.payload = None

        self.payload_error = False
        self.message_error = False
        self.incomplete = False

    def append_data(self, data):
        self.data.append(data)

    def append_tps(self, tps):
        self.tps.append(tps)

    def extend(self, results):
        self.data.extend(results.data)
        self.tps.extend(results.tps)

        self.payload = results.payload
        self.incomplete = results.incomplete
        self.payload_error = results.payload_error
        self.message_error = results.message_error

    def merge_data(self, check=False):
        self.data.sort(key=lambda x: x.master_idx(), reverse=True)

        new_data = []
        smart_readouts = 0

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
            if check is True:
                raise ValueError("Data merging doesn't support Smart Readout... yet")

        for d in self.data:
            if d.bottom == 0 and (tmp.hitmap & 0xf) != 0:
                if check is True:
                    raise ValueError("Data merging doesn't support Smart Readout... yet")

                smart_readouts += 1
                continue

            this_idx = d.master_idx()

            if this_idx != old_idx:
                tmp.bottom = 1
                new_data.append(tmp)
                tmp = d
            else:
                tmp.hitmap |= d.hitmap

            old_idx = this_idx

        # Account for any last loner
        new_data.append(tmp)

        self.data = new_data

        return smart_readouts

class Sequence:
    def __init__(self, packets=None):
        self.packets = []
        self.ts_sw   = 0

        if packets is not None:
            self.elaborate(packets)

    def __iter__(self):
        yield from self.packets

    def elaborate(self, packets):
        for packet in packets:
            p = FPGAData(packet)
            e = p.elaborate()

            if e is not None:
                self.packets.append(e)

    def pop_until(self, message, payload=None):
        tps = []
        data = []
        p = None

        results = Results()

        while True:
            try:
                p = self.packets.pop(0)
            except IndexError:
                results.incomplete = True
                break

            if isinstance(p, CustomWord):
                if p.message != message:
                    results.message_error = p.message
                else:
                    results.payload = p.payload & 0xff

                if payload is not None and p.payload != payload:
                    results.payload_error = True

                break

            if isinstance(p, ChipData):
                results.append_data(p)
            elif isinstance(p, TestPulse):
                results.append_tps(p)
            else:
                raise ValueError('Packet p is no known type: %s' % p)

        return results

    def analyze(self, pixels_cfg, printout=True, plot=False):
        tps = 0
        hitcount = 0

        hits = np.full((512, 512), np.nan)

        # Add received hits, keep track of tps
        for p in self.packets:
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

        ts_base = None
        while limit == 0 or i < limit:
            try:
                p = self.packets[start+i]
            except IndexError:
                break

            if ts_base is None:
                ts = 0
                ts_base = p.ts_ext
            else:
                ts = p.ts_ext - ts_base

            toprint.append([i, ts, str(p)])
            i += 1

        print(tabulate(toprint, headers=["#", "Timestamp", "Packet dump"]))
