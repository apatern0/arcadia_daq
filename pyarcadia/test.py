import functools
import time
import logging
import math
import configparser
import os
import matplotlib
import matplotlib.pyplot as plt
import numpy as np

from .daq import Fpga, onecold
from .sequence import Sequence, SubSequence
from .data import ChipData, TestPulse

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

            if not show and saveas is None:
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

            if saveas is not None:
                filename = saveas+".pdf"
                if os.path.exists(filename):
                    i = 1
                    while True:
                        filename = saveas + ("_%d" % i) + ".pdf"
                        if not os.path.exists(filename):
                            break

                        i += 1

                fig.savefig(filename, bbox_inches='tight')

            if show:
                matplotlib.interactive(True)
                plt.show()
            else:
                matplotlib.interactive(False)
                plt.close(fig)

        return wrapper
    return decorator

class Test:
    logger = None
    fpga = None
    chip = None

    cfg = []

    chip_timestamp_divider = 0

    def __init__(self):
        self.fpga = Fpga()
        self.chip = self.fpga.get_chip(0)
        self.sequence = Sequence(chip=self.chip, autoread=True)
        self.logger = logging.getLogger(__name__)

        # Load configuration
        self.load_cfg()

        # Initialize Chip
        self.fpga.init_connection()
        self.chip.logger = self.logger
        if 'lanes_masked' in self.chip.cfg:
            stm = self.chip.cfg['lanes_masked'].split(",")
            print("Masking sections: %s" % str(stm))
            stm = [int(x) for x in stm]
            self.chip.lanes_masked = stm

        # Initialize Logger
        ch = logging.StreamHandler()
        formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
        ch.setFormatter(formatter)
        #ch.setLevel(logging.WARNING)
        self.logger.addHandler(ch)

        self.result = None
        self.lanes_excluded = []

    def load_cfg(self):
        if not os.path.isfile("./chip.ini"):
            return False

        config = configparser.ConfigParser()
        config.read('./chip.ini')

        this_chip = 'id'+str(self.chip.id)
        
        if this_chip not in config.sections():
            return False

        self.chip.cfg = config[this_chip]

    def set_timestamp_resolution(self, res_s):
        clock_hz = 80E6

        chip_clock_divider = math.log( (clock_hz * res_s)/10, 2)
        if( math.floor(chip_clock_divider) != chip_clock_divider ):
            raise ValueError('Chip Clock Divider can\'t be set to non-integer value: %.3f' % chip_clock_divider)
        chip_clock_divider = math.floor(chip_clock_divider)
        self.logger.info('Chip clock divider: %d' % chip_clock_divider)

        fpga_clock_divider = (clock_hz * res_s) -1
        if( math.floor(fpga_clock_divider) != fpga_clock_divider ):
            raise ValueError('FPGA Clock Divider can\'t be set to non-integer value: %.3f' % fpga_clock_divider)
        fpga_clock_divider = math.floor(fpga_clock_divider)
        self.logger.info('Fpga clock divider: %d' % fpga_clock_divider)

        self.ts_us = res_s/1E6

        self.chip.write_gcrpar('TIMING_CLK_DIVIDER', chip_clock_divider)
        self.chip.set_timestamp_period(fpga_clock_divider)

        self.chip_timestamp_divider = chip_clock_divider

    # Global
    def chip_init(self):
        self.chip.enable_readout(0)
        self.chip.hard_reset()
        self.chip.reset_subsystem('chip', 1)
        self.chip.reset_subsystem('chip', 2)
        self.chip.write_gcr(0, (0xFF00) | (self.chip_timestamp_divider << 8))
        self.chip.reset_subsystem('per', 1)
        self.chip.reset_subsystem('per', 2)
        self.chip.injection_digital()
        self.chip.injection_enable()
        self.chip.clock_enable()
        self.chip.read_enable()
        self.chip.force_injection()
        self.chip.force_nomask()
        self.chip.reset_subsystem('per', 1)
        self.chip.reset_subsystem('per', 2)
        self.chip.pixels_mask()
        self.chip.write_gcrpar('LVDS_STRENGTH', 0b111)
        self.chip.sync_mode()
        time.sleep(1)
        synced = self.chip.sync()
        self.chip.normal_mode()
        self.chip.enable_readout(synced)

        print("Synchronized lanes:", end=''); print(synced)

        return synced
        
    def check_stability(self, trials=8):
        for _ in range(trials):
            self.chip.packets_reset()
            self.chip.packets_reset()
            packets_in_fifo = self.chip.packets_count()
            if packets_in_fifo == 0:
                return True

            time.sleep(0.01)
            continue

        return False

    def stabilize_lanes(self, sync=None, iterations=5):
        autoread = self.chip.packets_read_active()
        self.chip.packets_read_stop()

        lanes_noisy = []
        iteration = 0
        while iteration < iterations:
            print(f"Synchronization iteration {iteration}...")
            silence = False
            while iteration < 5:
                self.chip.enable_readout(onecold(lanes_noisy, 0xffff))
                self.chip.packets_reset()
                self.chip.packets_reset()

                if self.check_stability():
                    silence = True
                    break

                # Get a sample of the noisy data
                try:
                    readout = self.chip.readout(30)
                except StopIteration:
                    silence = True
                    break

                # Distinguish between noisy and unsync
                this_lanes_noisy = []
                this_lanes_unsync = []
                read = 0
                print("Noisy uncync sequence")
                elaborated = SubSequence(readout)
                for pkt in elaborated:
                    if isinstance(pkt, ChipData):
                        read += 1
                        if pkt.ser == pkt.sec and pkt.ser not in this_lanes_noisy:
                            this_lanes_noisy.append(pkt.ser)
                        elif pkt.ser not in this_lanes_unsync:
                            this_lanes_unsync.append(pkt.ser)

                if read == 0:
                    silence = True
                    break

                print("\tNoisy lanes: %s\n\tUnsync lanes: %s" % (str(this_lanes_noisy), str(this_lanes_unsync)))

                if sync == 'sync':
                    self.resync(0xffff)
                else:
                    self.chip.calibrate_deserializers()

                lanes_noisy.extend(this_lanes_noisy)

                iteration += 1

            if not silence:
                continue

            print("\tLines are silent.")

            # Are the lanes alive?
            self.chip.injection_enable(0xffff)
            self.chip.injection_digital(0xffff)
            self.chip.noforce_injection(0xffff)
            self.chip.noforce_nomask(0xffff)
            self.chip.pixels_mask()
            self.chip.pixels_cfg(0b01, 0xffff, [0], [0], [0], 0b1)

            # There still silence?
            if not self.check_stability():
                print("\tStability lost after injection enabling")
                continue

            # Send a TP, expect a packet per stable lane
            self.chip.send_tp(1)
            try:
                readout = self.chip.readout(40)
            except StopIteration:
                readout = []

            lanes_ok = []
            lanes_invalid = []
            elaborated = SubSequence(readout)
            for packet in elaborated:
                if not isinstance(packet, ChipData):
                    continue

                if packet.ser != packet.sec or packet.col != 0 or packet.corepr != 0:
                    if packet.ser not in lanes_invalid:
                        lanes_invalid.append(packet.ser)
                        continue

                if packet.ser not in lanes_ok and packet.ser not in lanes_invalid:
                    lanes_ok.append(packet.ser)

            exclude = self.chip.lanes_masked + lanes_ok + lanes_noisy
            lanes_dead = [x for x in range(16) if x not in exclude]

            ready = True
            if len(lanes_dead) != 0:
                ready = False
                print(f"\tIteration {iteration}. Missing data from lanes: " + str(lanes_dead))

            if len(lanes_invalid) != 0:
                ready = False
                print(f"\tIteration {iteration}. Found invalid data from lanes: " + str(lanes_invalid))

            if ready:
                print("\t... but not deaf!")
                break

            if sync == 'sync':
                self.resync(0xffff)
            else:
                self.chip.calibrate_deserializers()

            iteration += 1

        if len(lanes_dead) != 0:
            print('Tests will proceed with the following dead lanes: %s' % lanes_dead)

        if len(lanes_invalid) != 0:
            raise RuntimeError('Unable to stabilize the lanes!')

        self.lanes_excluded = self.chip.lanes_masked + lanes_dead
        if autoread:
            self.chip.packets_read_start()

    def timestamp_sync(self):
        self.chip.set_timestamp_delta(0)

        self.chip.pixels_mask()
        self.chip.pixels_cfg(0b01, 0x000f, [0], [0], [0], 0xF)
        self.chip.noforce_injection()
        self.chip.noforce_nomask()

        self.chip.packets_reset()
        self.chip.send_tp(1)
        time.sleep(0.1)
        try:
            readout = self.chip.readout(30)
        except StopIteration:
            return False

        elaborated = SubSequence(readout)

        tp = filter(lambda x:(type(x) == TestPulse), elaborated)
        data = filter(lambda x:(type(x) == ChipData), elaborated)

        try:
            tp = next(tp)
        except StopIteration:
            self.logger.fatal("Sync procedure returned no Test Pulses. Check chip status. Dump:")
            elaborated.dump()
            print("\n")
            raise RuntimeError("Check previous CRITICAL error")

        try:
            data = next(data)
        except StopIteration:
            self.logger.fatal("Sync procedure returned no Data Packets. Check chip status. Dump:")
            elaborated.dump()
            print("\n")
            raise RuntimeError("Check previous CRITICAL error")

        ts_tp = tp.ts
        ts_fpga = data.ts_fpga
        ts_tp_lsb = (ts_tp & 0xff)
        ts_chip = data.ts
        if(ts_tp_lsb < ts_chip):
            ts_tp_lsb = (1<<8) | ts_tp_lsb

        ts_delta = ts_tp_lsb - ts_chip

        self.logger.info("Test Pulse timestamp: 0x%x" % ts_tp)
        self.logger.info("Data timestamp: 0x%x (FPGA) 0x%x (CHIP)" % (ts_fpga, ts_chip))

        self.logger.info("Chip event anticipates fpga event, thus ts_fpga must be decreased to reach ts_chip")
        self.logger.info("ts_fpga - X = ts_chip -> X = ts_fpga - ts_chip = 0x%x" % (ts_delta))

        self.logger.info("New Data timestamp: 0x%x (FPGA) 0x%x (CHIP)" % (ts_fpga-ts_delta, ts_chip))

        self.chip.set_timestamp_delta(ts_delta)

    def initialize(self, sync=None, auto_read=True):
        for i in range(4):
            ok = True

            # Initialize chip
            lanes_synced = self.chip_init()
            #to_mask = [item for item in list(range(16)) if item not in (lanes_synced + self.chip.lanes_masked)]
            to_mask = [item for item in list(range(16)) if item not in self.chip.lanes_masked]

            # Check and stabilize the lanes
            self.stabilize_lanes(sync=sync, iterations=2)

            try:
                self.timestamp_sync()
            except RuntimeError:
                ok = False
                self.logger.warning("Initialization trial %d KO. Re-trying...", i)

            if ok:
                if auto_read:
                    self.chip.packets_reset()
                    self.chip.packets_read_start()

                return

        raise RuntimeError('Unable to receive data from the chip!')

    def resync(self, lanes=0xffff):
        self.chip.sync_mode()
        time.sleep(0.1)
        synced = self.chip.sync(lanes)
        self.chip.normal_mode()
        time.sleep(0.1)

        return synced

    def save(self, saveas):
        filename = saveas + ".npy"
        if os.path.exists(filename):
            i = 1
            while True:
                filename = saveas + ("_%d" % i) + ".npy"
                if not os.path.exists(filename):
                    break

                i += 1

        np.save(filename, self.result)
