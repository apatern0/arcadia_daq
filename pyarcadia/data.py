from dataclasses import dataclass

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
    sequence: 'Sequence' = None

    def __post_init__(self):
        if self.sequence is None:
            self.ts_sw = 0
        else:
            self.ts_sw = self.sequence.ts_sw

        if self.fpga_packet is None:
            self.bottom  = None
            self.hitmap  = None
            self.corepr  = None
            self.col     = None
            self.sec     = None
            self.ts      = None
            self.ts_fpga = None
            self.ser     = None
            self.falling = False
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
        self.falling = False

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
