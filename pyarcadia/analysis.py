import numpy as np
from tabulate import tabulate
import time

class Data:
    word = 0
    bits = 63

    bytes = []

    def __init__(self, word):
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
        word = self.word
        for i in range(0, self.bits, 8):
            word = word >> i*8
            string += format((word & 0xff), '2x')

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
        return self.col / 32

    def get_dcol(self):
        return (self.col % 32) / 16

    def get_corepr(self):
        return self.row / 4

    def __str__(self):
        return "Pixel @ [%3d][%3d] SEC %d DCOL %d COREPR %d" % (self.row, self.col, self.get_sec(), self.get_dcol(), self.get_corepr())

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

    def __init__(self, word, sequence):
        super().__init__(word)
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

        for pix in range(0,7):
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

            p = Pixel(row, col)
            self.pixels.append(p)

        if sequence is not None:
            self.ts_sw  = sequence.ts

        self.extend_timestamp()

    def extend_timestamp(self):
        ts_fpga_msb = (self.ts_fpga & 0xffff00)
        ts_fpga_lsb = (self.ts_fpga & 0xff)
        if (self.ts > ts_fpga_lsb):
            ts_fpga_msb = (ts_fpga_msb-0x100)

        self.ts_ext  = (self.ts_sw << 24) | ts_fpga_msb | self.ts

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
        self.word = (wb[6] << 40) | (wb[5] << 32) | (wb[4] << 24) | (wb[3] << 16) | (wb[2] << 8) | wb[1]
        self.payload = wb[0]

    def __str__(self):
        return "%s -    WORD : 0x%x - PAYLOAD : 0x%x" % (self.to_hex(), self.word, self.payload)

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
        self.word_error = False
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
        self.word_error = results.word_error

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

    def pop_until(self, word, payload=None):
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
                if p.word != word:
                    results.word_error = p.word
                else:
                    results.payload = p.payload

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

    def dump(self, start=0, limit=0):
        i = 0
        toprint = []

        ts_base = None
        while i < limit:
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

        print(tabulate(toprint))
