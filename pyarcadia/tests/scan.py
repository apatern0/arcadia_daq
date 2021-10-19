from tqdm import tqdm
import numpy as np
import threading

from ..test import Test, customplot

class ParallelAnalysis(threading.Thread):
    test = None

    def __init__(self, test):
        threading.Thread.__init__(self)
        self.test = test

    def run(self):
        self.test.post_main()
        self.test.chip.packets_read_stop()


class ScanTest(Test):
    range = []
    result = []
    axes = ["time (s)", "voltage (mV)"]
    title = "Scan Test"

    reader = None
    ebar = None

    def pre_main(self):
        return

    def pre_loop(self):
        return

    def loop_body(self, iteration):
        return

    def post_loop(self):
        return

    def post_main(self):
        return

    def loop(self):
        self.pre_main()

        with tqdm(total=len(self.range), desc='Acquisition') as bar:
            for i in self.range:
                self.pre_loop()
                self.loop_body(i)
                self.post_loop()
                bar.update(1)
        
        self.post_main()

    def loop_parallel(self):
        analysis_thread = ParallelAnalysis(self)

        self.pre_main()
        self.chip.idle_timeout=5
        analysis_thread.start()

        with tqdm(total=len(self.range), desc='Acquisition') as abar, tqdm(total=len(self.range), desc='Elaboration') as self.ebar:
            for i in self.range:
                self.pre_loop()
                self.loop_body(i)
                self.post_loop()
                abar.update(1)

            analysis_thread.join()
        
    def __init__(self):
        super().__init__()

    @customplot(('X', 'Y'), 'Title')
    def plot(self, show=True, saveas=None, ax=None):
        ax.plot(self.range, self.result, '-o')
