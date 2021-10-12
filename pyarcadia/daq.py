import os, sys, argparse, time, logging
import numpy as np
import matplotlib.pyplot as plt

from DAQ_pybind import DAQBoard_comm, set_ipbus_loglevel
set_ipbus_loglevel(0)

def onehot(bits, base=0x0000):
    if(isinstance(bits, list)):
        onehot = 0x0000
        for item in bits:
            onehot = onehot | (0xffff & (1 << item));

        bits = onehot

    return bits | base

def onecold(bits, base=0xffff):
    return ~onehot(bits) & base

class Daq(DAQBoard_comm):
    """ Communicate with Chip """
    chip_id = 'id0'
    sections_to_mask = 0

    def init_connection(self, xml_file=None):
        if xml_file is None:
            xml_file = os.path.abspath(os.path.join(__file__, "../../cfg/connection.xml"))

        try:
            super().__init__(xml_file, 'kc705', 0)
        except:
            raise RuntimeError('Failed to instantiate DAQBoard_comm')
            sys.exit(255)

    # Overriding some methods to improve usability

    def write_gcrpar(self, gcrpar, value):
        self.logger.debug("Writing GCR_PAR[%s] = 0x%x" % (gcrpar, value))
        super().write_gcrpar(self.chip_id, gcrpar, value)

    def write_gcr(self, gcr, value):
        self.logger.debug("Writing GCR[%2d] = 0x%x" % (gcr, value))
        super().write_gcr(self.chip_id, gcr, value)

    def write_icr(self, icr, value):
        self.logger.debug("Writing ICR%1d = %x" % (icr, value))
        super().write_icr(self.chip_id, 'ICR%1d' % icr, value)

    def send_controller_command(self, cmd, value=0):
        resp = super().send_controller_command('controller_'+self.chip_id, cmd, value)
        return resp

    def get_fifo_occupancy(self):
        return super().get_fifo_occupancy(self.chip_id)

    def enable_readout(self, sections):
        sections = onehot(sections) & onecold(self.sections_to_mask)
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

    def calibrate_serializers(self):
        self.sync_mode()
        response = self.cal_serdes_idealy('controller_'+self.chip_id)
        self.normal_mode()

        lanes = []
        for i in range(16):
            if ((response >> i) & 0b1):
                lanes.append(i)

        return lanes

    def set_timestamp_period(self, period):
        period = period
        self.send_controller_command('writeTimeStampPeriod', (period & 0xffff))

    def __init__(self, xml_file=None):
        self.init_connection(xml_file)

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
                pselect = (subpr << 4) | (onehot(pixels) & 0xf)
                self.write_gcrpar('HELPER_SECCFG_PIXELSELECT', pselect)
                self.write_pcr()

    def pixels_mask(self, sections = 0xffff, columns = 0xffff, prs=None, master=None, pixels = 0xf):
        self.pixels_cfg(0b11, sections, columns, prs, master, pixels)

    # Injection
    def send_tp(self, pulses=1, t_on=1000, t_off=1000):
        t_on = t_on-2 if (t_on > 2) else t_on
        t_off = t_off-1 if (t_off > 1) else t_off
        super().send_pulse(self.chip_id, int(t_on), int(t_off), pulses)

    # FPGA commands
    def sync(self):
        self.send_controller_command('syncTX', 0xffff)
        ret, response = self.send_controller_command('readTxState', 0)

        lanes = []
        for i in range(16):
            if ((response >> i) & 0b1):
                lanes.append(i)

        return lanes

    def reset_fifo(self):
        super().reset_fifo(self.chip_id)

        time.sleep(1)

    def listen(self, packets=128):
        self.daq_read(self.chip_id, 'dout', packets)
     
        return self.get_packet_count(self.chip_id)

    def listen_loop(self, stopafter=0, timeout=0, idletimeout=0):
        if (self.start_daq(self.chip_id, stopafter, timeout, idletimeout, 'dout') != 0):
            raise Exception('Fail to start DAQ')

        self.wait_daq_finished()
     
        return self.get_packet_count(self.chip_id)
