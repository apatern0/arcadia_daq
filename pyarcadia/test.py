import time, logging, math
import matplotlib
import threading
import functools
import subprocess, signal
import configparser
from tqdm import tqdm

from .daq import *
from .analysis import *

plt = matplotlib.pyplot

"""
def linearplot(axes, title):
    def decorator(f):
        @functools.wraps(f)
        def wrapper(*args, **kwargs):
            # can access all args
        return wrapper
    return decorator
"""

def customplot(axes, title):
    def decorator(f):
        @functools.wraps(f)
        def wrapper(*args, **kwargs):
            show = kwargs['show']
            saveas = kwargs['saveas']

            if(show == False and saveas == None):
                raise ValueError('Either show or save the plot!')
        
            fig, ax = plt.subplots()

            f(*args, **kwargs, ax=ax)

            ax.set(xlabel=axes[0], ylabel=axes[1], title=title)
            ax.grid()

            ax.legend()

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

class DaqListen(threading.Thread):
    chip_id = None
    process = None

    def __init__(self, chip_id='id0'):
        threading.Thread.__init__(self)
        self.chip_id = chip_id

    def __enter__(self):
        self.run()

    def run(self):
        print("Starting " + self.name)
        self.process = Daq()
        self.process.listen_loop()
        print("Exiting " + self.name)

    def __exit__(self, exc_type, exc_value, exc_traceback):
        self.stop()

    def stop(self):
        self.process.stop_daq(self.chip_id)

    def is_active(self):
        if self.process is None:
            return False
        elif self.process.poll() is None:
            return True

class DaqListenP(threading.Thread):
    launchable = None
    process = None

    def __init__(self, chip_id='id0'):
        threading.Thread.__init__(self)
        xml_file = os.path.abspath(os.path.join(__file__, "../../cfg/connection.xml"))
        self.launchable = ["bin/arcadia-cli", f"--daq={chip_id}", f"--conn={xml_file}"]

    def __enter__(self):
        self.run()

    def run(self):
        self.process = subprocess.Popen(self.launchable)

    def __exit__(self, exc_type, exc_value, exc_traceback):
        self.stop()

    def stop(self):
        self.process.send_signal(signal.SIGINT)

    def is_active(self):
        if self.process is None:
            return False
        elif self.process.poll() is None:
            return True

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

        if auto_read is True:
            self.reader = DaqListenP()
            self.daq.reset_fifo()
            self.daq.enable_readout(0)
            self.reader.start()

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

        print("Synchronized lanes:", end='')
        print(synced)

        return synced

    def timestamp_sync(self):
        self.daq.pixels_mask()
        self.daq.noforce_injection()
        self.daq.noforce_nomask()

        self.daq.set_timestamp_delta(0)
        self.daq.enable_readout(0xffff)
        self.daq.pixels_cfg(0b01, 0x000f, [0], [0], [0], 0xF)

        self.analysis.skip()
        self.daq.send_tp(1)

        self.readout(10)

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

    def initialize(self):
        for i in range(4):
            ok = True
            lanes = self.chip_init()
            try:
                self.timestamp_sync()
            except RuntimeError:
                ok = False
                self.logger.warning("Initialization trial %d KO. Re-trying..." % i)

            if(ok):
                return
        
        raise RuntimeError('Unable to receive data from the chip!')

    def resync(self):
        self.daq.sync_mode()
        time.sleep(0.1)
        synced = self.daq.sync()
        self.daq.normal_mode()

        return synced

    def readout(self, max_packets=None, fail_on_error=True):
        self.analysis.cleanup()
        in_fifo = self.daq.get_fifo_occupancy()

        if(in_fifo == 0):
            return 0

        to_read = min(in_fifo, max_packets) if max_packets is not None else in_fifo
        readout = self.daq.listen_loop(to_read, 5, 1)

        if(readout != to_read and fail_on_error):
            raise ValueError(f'Readout {readout} out of {to_read}')

        self.analysis.file_ptr = 0
        analyzed = self.analysis.analyze()

        if(analyzed != to_read and fail_on_error):
            raise ValueError(f'Analyzed {analyzed} out of {to_read}')

        return analyzed
