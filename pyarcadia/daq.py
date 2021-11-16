##
# @file daq.py
#
# @brief Defines the DAQ Class for DAQ/Chip interation
#
# @section description_daq Description
# Defines the base operations that can be performed on the DAQ and the Chip
#
# @section todo_daq TODO
# - None.
#
# @section author_daq Author(s)
# - Created by Andrea Paternò <andrea.paterno@to.infn.it>

import os
import time
import math
import numpy as np

from arcadia_daq import FPGAIf, ChipIf, set_ipbus_loglevel
from .data import FPGAData

set_ipbus_loglevel(0)

def onehot(bits, base=0x0000):
    """One-hot encodes a list of bit positions

    :param bits: The bits to set (list or one-hot encoded value)
    :type bits: List or one-hot encoded integer

    :param base: Base value on which to apply the one-hot encoding
    :type base: int

    :return: One-hot encoded value
    :rtype: int
    """
    if isinstance(bits, list):
        onehot = 0x0000
        for item in bits:
            onehot = onehot | (0xffff & (1 << item))

        bits = onehot

    return bits | base

def onecold(bits, base=0xffff):
    """One-cold encodes a list of bit positions

    :param bits: The bits to set (list or one-cold encoded value)
    :type bits: List or one-cold encoded integer

    :param base: Base value on which to apply the one-cold encoding
    :type base: int

    :return: One-cold encoded value
    :rtype: int
    """
    return ~onehot(bits) & base

class Fpga(FPGAIf):
    """This class is used to communicate with the FPGA.
    It extends the C++ Class implementation FPGAIf, by providing
    a more python-friendly interface.

    :ivar lanes_masked: Sections to filter out during FPGA readout
    """
    clock_hz = 80E6

    def init_connection(self, xml_file=None):
        """Initializes connectivity with the FPGA through IPBus

        :param xml_file: Connection XML file location
        :type xml_file: string
        """
        if xml_file is None:
            xml_file = os.path.abspath(os.path.join(__file__, "../../cfg/connection.xml"))

        try:
            super().__init__(xml_file, 'kc705', 0)
        except:
            raise RuntimeError('Failed to instantiate FPGAIf')

    def __init__(self, xml_file=None):
        self.init_connection(xml_file)

    def get_chip(self, chip_id):
        """Retrieve a Chip instance for the specified chip id.

        :param chip_id: Number of the chip to retrieve [0,1,2]
        :type chip_id: int
        """
        return Chip(chip_id, self.chips[chip_id], self)

class Chip:
    """The Chip class is used to interface with a chip. It
    references the ChipIf interface ported from C++, and wraps
    its methods in order to provide auxiliary features.
    """

    fpga : Fpga = None
    ts_us : int = None

    def __init__(self, chip_id, chipif, fpga):
        self.__chipif = chipif
        self.fpga = fpga

        self.id = chip_id
        self.lanes_masked = []
        self.pcr = None
        self.track_pcr = False

    def __getattr__(self, attr):
        return getattr(self.__chipif, attr)

    def write_gcrpar(self, gcrpar, value):
        """Writes a GCR field

        :param gcrpar: GCR field name as in the ARCADIA Configuration file
        :type gcrpar: string

        :param value: Value to be written in the GCR field
        :type value: int
        """
        self.logger.debug("Writing GCR_PAR[%s] = 0x%x" % (gcrpar, value))
        self.__chipif.write_gcrpar(gcrpar, value)

    def read_gcrpar(self, gcrpar, force_update=False):
        """Reads a GCR

        :param gcr: GCR name as in the ARCADIA Configuration file
        :type gcr: string

        :param force_update: Updates from Chip
        :type force_update: bool
        """
        ret, value = self.__chipif.read_gcrpar(gcrpar, force_update)
        return value


    def read_gcr(self, gcr, force_update=False):
        """Reads a GCR

        :param gcr: GCR name as in the ARCADIA Configuration file
        :type gcr: string

        :param force_update: Updates from Chip
        :type force_update: bool
        """
        _, value = self.__chipif.read_gcr(gcr, force_update)
        return value

    def write_gcr(self, gcr, value):
        """Writes a GCR

        :param gcr: GCR name as in the ARCADIA Configuration file
        :type gcr: string

        :param value: Value to be written in the GCR
        :type value: int
        """
        self.logger.debug("Writing GCR[%2d] = 0x%x" % (gcr, value))
        self.__chipif.write_gcr(gcr, value)

    def write_icr(self, icr, value):
        """Writes an ICR

        :param gcrpar: ICR number
        :type gcrpar: int

        :param value: Value to be written in the ICR
        :type value: int
        """
        self.logger.debug("Writing ICR%1d = %x" % (icr, value))
        self.__chipif.write_icr('ICR%1d' % icr, value)

        if not self.track_pcr or icr != 0 or (value >> 8) & 0b1 == 0:
            return

        # Logging pixels
        if self.pcr is None:
            self.pcr = np.zeros((512, 512), dtype='b')

        secs     = self.read_gcrpar('HELPER_SECCFG_SECTIONS')
        cols     = self.read_gcrpar('HELPER_SECCFG_COLUMNS')
        prstart  = self.read_gcrpar('HELPER_SECCFG_PRSTART')
        prstop   = self.read_gcrpar('HELPER_SECCFG_PRSTOP')
        prskip   = self.read_gcrpar('HELPER_SECCFG_PRSKIP')
        pixsel   = self.read_gcrpar('HELPER_SECCFG_PIXELSELECT')
        cfgval   = self.read_gcrpar('HELPER_SECCFG_CFGDATA')

        for region in range(prstart, prstop+1, prskip+1):
            pix_row_base = region*4 + ((pixsel >> 4) & 0b1)*2
            for pix in range(0, 4):
                if ((pixsel >> pix) & 0b1) == 0:
                    continue

                pix_row = pix_row_base + math.floor(pix/2)
                pix_col_base = (pix % 2)

                for sec in range(0, 16):
                    if (secs >> sec) & 0b1 == 0:
                        continue

                    for col in range(0, 16):
                        if (cols >> col) & 0b1 == 0:
                            continue

                        pix_col = pix_col_base + sec*32 + col*2

                        self.pcr[pix_row][pix_col] = cfgval

    def send_controller_command(self, cmd, value=0):
        """Send a command to the FPGA Controller

        :param cmd: Command name
        :type cmd: string

        :param value: Command payload
        :type value: int, optional
        """
        resp = self.__chipif.send_controller_command(cmd, value)
        return resp

    def packets_reset(self):
        """Clear any packet that might have been readout
        """
        return self.__chipif.packets_reset()

    def packets_count(self):
        """Get the number of available data packets

        :return: Number of available packets
        :rtype: int
        """
        return self.__chipif.packets_count()

    def packets_read(self, packets=0):
        """Read data packets from the chip

        :param packets: Number of packets to retrieve (0 for max)
        :type packets: int, optional

        :return: Packets list
        :rtype: list of uint64
        """
        return self.__chipif.packets_read(packets)

    def packets_read_stop(self):
        """Stops the automatic readout of packets from the FPGA FIFO
        """
        return self.__chipif.packets_read_stop()

    def enable_readout(self, lanes):
        """Enable data readout from the specified lanes

        :param lanes: Lanes to enable
        :type lanes: int or list of ints
        """
        lanes = onehot(lanes) & onecold(self.lanes_masked)
        self.send_controller_command('setTxDataEnable', lanes)

    def custom_word(self, word, payload=0):
        """Inserts a custom word in the FPGA's FIFO.

        :param word: Word to insert
        :type word: int

        :param payload: Optional 8-bit payload to the word
        :type payload: int
        """
        self.send_controller_command('loadUserData_0', ((word<<8) | (payload & 0xff)) & 0xffff)
        self.send_controller_command('loadUserData_1', (word>>8 & 0xffff))
        self.send_controller_command('loadUserData_2', (word>>24 & 0xffff))
        self.send_controller_command('loadUserData_3', (word>>40 & 0x0fff | 0xc000))
        self.send_controller_command('loadUserDataPush', 0)

    def set_timestamp_delta(self, delta):
        """Sets the FPGA timestamp delta. Used for timestamp synchronization
        between FPGA and chip.

        :param delta: Delta to set
        :type delta: int
        """
        self.send_controller_command('loadTSDeltaLSB', ((delta>>0)  & 0xfffff))
        self.send_controller_command('loadTSDeltaMSB', ((delta>>20) & 0xfffff))

    def calibrate_deserializers(self):
        """Trigger the calibration of the deserializers. The procedure tries
        to select and set the optimal Tap Delays in order to minimize sampling
        errors.

        :return: Lanes that have been successfully calibrated
        :rtype: list of ints
        """
        self.sync_mode()
        time.sleep(0.01)
        response = self.__chipif.calibrate_deserializers()
        time.sleep(0.01)
        self.normal_mode()

        lanes = []
        for i in range(16):
            if (response >> i) & 0b1:
                lanes.append(i)

        return lanes

    def set_timestamp_period(self, period):
        """Set the timestamp period in the FPGA timestamp counter.

        :param period: Period in FPGA Clock cycles
        :type period: int
        """
        self.send_controller_command('writeTimeStampPeriod', (period & 0xffff))

    # Chip commands
    def hard_reset(self):
        """Sends a hard reset to the chip through the Reset pin.
        """
        self.send_controller_command('doRESET', 0x1)

    def soft_reset(self):
        """Sends a hard reset to the chip through ICR resets.
        """
        self.write_icr(0, 0x0015)

    def space_mode(self):
        """Configures the chip to operate in space mode. Only lane 0 will be activated.
        """
        self.write_gcrpar('OPERATION', 1)

    def normal_mode(self):
        """Configures the chip to operate in normal mode. All the lanes will be activated.
        """
        self.write_gcrpar('SERIALIZER_SYNC', 0)
        self.write_gcrpar('OPERATION', 0)

    def sync_mode(self):
        """Configures the chip to operate in sync mode. Lanes only send synchronization words.
        """
        self.write_gcrpar('SERIALIZER_SYNC', 1)

    def reset_subsystem(self, subsystem, action=0):
        """Uses the built-in reset mechanism to reset on-chip subsystems.

        :param subsystem: The subsystem to reset [chip, gcr, per, sec, ts]
        :type subsystem: string

        :param action: Reset operation [0: pulse, 1: start, 2: stop]
        :type action: int
        """
        sub_dict = {
            'chip': 3,
            'gcr':  4,
            'per':  5,
            'sec':  6,
            'ts':   7
        }

        try:
            bit = sub_dict[subsystem]
        except KeyError:
            raise Exception("Subsystem %s doesn't exist!" % subsystem)

        icr0 = (1 << bit) | ((1 << action) & 0x7)
        self.write_icr(0, icr0)

    # Onehot/Onecold GCRs
    def gcr_onehot(self, gcr, value=0xffff, update=False):
        """Configures a GCR to a one-hot encoded value

        :param gcr: GCR to configure
        :type gcr: int

        :param value: Value to be used
        :type action: int or list of ints

        :param update: Update previous value with new bits enabled or substitute
        :type update: bool
        """

        base = self.read_gcr(gcr) if update else 0x0000
        value = onehot(value, base)

        self.write_gcr(gcr, value)

    def gcr_onecold(self, gcr, value=0xffff, update=False):
        """Configures a GCR to a one-cold encoded value

        :param gcr: GCR to configure
        :type gcr: int

        :param value: Value to be used
        :type action: int or list of ints

        :param update: Update previous value with new bits enabled or substitute
        :type update: bool
        """

        base = self.read_gcr(gcr) if update else 0xffff
        value = onecold(value, base)

        self.write_gcr(gcr, value)

    def injection_disable(self, sections=0xffff, update=False):
        """Disables injection on selected sections.

        :param sections: Sections to disable
        :type sections: int or list of ints

        :param update: Update from previous value or substitute
        :type update: bool
        """
        self.gcr_onehot(2, sections, update)

    def injection_enable(self, sections=0xffff, update=False):
        """Enables injection on selected sections.

        :param sections: Sections to enable
        :type sections: int or list of ints

        :param update: Update from previous value or substitute
        :type update: bool
        """
        self.gcr_onecold(2, sections, update)

    def read_disable(self, sections=0xffff, update=False):
        """Disables readout on selected sections.

        :param sections: Sections to disable
        :type sections: int or list of ints

        :param update: Update from previous value or substitute
        :type update: bool
        """
        self.gcr_onehot(2, sections, update)

    def read_enable(self, sections=0xffff, update=False):
        """Enables readout on selected sections.

        :param sections: Sections to enable
        :type sections: int or list of ints

        :param update: Update from previous value or substitute
        :type update: bool
        """
        self.gcr_onecold(2, sections, update)

    def clock_disable(self, sections=0xffff, update=False):
        """Disables clock on selected sections.

        :param sections: Sections to disable
        :type sections: int or list of ints

        :param update: Update from previous value or substitute
        :type update: bool
        """
        self.gcr_onehot(3, sections, update)

    def clock_enable(self, sections=0xffff, update=False):
        """Enables clock on selected sections.

        :param sections: Sections to enable
        :type sections: int or list of ints

        :param update: Update from previous value or substitute
        :type update: bool
        """
        self.gcr_onecold(3, sections, update)

    def injection_digital(self, sections=0xffff, update=False):
        """Enables digital injection on selected sections.

        :param sections: Sections
        :type sections: int or list of ints

        :param update: Update from previous value or substitute
        :type update: bool
        """
        self.gcr_onehot(4, sections, update)

    def injection_analog(self, sections=0xffff, update=False):
        """Enables analog injection on selected sections.

        :param sections: Sections
        :type sections: int or list of ints

        :param update: Update from previous value or substitute
        :type update: bool
        """
        self.gcr_onecold(4, sections, update)

    def force_injection(self, sections=0xffff, update=False):
        """Override pixel's PCR to force injection on selected sections.

        :param sections: Sections
        :type sections: int or list of ints

        :param update: Update from previous value or substitute
        :type update: bool
        """
        self.gcr_onehot(5, sections, update)

    def noforce_injection(self, sections=0xffff, update=False):
        """Disables pixel's PCR override to force injection on selected sections.

        :param sections: Sections
        :type sections: int or list of ints

        :param update: Update from previous value or substitute
        :type update: bool
        """
        self.gcr_onecold(5, sections, update)

    def force_nomask(self, sections=0xffff, update=False):
        """Override pixel's PCR to disable mask on selected sections.

        :param sections: Sections
        :type sections: int or list of ints

        :param update: Update from previous value or substitute
        :type update: bool
        """
        self.gcr_onehot(6, sections, update)

    def noforce_nomask(self, sections=0xffff, update=False):
        """Disables pixel's PCR override to disable mask on selected sections.

        :param sections: Sections
        :type sections: int or list of ints

        :param update: Update from previous value or substitute
        :type update: bool
        """
        self.gcr_onecold(6, sections, update)

    # PCRs
    def write_pcr(self):
        """Start the pixel's PCR programming procedure
        """
        self.write_icr(0, onehot([8]))

    def pixel_cfg(self, cfg, pixel):
        """Configure a pixel with a specific PCR value.

        :param int cfg: Value to configure the PCR to

        :param Pixel pixel: Pixel to configure
        """
        self.pixels_cfg(
            cfg,
            [pixel.get_sec()],
            [pixel.get_dcol()],
            [pixel.get_corepr()],
            [pixel.get_master()],
            [pixel.get_idx()]
        )

    def pixels_cfg(self, cfg, sections = 0xffff, columns = 0xffff, prs=None, master=None, pixels = 0xf):
        """Configure a set of pixels with a specific PCR value.

        :param int|List[int] sections: Sections
        :param int|List[int] columns: Columns
        :param int|List[int] prs: Pixel Regions
        :param int|List[int] master: Master sub-PR or Slave
        :param int|List[int] pixels: Pixels in the sub-PR
        """
        self.write_gcrpar('HELPER_SECCFG_SECTIONS', onehot(sections))
        self.write_gcrpar('HELPER_SECCFG_COLUMNS', onehot(columns))

        if prs is None:
            prs = [[0, 127]]
        elif isinstance(prs, int):
            prs = [[prs]]

        if master is None:
            master = [0, 1]

        for pr_range in prs:
            if isinstance(pr_range, int):
                range_start = pr_range
                range_stop  = pr_range
            elif isinstance(pr_range, list) and len(pr_range) == 1:
                range_start = pr_range[0]
                range_stop  = pr_range[0]
            else:
                range_start = pr_range[0]
                range_stop  = pr_range[1]

            self.write_gcrpar('HELPER_SECCFG_PRSTART', range_start)
            self.write_gcrpar('HELPER_SECCFG_PRSKIP',  0)
            self.write_gcrpar('HELPER_SECCFG_CFGDATA', cfg)
            self.write_gcrpar('HELPER_SECCFG_PRSTOP',  range_stop)

            master = [master] if not isinstance(master, list) else master
            for subpr in master:
                pselect = (subpr << 4) | (onehot(pixels) & 0xf)
                self.write_gcrpar('HELPER_SECCFG_PIXELSELECT', pselect)
                self.write_pcr()

    def pixels_mask(self, sections=0xffff, columns=0xffff, prs=None, master=None, pixels = 0xf):
        """Mask a set of pixels

        :param sections: Sections
        :type sections: int or list of ints

        :param columns: Columns
        :type columns: int or list of ints

        :param prs: Pixel Regions
        :type prs: list of ints

        :param master: Master sub-PR or Slave
        :type master: int or list of ints

        :param pixels: Pixels in the sub-PR
        :type pixels: int or list of ints
        """
        self.pixels_cfg(0b11, sections, columns, prs, master, pixels)

    # Injection
    def send_tp(self, pulses=1, us_on=1, us_off=1):
        """Send a Test Pulse train to the chip.

        :param pulses: Number of Test Pulses to send
        :type pulses: int

        :param t_on: TP high state duration in number of clock cycles
        :type t_on: int

        :param t_off: TP low state duration in number of clock cycles
        :type t_off: int
        """

        t_on_f = self.fpga.clock_hz*(us_on/1E6)
        t_off_f = self.fpga.clock_hz*(us_off/1E6)

        t_on = int(t_on_f)
        t_off = int(t_off_f)

        if t_on != t_on_f:
            self.logger.warning("Cropping TP t_on from %.3f us to %.3f us", us_on, t_on/self.fpga.clock_hz*1E6)

        if t_off != t_off_f:
            self.logger.warning("Cropping TP t_off from %.3f us to %.3f us", us_off, t_off/self.fpga.clock_hz*1E6)

        if t_on > (1<<20):
            raise ValueError("TP On Time (%d) exceeds maximum value of %d." % (t_on, (1<<20)))

        if t_off > (1<<20):
            raise ValueError("TP Off Time (%d) exceeds maximum value of %d." % (t_off, (1<<20)))

        t_on = t_on-2 if (t_on > 2) else t_on
        t_off = t_off-1 if (t_off > 1) else t_off
        self.__chipif.send_pulse(int(t_on), int(t_off), pulses)

        return pulses*(t_on+t_off+2+1)*31.25E-9

    # FPGA commands
    def sync(self, lanes=0xffff):
        """Trigger the FPGA synchronization procedure on specific lanes.

        :param lanes: Lanes to synchronize
        :type lanes: int or list of ints

        :return: List of synchronized lanes
        :rtype: list of ints
        """
        self.send_controller_command('syncTX', onehot(lanes))
        ret, response = self.send_controller_command('readTxState', 0)

        lanes = []
        for i in range(16):
            if (response >> i) & 0b1:
                lanes.append(i)

        return lanes

    def readout(self, max_packets=32768, idle_start_timeout=50):
        for i in range(idle_start_timeout):
            in_fifo = self.packets_count()
            if in_fifo != 0:
                break

            time.sleep(0.1)

        if in_fifo == 0:
            raise StopIteration("Zero packets in fifo after %.1f seconds" % (idle_start_timeout*0.1))

        return FPGAData.from_packets(self.packets_read(max_packets))
