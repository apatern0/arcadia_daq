import time, logging, math
import matplotlib
import threading
import functools
import subprocess, signal
import configparser
from tqdm import tqdm

from . import bcolors
from .daq import *
from .analysis import *

plt = matplotlib.pyplot

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

            if isinstance(image, matplotlib.lines.Line2D) and ax.get_label() is not '':
                ax.legend()
                ax.grid()
            elif isinstance(image, matplotlib.image.AxesImage):
                plt.colorbar(image, orientation='horizontal')

            if(saveas != None):
                fig.savefig(f"{saveas}.pdf", bbox_inches='tight')

            if(show == True):
                matplotlib.interactive(True)
                plt.show()
            else:
                matplotlib.interactive(False)
                plt.close(fig)

        return wrapper
    return decorator

class ChipListen:
    chip = None
    active = False

    def __init__(self, chip):
        self.chip = chip

    def __enter__(self):
        self.start()

    def __del__(self):
        self.stop()

    def __exit__(self, exc_type, exc_value, exc_traceback):
        self.stop()

    def start(self):
        self.active = True
        self.chip.packets_read_start()

    def stop(self):
        self.active = False
        self.chip.packets_read_stop()

class Test:
    logger = None
    fpga = None
    chip = None
    analysis = None

    reader = None
    cfg = []

    chip_timestamp_divider = 0

    def __init__(self):
        self.fpga = Fpga()
        self.chip = self.fpga.get_chip(0)
        self.analysis = DataAnalysis()
        self.logger = logging.getLogger(__name__)

        # Load configuration
        self.load_cfg()

        # Initialize Chip
        self.fpga.init_connection()
        self.chip.logger = self.logger
        if 'sections_to_mask' in self.chip.cfg:
            stm = self.chip.cfg['sections_to_mask'].split(",")
            print("Masking sections: %s" % str(stm))
            stm = [int(x) for x in stm]
            self.chip.sections_to_mask = stm

        # Initialize DataAnalysis
        self.analysis = DataAnalysis()
        self.analysis.logger = self.logger

        # Initialize Logger
        ch = logging.StreamHandler()
        formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
        ch.setFormatter(formatter)
        #ch.setLevel(logging.WARNING)
        self.logger.addHandler(ch)

        # Add Listener
        self.reader = ChipListen(self.chip)

    def __del__(self):
        if self.reader is not None:
            self.reader.stop()

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

        self.analysis.ts_hz = 1/res_s

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
        
    def check_stability(self):
        for i in range(8):
            self.chip.packets_reset()
            self.chip.packets_reset()
            packets_in_fifo = self.chip.packets_count()
            if packets_in_fifo != 0:
                time.sleep(0.01)
                continue
            else:
                return True

        return False

    def stabilize_lanes(self):
        if self.reader.active:
            self.reader.stop()

        to_mask = []
        iteration = 0
        while iteration < 5:
            print(f"Synchronization iteration {iteration}...")
            silence = False
            while iteration < 5:
                self.chip.enable_readout(onecold(to_mask, 0xffff))
                self.chip.packets_reset()
                self.chip.packets_reset()

                if self.check_stability():
                    silence = True
                    break

                # Get a sample of the noisy data
                analyzed = self.readout(30)
                if analyzed == 0:
                    silence = True
                    break

                # Distinguish between noisy and unsync
                noisy_lanes = []
                unsync_lanes = []
                read = 0
                for pkt in self.analysis.packets:
                    if isinstance(pkt, PixelData):
                        read += 1
                        if pkt.ser == pkt.sec and pkt.ser not in noisy_lanes:
                            noisy_lanes.append(pkt.ser)
                        elif pkt.ser not in unsync_lanes:
                            unsync_lanes.append(pkt.ser)

                if read == 0:
                    silence = True
                    break

                print("\tNoisy lanes: %s\n\tUnsync lanes: %s" % (str(noisy_lanes), str(unsync_lanes)))

                self.resync(0xffff) ;#self.resync(unsync_lanes)
                to_mask.extend(noisy_lanes)

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
            self.readout(40)

            lanes_check = []
            lanes_invalid = []
            for packet in self.analysis.packets:
                if isinstance(packet, PixelData):
                    if packet.ser != packet.sec or packet.col != 0 or packet.corepr != 0:
                        if packet.ser not in lanes_invalid:
                            lanes_invalid.append(packet.ser)
                            continue

                    if packet.ser not in lanes_check and packet.ser not in lanes_invalid:
                        lanes_check.append(packet.ser)

            exclude = self.chip.sections_to_mask + lanes_check + to_mask
            missing = [x for x in range(16) if x not in exclude]

            ready = True
            if len(missing) != 0:
                ready = False
                print(f"\tIteration {iteration}. Missing data from lanes: " + str(missing))

            if len(lanes_invalid) != 0:
                ready = False
                print(f"\tIteration {iteration}. Found invalid data from lanes: " + str(lanes_invalid))

            if ready:
                print("\t... but not deaf!")
                break

            iteration += 1


        if not ready:
            print()
            raise RuntimeError('Unable to stabilize the lanes!')

    def timestamp_sync(self):
        self.chip.set_timestamp_delta(0)

        self.chip.pixels_mask()
        self.chip.pixels_cfg(0b01, 0x000f, [0], [0], [0], 0xF)
        self.chip.noforce_injection()
        self.chip.noforce_nomask()

        self.chip.packets_reset()
        self.chip.send_tp(1)
        time.sleep(0.5)
        self.readout(30)

        tp = filter(lambda x:(type(x) == TestPulse), self.analysis.packets)
        data = filter(lambda x:(type(x) == PixelData), self.analysis.packets)

        try:
            tp = next(tp)
        except StopIteration:
            self.logger.fatal("Sync procedure returned no Test Pulses. Check chip status. Dump:")
            self.analysis.dump()
            print("\n")
            raise RuntimeError("Check previous CRITICAL error")

        try:
            data = next(data)
        except StopIteration:
            self.logger.fatal("Sync procedure returned no Data Packets. Check chip status. Dump:")
            self.analysis.dump()
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

    def initialize(self, auto_read=True):
        for i in range(4):
            ok = True

            # Initialize chip
            lanes = self.chip_init()
            to_mask = [item for item in list(range(16)) if item not in lanes and item not in self.chip.sections_to_mask]
            self.chip.sections_to_mask.extend(to_mask)

            # Check and stabilize the lanes
            self.stabilize_lanes()

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

    def readout(self, max_packets=None, fail_on_error=True, reset=True):
        if reset is True:
            self.analysis.cleanup()

        if not self.reader.active:
            in_fifo = self.chip.packets_count()

            if in_fifo == 0:
                return 0

            packets_to_read = min(in_fifo, max_packets) if max_packets is not None else in_fifo
            readout = self.chip.packets_read(packets_to_read)
    
            if(len(readout) < packets_to_read and fail_on_error):
                raise ValueError(f'Readout {readout} packets out of {packets_to_read}')
        else:
            for _ in range(5):
                in_fifo = self.chip.packets_count()
                if in_fifo != 0:
                    break

                time.sleep(1)

            if in_fifo == 0:
                return 0
            
            readout = self.chip.packets_read()

        return self.analysis.analyze(readout)
