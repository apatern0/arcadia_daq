import time, logging, math
import matplotlib
import threading
import subprocess, signal
import configparser
import os
import traceback
from tqdm import tqdm

from . import bcolors
from .daq import *
from .analysis import *

plt = matplotlib.pyplot

class ChipListen:
    chip = None
    active = False

    def __init__(self, chip):
        self.chip = chip

    def __enter__(self):
        self.start()

    def start(self):
        self.active = True
        self.chip.packets_read_start()

    def _stop(self):
        self.chip.packets_read_stop()

    def stop(self):
        self._stop()
        self.active = False


class Test:
    logger = None
    fpga = None
    chip = None

    reader = None
    cfg = []

    chip_timestamp_divider = 0

    def __init__(self):
        self.fpga = Fpga()
        self.chip = self.fpga.get_chip(0)
        self.sequence = Sequence()
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

        # Add Listener
        self.reader = ChipListen(self.chip)

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
        for i in range(trials):
            self.chip.packets_reset()
            self.chip.packets_reset()
            packets_in_fifo = self.chip.packets_count()
            if packets_in_fifo != 0:
                time.sleep(0.01)
                continue
            else:
                return True

        return False

    def stabilize_lanes(self, sync=None, iterations=5):
        if self.reader.active:
            self.reader.stop()

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
                    readout = self.readout(30)
                except StopIteration:
                    silence = True
                    break

                # Distinguish between noisy and unsync
                this_lanes_noisy = []
                this_lanes_unsync = []
                read = 0
                elaborated = Sequence(readout)
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
                readout = self.readout(40)
            except StopIteration:
                readout = []

            lanes_ok = []
            lanes_invalid = []
            elaborated = Sequence(readout)
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
            readout = self.readout(30)
        except StopIteration:
            return False

        elaborated = Sequence(readout)

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
                    self.reader.start()

                return

        raise RuntimeError('Unable to receive data from the chip!')

    def resync(self, lanes=0xffff):
        self.chip.sync_mode()
        time.sleep(0.1)
        synced = self.chip.sync(lanes)
        self.chip.normal_mode()
        time.sleep(0.1)

        return synced

    def readout(self, max_packets=None, fail_on_error=True, timeout=5):
        for _ in range(timeout):
            in_fifo = self.chip.packets_count()
            if in_fifo != 0:
                break

            time.sleep(0.1)

        if in_fifo == 0:
            raise StopIteration()

        if self.reader.active:
            return self.chip.packets_read()


        packets_to_read = min(in_fifo, max_packets) if max_packets is not None else in_fifo
        readout = self.chip.packets_read(packets_to_read)

        if(len(readout) < packets_to_read and fail_on_error):
            raise ValueError(f'Readout {readout} packets out of {packets_to_read}')

        return readout

    def readout_until(self, max_packets=None, timeout=2):
        r = []
        saved = 0
        while True:
            print("Read!")
            to_read = (max_packets-saved) if max_packets is not None else None
            try:
                tmp = self.readout(to_read, timeout=timeout)
            except StopIteration:
                break

            saved += len(tmp)
            r.extend(tmp)

        print("Readut %d packets", len(r))
        return r

    def elaborate_until(self, word, payload=None, timeout=5, tries=20):
        results = Results()

        for _ in range(tries):
            results.extend(self.sequence.pop_until(word, payload))

            if not results.incomplete:
                return results

            # Incomplete readout, try to read some more.
            try:
                r = self.readout(timeout=timeout)
            except StopIteration:
                return results

            # Elaborate
            self.sequence = Sequence(r)

        return results

    def save(self, saveas):
        fn = saveas+".npy"
        if os.path.exists(fn):
            i = 1
            while True:
                fn = saveas + ("_%d" % i) + ".npy"
                if not os.path.exists(fn):
                    break

                i += 1

        np.save(fn, self.result)
