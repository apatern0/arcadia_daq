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
            show = kwargs['show']
            saveas = kwargs['saveas']

            if(show == False and saveas == None):
                raise ValueError('Either show or save the plot!')
        
            fig, ax = plt.subplots()

            image = f(*args, **kwargs, ax=ax)

            ax.set(xlabel=axes[0], ylabel=axes[1], title=title)

            ax.grid()
            if isinstance(image, matplotlib.lines.Line2D) and ax.get_label() is not '':
                ax.legend()
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

class DaqListen:
    daq = None
    active = False

    def __init__(self, daq):
        self.daq = daq

    def __enter__(self):
        self.start()

    def __del__(self):
        self.stop()

    def __exit__(self, exc_type, exc_value, exc_traceback):
        self.stop()

    def start(self):
        self.active = True
        self.daq.listen_loop()

    def stop(self):
        self.active = False
        self.daq.stop_daq(self.daq.chip_id)

class Test:
    logger = None
    daq = None
    analysis = None

    reader = None
    cfg = []

    chip_timestamp_divider = 0

    def __init__(self, auto_read=True):
        self.daq = Daq()
        self.analysis = DataAnalysis()
        self.logger = logging.getLogger(__name__)
        
        # Load configuration
        self.load_cfg()

        # Initialize Daq
        self.daq.init_connection()
        self.daq.logger = self.logger
        if 'sections_to_mask' in self.cfg:
            stm = self.cfg['sections_to_mask'].split(",")
            print("Masking sections: ", end=""); print(stm)
            stm = [int(x) for x in stm]
            self.daq.sections_to_mask = stm

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
        self.reader = DaqListen(self.daq)

    def __del__(self):
        if self.reader is not None:
            self.reader.stop()

    def load_cfg(self):
        if not os.path.isfile("./chip.ini"):
            return False

        config = configparser.ConfigParser()
        config.read('./chip.ini')

        if self.daq.chip_id not in config.sections():
            return False

        self.cfg = config[self.daq.chip_id]

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

        self.daq.write_gcrpar('TIMING_CLK_DIVIDER', chip_clock_divider)
        self.daq.set_timestamp_period(fpga_clock_divider)

        self.chip_timestamp_divider = chip_clock_divider

    # Global
    def chip_init(self):
        self.daq.enable_readout(0)
        self.daq.hard_reset()
        self.daq.reset_subsystem('chip', 1)
        self.daq.reset_subsystem('chip', 2)
        self.daq.write_gcr(0, (0xFF00) | (self.chip_timestamp_divider << 8))
        self.daq.reset_subsystem('per', 1)
        self.daq.reset_subsystem('per', 2)
        self.daq.injection_digital()
        self.daq.injection_enable()
        self.daq.clock_enable()
        self.daq.read_enable()
        self.daq.force_injection()
        self.daq.force_nomask()
        self.daq.reset_subsystem('per', 1)
        self.daq.reset_subsystem('per', 2)
        self.daq.pixels_mask()
        self.daq.sync_mode()
        time.sleep(1)
        synced = self.daq.sync()
        self.daq.normal_mode()
        self.daq.enable_readout(synced)

        print("Synchronized lanes:", end=''); print(synced)

        return synced
        
    def check_stability(self):
        for i in range(8):
            self.daq.reset_fifo()
            self.daq.clear_packets()
            packets_in_fifo = self.daq.get_fifo_occupancy()
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
        read = -1
        while read != 0 and iteration < 5:
            self.daq.enable_readout(onecold(to_mask, 0xffff))
            self.daq.reset_fifo()
            self.daq.clear_packets()
            read = 0

            if self.check_stability():
                break

            # Get a sample of the noisy data
            analyzed = self.readout(30)
            if analyzed == 0:
                break

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
                break

            print(f"Iteration {iteration}. Found {read} Packets from:")
            print("\tNoisy lanes: %s" % str(noisy_lanes))
            print("\tUnsync lanes: %s" % str(unsync_lanes))

            print("Synchronizing unsynchronized lanes, masking noisy ones...")
            self.resync(unsync_lanes)
            to_mask.extend(noisy_lanes)
            iteration += 1

        if read == 0:
            self.daq.sections_to_mask.extend(to_mask)
        else:
            raise RuntimeError('Unable to stabilize the lanes!')

    def timestamp_sync(self):
        self.daq.pixels_mask()
        self.daq.noforce_injection()
        self.daq.noforce_nomask()

        self.daq.set_timestamp_delta(0)
        self.daq.pixels_cfg(0b01, 0x000f, [0], [0], [0], 0xF)
    
        self.daq.reset_fifo()
        self.daq.clear_packets()
        self.daq.send_tp(1)
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

        self.daq.set_timestamp_delta(ts_delta)

    def initialize(self, auto_read=True):
        for i in range(4):
            ok = True

            # Initialize chip
            lanes = self.chip_init()
            to_mask = [item for item in list(range(16)) if item not in lanes and item not in self.daq.sections_to_mask]
            self.daq.sections_to_mask.extend(to_mask)

            # Check and stabilize the lanes
            self.stabilize_lanes()

            try:
                self.timestamp_sync()
            except RuntimeError:
                ok = False
                self.logger.warning("Initialization trial %d KO. Re-trying...", i)

            if ok:
                if auto_read:
                    self.daq.reset_fifo()
                    self.reader.start()
    
                return

        raise RuntimeError('Unable to receive data from the chip!')

    def resync(self, lanes=0xffff):
        self.daq.sync_mode()
        time.sleep(0.1)
        synced = self.daq.sync(lanes)
        self.daq.normal_mode()
        time.sleep(0.1)

        return synced

    def readout(self, max_packets=None, fail_on_error=True, reset=True):
        if reset is True:
            self.analysis.cleanup()

        if not self.reader.active:
            in_fifo = self.daq.get_fifo_occupancy()

            if(in_fifo == 0):
                return 0

            packets_to_read = min(in_fifo, max_packets) if max_packets is not None else in_fifo
            packets_read = self.daq.readout_burst(packets_to_read)
    
            if(packets_read < packets_to_read and fail_on_error):
                raise ValueError(f'Readout {packets_read} out of {packets_to_read}')
        else:
            max_packets = None

        readout = self.daq.readout()
        analyzed = self.analysis.analyze(readout)

        return analyzed
