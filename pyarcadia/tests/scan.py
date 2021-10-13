from tqdm import tqdm
import numpy as np

from ..test import Test, customplot

class ScanTest(Test):
    range = []
    result = []
    axes = ["time (s)", "voltage (mV)"]
    title = "Scan Test"

    reader = None

    def pre_main(self):
        self.analysis.cleanup()
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

    def __init__(self):
        super().__init__()

    @customplot(('X', 'Y'), 'Title')
    def plot(self, show=True, saveas=None, ax=None):
        ax.plot(self.range, self.result, '-o')
