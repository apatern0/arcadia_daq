import functools
import time
import logging
import math
import configparser
import os
import codecs
import json
import csv
import datetime
import matplotlib
import matplotlib.pyplot as plt
import tqdm

from .daq import Fpga, Chip, onecold
from .sequence import Sequence, SubSequence
from .data import ChipData, TestPulse

class TqdmLoggingHandler(logging.Handler):
    def __init__(self, level=logging.NOTSET):
        super().__init__(level)

    def emit(self, record):
        try:
            msg = self.format(record)
            tqdm.tqdm.write(msg)
            self.flush()
        except Exception:
            self.handleError(record)

class Test:
    """Test generator class. Contains helper functions and initialization
    methods to prep the chip for testing. The class also provides methods
    for its own data saving and loading.
    """
    logger = None
    fpga = None
    chip = None
    cfg = []
    gcrs = None

    chip_timestamp_divider = 0
    lanes_excluded = []

    def __init__(self):
        self.fpga = Fpga()
        self.chip = self.fpga.get_chip(0)
        self.sequence = Sequence(chip=self.chip)

        self.title = ''

        # Initialize Logger
        self.logger = logging.getLogger(__name__)
        if not self.logger.handlers:
            ch = TqdmLoggingHandler()
            formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
            ch.setFormatter(formatter)
            ch.setLevel(logging.WARNING)
            self.logger.addHandler(ch)

        self.result = None

        # Initialize Chip
        self.chip.logger = self.logger

    def load_cfg(self):
        """Loads chip-wide configuration from a chip.ini file
        """
        if not os.path.isfile("./chip.ini"):
            return False

        config = configparser.ConfigParser()
        config.read('./chip.ini')

        this_chip = 'id'+str(self.chip.id)

        if this_chip not in config.sections():
            return False

        self.chip.cfg = config[this_chip]

        if 'lanes_masked' in self.chip.cfg:
            stm = self.chip.cfg['lanes_masked'].split(",")
            print("Masking sections: %s" % str(stm))
            stm = [int(x) for x in stm]
            self.chip.lanes_masked = stm

    def set_timestamp_resolution(self, res_s, update_hw=True):
        """Configures the timestamp resolution on both the chip and the FPGA.
        :param int res_s: Timestamp resolution in seconds
        """

        chip_clock_divider = math.log((self.fpga.clock_hz * res_s)/10, 2)
        if math.floor(chip_clock_divider) != chip_clock_divider:
            raise ValueError('Chip Clock Divider can\'t be set to non-integer value: %.3f' % chip_clock_divider)
        chip_clock_divider = math.floor(chip_clock_divider)
        self.logger.info('Chip clock divider: %d', chip_clock_divider)

        fpga_clock_divider = (self.fpga.clock_hz * res_s) -1
        if math.floor(fpga_clock_divider) != fpga_clock_divider:
            raise ValueError('FPGA Clock Divider can\'t be set to non-integer value: %.3f' % fpga_clock_divider)
        fpga_clock_divider = math.floor(fpga_clock_divider)
        self.logger.info('Fpga clock divider: %d', fpga_clock_divider)

        Chip.ts_us = res_s*1E6

        self.chip_timestamp_divider = chip_clock_divider

        if update_hw:
            self.chip.write_gcrpar('TIMING_CLK_DIVIDER', chip_clock_divider)
            self.chip.set_timestamp_period(fpga_clock_divider)
            self.timestamp_sync()

    def chip_init(self):
        """Common chip initialization settings
        """
        self.chip.enable_readout(0)
        self.chip.hard_reset()
        self.chip.reset_subsystem('chip', 1)
        self.chip.reset_subsystem('chip', 2)
        self.chip.write_gcrpar('READOUT_CLK_DIVIDER', 0)
        self.chip.write_gcrpar('TIMING_CLK_DIVIDER', self.chip_timestamp_divider)
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
        self.chip.calibrate_deserializers()
        synced = self.chip.sync()
        self.chip.normal_mode()
        self.chip.enable_readout(synced)

        print("Synchronized lanes: %s" % synced)

        return synced

    def check_stability(self, trials=8):
        """Ensures that the lanes are stable. Assumes that no data
        are being sent from the chip, and checks that no data is
        received. If the test fails, it is likely that there are
        synchronization problems in the FPGA lanes or chip bugs.

        :param int trials: Number of trials before failing
        """
        for _ in range(trials):
            self.chip.packets_reset()
            self.chip.packets_reset()
            packets_in_fifo = self.chip.packets_count()
            if packets_in_fifo == 0:
                return True

            time.sleep(0.01)
            continue

        return False

    def stabilize_lanes(self, sync_not_calibrate=True, iterations=5):
        """Performs a series of checks on the lanes to try to automatically
        fix the noisy/dead ones, leaving the chip on a testable state.

        :param int sync_not_calibrate: Don't perform lane calibration
        :param int iterations: Number of consecutive stabilization trials
        """
        autoread = self.chip.packets_read_active()
        self.chip.packets_read_stop()
        self.chip.enable_readout(0xffff)

        lanes_noisy = []
        lanes_unsync = []
        lanes_dead = []
        lanes_invalid = []
        iteration = 0

        for iteration in range(iterations):
            print(f"Stabilization trial {iteration}/{iterations}...")

            for _ in range(iterations):
                if sync_not_calibrate:
                    self.resync(0xffff)
                else:
                    self.chip.calibrate_deserializers()

                self.chip.packets_reset()
                self.chip.packets_reset()

                print("\tPerforming stabilization...")
                if self.check_stability():
                    break

                # Get a sample of the noisy data
                try:
                    readout = self.chip.readout(30)
                except StopIteration:
                    readout = []

                # Distinguish between noisy and unsync
                read = 0
                elaborated = SubSequence(readout)
                for pkt in elaborated:
                    if isinstance(pkt, ChipData):
                        read += 1
                        if pkt.ser == pkt.sec and pkt.ser not in lanes_noisy:
                            lanes_noisy.append(pkt.ser)
                        elif pkt.ser not in lanes_unsync:
                            lanes_unsync.append(pkt.ser)

                if read == 0:
                    break

                print("\t\tNoisy lanes: %s\n\t\tUnsync lanes: %s\n\t\tRetrying." % (str(lanes_noisy), str(lanes_unsync)))

            tomask = list(set(lanes_noisy + lanes_unsync))
            if len(tomask) > 0:
                tomask.sort()
                print("\tDisabling noisy/unsync lanes: %s" % (tomask))
                self.chip.enable_readout(onecold(tomask, 0xffff))

            print("\tLines are silent.")

            # Are the lanes alive?
            self.chip.injection_enable(0xffff)
            self.chip.injection_digital(0xffff)
            self.chip.noforce_injection(0xffff)
            self.chip.noforce_nomask(0xffff)
            self.chip.pixels_mask()
            self.chip.pcr_cfg(0b01, 0xffff, [0], [0], [0], 0b1)

            # There still silence?
            if not self.check_stability():
                print("\tLines are still noisy! Trying again...")
                continue

            print("\tChecking sample data packets for errors...")

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
                print(f"\tMissing data from lanes: " + str(lanes_dead))

            if len(lanes_invalid) != 0:
                ready = False
                print(f"\tFound invalid data from lanes: " + str(lanes_invalid))

            if ready:
                print("\t... all is good.")
                break

        if iteration > iterations:
            raise RuntimeError('Unable to mask noisy lanes. Aborting.')

        Test.lanes_excluded = list(set(self.chip.lanes_masked + lanes_dead + lanes_invalid + lanes_noisy + lanes_unsync))
        if Test.lanes_excluded == list(range(16)):
            raise RuntimeError('All the lanes are masked! Unable to proceed!')

        if len(lanes_dead) != 0:
            print('Tests will proceed with the following dead lanes: %s' % lanes_dead)

        if len(lanes_invalid) != 0:
            print('Marking as dead the lanes that couldn\'t be stabilized: %s' % lanes_invalid)

        self.chip.lanes_masked = Test.lanes_excluded
        self.chip.enable_readout(0xffff)

        if autoread:
            self.chip.packets_read_start()

    def timestamp_sync(self):
        """Synchronizes Chip and FPGA timestamp counters
        """
        self.chip.set_timestamp_delta(0)

        self.chip.pixels_mask()
        self.chip.pcr_cfg(0b01, 0x000f, [0], [0], [0], 0xF)
        self.chip.noforce_injection()
        self.chip.noforce_nomask()

        self.chip.packets_reset()
        self.chip.send_tp(1)
        elaborated = SubSequence(self.chip.readout(100))
        tp = elaborated.get_tps()
        data = elaborated.get_data()

        if len(tp) == 0:
            self.logger.fatal("Sync procedure returned no Test Pulses. Check chip status. Dump:")
            elaborated.dump()
            print("\n")
            raise RuntimeError("Check previous CRITICAL error")

        if len(data) == 0:
            self.logger.fatal("Sync procedure returned no Data Packets. Check chip status. Dump:")
            elaborated.dump()
            print("\n")
            raise RuntimeError("Check previous CRITICAL error")

        tp = tp[0]
        data = data[0]

        ts_chip = data.ts
        ts_fpga = data.ts_fpga & 0xff
        ts_delta = ts_fpga - ts_chip

        self.logger.info("Test Pulse timestamp: 0x%x" % tp.ts)
        self.logger.info("Data timestamp: 0x%x (FPGA) 0x%x (CHIP)" % (ts_fpga, ts_chip))

        self.logger.info("Chip event anticipates fpga event, thus ts_fpga must be decreased to reach ts_chip")
        self.logger.info("ts_fpga - X = ts_chip -> X = ts_fpga - ts_chip = 0x%x" % (ts_delta))

        self.logger.info("New Data timestamp: 0x%x (FPGA) 0x%x (CHIP)" % (ts_fpga-ts_delta, ts_chip))

        self.chip.set_timestamp_delta(ts_delta)

        self.logger.info("Going again")

        self.chip.packets_reset()
        self.chip.send_tp(1)
        elaborated = SubSequence(self.chip.readout(100))
        tp = elaborated.get_tps()
        data = elaborated.get_data()

        tp = tp[0]
        data = data[0]
        ts_chip = data.ts
        ts_fpga = data.ts_fpga & 0xff
        ts_delta = ts_fpga - ts_chip

        self.logger.warning("Timestamp alignment: FPGA: %x CHIP: %x DELTA: %x", ts_fpga, ts_chip, ts_delta)

    def initialize(self, sync_not_calibrate=True, auto_read=True, iterations=2):
        """Perform default test and chip initialization routines.

        :param bool sync_not_calibrate: Avoid to perform lanes calibration
        :param bool auto_read: Enable automatic packet readout from the FPGA
        """
        if not self.fpga.connected:
            self.fpga.connect()

        # Load configuration
        self.load_cfg()

        self.chip.enable_readout(0xffff)
        self.chip.clock_enable(0xffff)
        self.chip.read_enable(0xffff)
        self.chip.injection_enable(0xffff)

        saved_masked = self.chip.lanes_masked

        for i in range(4):
            ok = True
            self.chip.lanes_masked = saved_masked

            # Initialize chip
            lanes_synced = self.chip_init()

            to_mask = [item for item in list(range(16)) if item not in self.chip.lanes_masked]

            # Check and stabilize the lanes
            self.stabilize_lanes(sync_not_calibrate, iterations)

            try:
                self.set_timestamp_resolution(1E-6)
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
        """Temporary enables sync mode on the chip, and perform
        the lanes synchronization routing on the FPGA

        :param int lanes: (Optional) Lanes to perform synchronization on
        """
        self.chip.sync_mode()
        time.sleep(0.1)
        synced = self.chip.sync(lanes)
        self.chip.normal_mode()
        time.sleep(0.1)

        return synced

    @staticmethod
    def _filename(saveas):
        if os.path.exists(saveas):
            split = saveas.split('.')
            ext = ""
            if len(split) > 1:
                saveas = "".join(split[:-1])
                ext = split[-1]

            i = 1
            while True:
                filename = saveas + ("_%d" % i) + "." + ext
                if not os.path.exists(filename):
                    break

                i += 1

            saveas = filename

        return saveas

    def _run(self):
        raise NotImplementedError()

    def deserialize(self, serialized):
        raise NotImplementedError()

    def serialize(self):
        raise NotImplementedError()

    def run(self):
        """Saves the starting GCRs and runs the test
        """
        self.gcrs = self.chip.dump_gcrs(False)
        self._run()

    def savecsv(self, saveas=None):
        """Saves the GCR configuration and test results to file. If the filename is not
        provided, the results will be saved into date folders, and incrementally indexed
        timed files in those folders.

        :param string saveas: (Optional) File to save the results to
        """
        listed = []
        idx = 0

        if saveas is None:
            folder = "results__" + datetime.datetime.now().strftime("%d_%m_%Y")
            if not os.path.exists(folder):
                os.mkdir(folder)

            # Get run idx
            files = os.listdir(folder)
            last_idx = -1
            for filename in files:
                if not os.path.isfile(os.path.join(folder, filename)):
                    continue

                if not filename.startswith("run__"):
                    continue

                try:
                    nextunder = filename[5:].index("_")
                except ValueError:
                    continue

                idx = int(filename[5:(5+nextunder)])
                if idx > last_idx:
                    last_idx = idx

            idx = last_idx+1

            time = datetime.datetime.now().strftime("%H_%M_%S")
            saveas = os.path.join(folder, "run__" + str(idx) + "__" + time + ".csv")
        
            listed.append(self.gcrs if self.gcrs is not None else self.chip.dump_gcrs(False))
        else:
            if not os.path.exists(saveas):
                print("Unable to load %s. Not found." % saveas)
                return

        listed.extend(self.serialize())

        with codecs.open(saveas, 'a', encoding='utf-8') as csvfile:
            spamwriter = csv.writer(csvfile, delimiter=',')
            spamwriter.writerow(listed)

        return saveas 

    def save(self, saveas=None, extend_from=None):
        """Saves the GCR configuration and test results to file. If the filename is not
        provided, the results will be saved into date folders, and incrementally indexed
        timed files in those folders.

        :param string saveas: (Optional) File to save the results to
        """
        listed = []

        if extend_from is None:
            listed.append(self.gcrs if self.gcrs is not None else self.chip.dump_gcrs(False))
        else:
            if not os.path.exists(extend_from):
                print("Unable to load %s. Not found." % filename)
                return

            with codecs.open(extend_from, 'r', encoding='utf-8') as handle:
                try:
                    listed = json.loads(handle.read())
                except json.decoder.JSONDecodeError:
                    print("Unable to decode %s." % filename)
                    return

                if len(listed) == 0:
                    return
        
        listed.extend(self.serialize())

        idx = 0
        if saveas is None:
            folder = "results__" + datetime.datetime.now().strftime("%d_%m_%Y")
            if not os.path.exists(folder):
                os.mkdir(folder)

            # Get run idx
            files = os.listdir(folder)
            last_idx = -1
            for filename in files:
                if not os.path.isfile(os.path.join(folder, filename)):
                    continue

                if not filename.startswith("run__"):
                    continue

                try:
                    nextunder = filename[5:].index("_")
                except ValueError:
                    continue

                idx = int(filename[5:(5+nextunder)])
                if idx > last_idx:
                    last_idx = idx

            idx = last_idx+1

            time = datetime.datetime.now().strftime("%H_%M_%S")
            saveas = os.path.join(folder, "run__" + str(idx) + "__" + time + ".json")

        json.dump(listed, codecs.open(self._filename(saveas), 'w', encoding='utf-8'), separators=(',', ':'), sort_keys=True, indent=4)

        print("Test results and configuration saved in:\n%s" % saveas)
        return saveas 

    def load(self, filename):
        """Loads the GCR configuration and test results from a file.

        :param string filename: File to read the results from
        """
        if not os.path.exists(filename):
            print("Unable to load %s. Not found." % filename)
            return

        with codecs.open(filename, 'r', encoding='utf-8') as handle:
            try:
                contents = json.loads(handle.read())
            except json.decoder.JSONDecodeError:
                return

            if len(contents) == 0:
                return

            self.gcrs = contents.pop(0)

            self.deserialize(contents)

    def loadcsv(self, filename):
        """Loads the GCR configuration and test results from a file.

        :param string filename: File to read the results from
        """
        if not os.path.exists(filename):
            print("Unable to load %s. Not found." % filename)
            return

        with codecs.open(filename, 'r', encoding='utf-8') as handle:
            try:
                contents = json.loads(handle.read())
            except json.decoder.JSONDecodeError:
                return

            if len(contents) == 0:
                return

            self.gcrs = contents.pop(0)

            self.deserialize(contents)

    def _plot_points(self, fig, ax, **kwargs):
        raise NotImplementedError()

    def _plot_heatmap(self, fig, ax, **kwargs):
        raise NotImplementedError()

    def plot(self, show=True, saveas=None, notes=None):
        raise NotImplementedError()

    def _plot_footer(self, fig, show, saveas, title, notes, saveas_append=""):
        title = self.title + (title if title is not None else '')

        fig.suptitle(title)

        fig.tight_layout()

        if notes is not None:
            plt.text(0.5, 0.0, notes, fontsize=8, ha="center", transform=plt.gcf().transFigure)
            plt.subplots_adjust(bottom=0.2)

        if saveas is not None:
            fig.savefig(self._filename(saveas+saveas_append+'.pdf'), bbox_inches='tight')

        if show:
            matplotlib.interactive(True)
            plt.show()
        else:
            matplotlib.interactive(False)
            plt.close(fig)

    def plot_heatmap(self, show=True, saveas=None, title=None, notes=None, **kwargs):
        if not show and saveas is None:
            raise ValueError('Either show or save the plot!')

        fig, ax = plt.subplots()

        image = self._plot_heatmap(fig, ax, **kwargs)

        plt.colorbar(image, orientation='horizontal')

        self._plot_footer(fig, show, saveas, title, notes)

    def plot_points(self, show=True, saveas=None, title=None, notes=None, **kwargs):
        if not show and saveas is None:
            raise ValueError('Either show or save the plot!')

        fig, ax = plt.subplots()

        self._plot_points(fig, ax, **kwargs)

        ax.legend()
        ax.grid()

        self._plot_footer(fig, show, saveas, title, notes)

    def close_plots(self):
        plt.close('all')
