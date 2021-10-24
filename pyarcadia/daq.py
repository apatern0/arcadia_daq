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

import os, sys, argparse, time, logging, math
import numpy as np
import matplotlib.pyplot as plt

from arcadia_daq import FPGAIf, ChipIf, set_ipbus_loglevel
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
    if(isinstance(bits, list)):
        onehot = 0x0000
        for item in bits:
            onehot = onehot | (0xffff & (1 << item));

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
    """This class is used to communicate with the FPGA

    :ivar chip_id: Chip identification. Default: id0
    :ivar lanes_masked: Sections to filter out during FPGA readout
    """

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
            sys.exit(255)

    def __init__(self, xml_file=None):
        self.init_connection(xml_file)

    def get_chip(self, chip_id):
        return Chip(chip_id, self.chips[chip_id])

class Chip(object):
    def __init__(self, id, chipif):
        self.__chipif = chipif

        self.id = id
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
        ret, value = self.__chipif.read_gcr(gcr, force_update)
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

        for pr in range(prstart, prstop+1, prskip+1):
            pix_row_base = pr*4 + ((pixsel >> 4) & 0b1)*2
            for pix in range(0,4):
                if ((pixsel >> pix) & 0b1) == 0:
                    continue

                pix_row = pix_row_base + math.floor(pix/2)
                pix_col_base = (pix % 2)

                for sec in range(0,16):
                    if (secs >> sec) & 0b1 == 0:
                        continue

                    for col in range(0,16):
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
        """Get the current FPGA FIFO occupancy

        :return: Data packets in the FPGA FIFO
        :rtype: int
        """
        return self.__chipif.packets_count()

    def packets_read(self, packets=0):
        """Get `packets` readout from DAQ FIFO

        :return: Number of packets readout
        :rtype: int
        """
        return self.__chipif.packets_read(packets)

    def packets_read_stop(self):
        """Waits for the data readout to stop
        """
        return self.__chipif.packets_read_stop()

    def readout(self):
        """Fetch readout packets

        :return: Data packets readout so far
        :rtype: py::array_t
        """
        return self.__chipif.readout()

    def enable_readout(self, sections):
        """Enable t

        :return: Data packets in the FPGA FIFO
        :rtype: int
        """
        sections = onehot(sections) & onecold(self.lanes_masked)
        self.send_controller_command('setTxDataEnable', sections)

    def custom_word(self, word, payload=0):
        self.send_controller_command('loadUserData_0', ((word<<8) | (payload & 0xff)) & 0xffff)
        self.send_controller_command('loadUserData_1', (word>>8 & 0xffff))
        self.send_controller_command('loadUserData_2', (word>>24 & 0xffff))
        self.send_controller_command('loadUserData_3', (word>>40 & 0x0fff | 0xc000))
        self.send_controller_command('loadUserDataPush', 0)

    def set_timestamp_delta(self, delta):
        self.send_controller_command('loadTSDeltaLSB', ((delta>>0)  & 0xfffff))
        self.send_controller_command('loadTSDeltaMSB', ((delta>>20) & 0xfffff))

    def calibrate_deserializers(self):
        self.sync_mode()
        time.sleep(0.01)
        response = self.__chipif.calibrate_deserializers()
        time.sleep(0.01)
        self.normal_mode()

        lanes = []
        for i in range(16):
            if ((response >> i) & 0b1):
                lanes.append(i)

        return lanes

    def set_timestamp_period(self, period):
        period = period
        self.send_controller_command('writeTimeStampPeriod', (period & 0xffff))

    # Chip commands
    def hard_reset(self):
        self.send_controller_command('doRESET', 0x1)

    def soft_reset(self):
        self.write_icr(0, 0x0015)

    def space_mode(self):
        self.write_gcrpar('OPERATION', 1)

    def normal_mode(self):
        self.write_gcrpar('SERIALIZER_SYNC', 0)
        self.write_gcrpar('OPERATION', 0)

    def sync_mode(self):
        self.write_gcrpar('SERIALIZER_SYNC', 1)

    def reset_subsystem(self, subsystem, action=0):
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
    def gcr_onehot(self, gcr, sections=0xffff, update=False):
        base = self.read_gcr(gcr) if update else 0x0000
        sections = onehot(sections, base)
    
        self.write_gcr(gcr, sections)

    def gcr_onecold(self, gcr, sections=0xffff, update=False):
        base = self.read_gcr(gcr) if update else 0xffff
        sections = onecold(sections, base)

        self.write_gcr(gcr, sections)

    def injection_disable(self, sections=0xffff, update=False):
        self.gcr_onehot(2, sections, update)

    def injection_enable(self, sections=0xffff, update=False):
        self.gcr_onecold(2, sections, update)

    def read_disable(self, sections=0xffff, update=False):
        self.gcr_onehot(2, sections, update)

    def read_enable(self, sections=0xffff, update=False):
        self.gcr_onecold(2, sections, update)

    def clock_disable(self, sections=0xffff, update=False):
        self.gcr_onehot(3, sections, update)

    def clock_enable(self, sections=0xffff, update=False):
        self.gcr_onecold(3, sections, update)

    def injection_digital(self, sections=0xffff, update=False):
        self.gcr_onehot(4, sections, update)

    def injection_analog(self, sections=0xffff, update=False):
        self.gcr_onecold(4, sections, update)

    def force_injection(self, sections=0xffff, update=False):
        self.gcr_onehot(5, sections, update)

    def noforce_injection(self, sections=0xffff, update=False):
        self.gcr_onecold(5, sections, update)

    def force_nomask(self, sections=0xffff, update=False):
        self.gcr_onehot(6, sections, update)

    def noforce_nomask(self, sections=0xffff, update=False):
        self.gcr_onecold(6, sections, update)

    # PCRs
    def write_pcr(self):
        self.write_icr(0, onehot([8]))

    def pixel_cfg(self, cfg, p):
        self.pixels_cfg(cfg, [p.get_sec()], [p.get_dcol()], [p.get_corepr()], [p.get_master()], [p.get_idx()])

    def pixels_cfg(self, cfg, sections = 0xffff, columns = 0xffff, prs=None, master=None, pixels = 0xf):
        self.write_gcrpar('HELPER_SECCFG_SECTIONS', onehot(sections))
        self.write_gcrpar('HELPER_SECCFG_COLUMNS',  onehot(columns))

        if(prs == None):
            prs = [[0, 127]]
        elif(isinstance(prs, int)):
            prs = [[prs]]

        if(master == None):
            master = [0, 1]

        for pr_range in prs:
            if(isinstance(pr_range, int)):
                range_start = pr_range
                range_stop  = pr_range
            elif(isinstance(pr_range, list) and len(pr_range) == 1):
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
                #self.logger.info("Configuring [%x][%x][%d]->[%d] %s[%s] w/ %x" % (onehot(sections), onehot(columns), range_start, range_stop, str(master), format(onehot(pixels), '#06b')[2:], cfg))
                pselect = (subpr << 4) | (onehot(pixels) & 0xf)
                self.write_gcrpar('HELPER_SECCFG_PIXELSELECT', pselect)
                self.write_pcr()
                time.sleep(0.001)

    def pixels_mask(self, sections = 0xffff, columns = 0xffff, prs=None, master=None, pixels = 0xf):
        self.pixels_cfg(0b11, sections, columns, prs, master, pixels)

    # Injection
    def send_tp(self, pulses=1, t_on=1000, t_off=1000):
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
        self.send_controller_command('syncTX', onehot(lanes))
        ret, response = self.send_controller_command('readTxState', 0)

        lanes = []
        for i in range(16):
            if ((response >> i) & 0b1):
                lanes.append(i)

        return lanes
