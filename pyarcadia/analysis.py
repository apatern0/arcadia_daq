import numpy as np
import time

class Packet:
    binstr = ""
    ts_base = 0
    ts_hz = 1

    def to_string(self):
        return self.binstr

class Pixel:
    row    = 0
    col    = 0
    dcol   = 0
    corepr = 0
    sec    = 0

    def to_string(self):
        return "Pixel @ [%3d][%3d] SEC %d DCOL %d COREPR %d" % (self.row, self.col, self.sec, self.dcol, self.corepr)

class PixelData(Packet):
    bottom  = 0
    hitmap  = 0
    corepr  = 0
    col     = 0
    sec     = 0
    ser     = 0
    ts      = 0
    ts_ext  = 0
    ts_fpga = 0
    ts_sw   = 0
    ts_base = 0
    last_tp = 0
    binstr = ""
    pixels = []

    def to_string(self):
        packet_info = "%s - SER[%2d] @ [%2d][%3d][%2x] = %s (%1d)" % (self.binstr, self.ser, self.sec, self.col, self.corepr, format(self.hitmap, '#010b'), self.bottom)

        ts_info = "%u [ %u us - %u (TP-CHIP) - %u (TP-DAQ) - %u (TS_SW) ]" % (
            self.ts_ext-self.ts_base,
            (self.ts_ext-self.ts_base)*1E6/self.ts_hz,
            (self.ts_ext-self.last_tp     )*1E6/self.ts_hz,
            (self.ts_fpga-self.last_tp    )*1E6/self.ts_hz,
            self.ts_sw
        )

        return "%s @ %s" % (packet_info, ts_info)

class TestPulse(Packet):
    ts = 0
    ts_sw = 0
    ts_base = 0
    binstr = ""

    def to_string(self):
        return "%s -      TP @ %d (%.3f us)" % (self.binstr, self.ts-self.ts_base, 1E6*(self.ts-self.ts_base)/self.ts_hz)

class CustomWord(Packet):
    binstr = ""
    word = 0
    payload = 0

    def to_string(self):
        return "%s -    WORD : 0x%x" % (self.binstr, self.word)

class DataAnalysis:
    """ Analyses data from chip """
    raw_file = "doutid0.raw"
    file = None
    file_ptr = 0

    packets = []

    prs = np.zeros((256,128))
    topslaves = np.zeros((256,128))
    secs = np.zeros(16)
    nf = 0
    topslaves_sec = np.zeros(16)
    tot = 0
    fixed = np.ones(43)

    ts_base = -1
    ts_hz = 320E6
    ts_sw = 0

    logger = None

    def __init__(self):
        self.file = open(self.raw_file, "rb")
        self.file.seek(0,2) # Go to the end of the file
        self.file_ptr = self.file.tell()

    def reverse_bitorder(self, byte):
        return int('{:08b}'.format(byte)[::-1], 2)

    def skip(self):
        self.file.seek(0,2)
        self.file_ptr = self.file.tell()

    def analyze(self):
        slept = 0
        read = 0
        last_tp = 0
        self.logger.info("Starting readout on byte %d" % self.file_ptr)
        while True:
            word = self.file.read(8)
            lw = len(word)
            if (lw < 8):
                self.logger.warning(f"Read {lw} bytes out of 8. Mmm.. rolling back for now")
                self.file.seek(self.file_ptr)
                if(read == 0 and slept < 3):
                    time.sleep(0.5)
                    slept += 0.5
                    continue
                else:
                    break

            self.file_ptr = self.file.tell()

            read += 1
            byte0 = word[4]
            byte1 = word[5]
            byte2 = word[6]
            byte3 = word[7]
            byte4 = word[0]
            byte5 = word[1]
            byte6 = word[2]
            byte7 = word[3]

            strh = ""
            strb = ""
            for i in [3, 2, 1, 0, 7, 6, 5, 4]:
                strh = strh + "%2x " % word[i]
                strb = strb + format(word[i], '#010b') + " "

            self.logger.info("Packet: %s - %s" % (strh, strb))

            # Check packet type
            if ((byte7>>4) == 0xf):
                self.ts_sw += 1

                continue

            elif ((byte7>>4) == 0xa):
                tp = TestPulse()
                tp.ts = (byte2 << 16) | (byte1 << 8) | byte0
                tp.binstr = strh

                if(read == 1):
                    self.ts_base = tp.ts

                tp.ts_base = self.ts_base
                tp.ts_hz = self.ts_hz
                tp.ts_sw = self.ts_sw

                self.logger.info("Found test pulse @ %x" % tp.ts)
                self.packets.append(tp)

                last_tp = (self.ts_sw << 24) | tp.ts

                continue

            elif ((byte7>>4) == 0xc):
                c = CustomWord()
                c.binstr = strh
                c.word = (byte6 << 40) | (byte5 << 32) | (byte4 << 24) | (byte3 << 16) | (byte2 << 8) | byte1
                c.payload = byte0
                self.packets.append(c)
        
                continue

            # Split into fields
            packet = PixelData()
            packet.bottom  = (byte0 >> 0) & 0x01
            packet.hitmap  = (((byte1 >> 0) & 0x01) << 7) | ((byte0 >> 1) & 0x7F)
            packet.corepr  = (byte1 >> 1) & 0x7F
            packet.col     = (byte2 >> 0) & 0x0F
            packet.sec     = (byte2 >> 4) & 0x0F
            packet.ts      = byte3
            packet.ts_fpga = (byte6 << 16) | (byte5 << 8) | byte4
            packet.ts_sw   = self.ts_sw

            ts_fpga_msb = (packet.ts_fpga & 0xffff00)
            ts_fpga_lsb = (packet.ts_fpga & 0xff)
            if (packet.ts > ts_fpga_lsb):
                ts_fpga_msb = (ts_fpga_msb-0x100)

            packet.ts_ext  = (self.ts_sw << 24) | ts_fpga_msb | packet.ts
            packet.ser     = byte7 & 0xF
            packet.binstr = strh
            packet.pixels = []

            for pix in range(0,7):
                if((packet.hitmap >> pix) & 0b1):
                    pr_row = ((pix % 4) > 1)
                    pr_col = (pix % 2)

                    p = Pixel()
                    p.dcol   = packet.col
                    p.sec    = packet.sec
                    if(pix>3):
                        p.corepr = packet.corepr
                        p.row = 2
                    else:
                        p.corepr = packet.corepr +1 -packet.bottom
                        p.row = 0

                    p.row += p.corepr*4 + pr_row
                    p.col = packet.sec*32 + packet.col*2 + pr_col

                    packet.pixels.append(p)


            if(read == 1):
                self.ts_base = packet.ts_ext

            packet.ts_base = self.ts_base
            packet.ts_hz = self.ts_hz
            packet.last_tp = last_tp
            self.packets.append(packet)

            # Statistics
            self.secs[packet.sec] += 1
            self.prs[packet.sec*16+packet.col][packet.corepr] += 1

            self.tot += 1

        return read

    def cleanup(self):
        self.packets.clear()
        self.ts_base = -1

    def subset(self, from_packet, to_packet):
        s = []

        iterator = iter(self.packets)

        try:
            next(p for p in iterator if type(p) == CustomWord and p.word == from_packet.word and p.payload == from_packet.payload)
        except StopIteration:
            self.logger.fatal('Never encountered from_packet %s!' % from_packet.to_string())

        while True:
            try:
                packet = next(iterator)
            except StopIteration:
                break

            if(type(packet) == CustomWord and packet.word == to_packet.word and packet.payload == to_packet.payload):
                break
            else:
                s.append(packet)

        return s

    def print_stats(self):
        for i in range(16):
            print("Section %2d has %4d data packets!" % (i, self.secs[i]))

    def dump(self, limit=0):
        counter = 0
        last_data = 0
        for packet in self.packets:
            if(limit != 0 and counter > limit):
                break

            print("%3d) %s" % (counter, packet.to_string()))

            counter = counter+1

        
