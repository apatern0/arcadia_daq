Comprehensive DAQ for the ARCADIA DMAPS chip.

# Pre-requisites
To build and use this tool the [IPBus software](https://ipbus.web.cern.ch/doc/user/html/software/installation.html) need to be installed in `/opt/cactus`.
The C++ sources needs to be compiled via:
```
$ make -C work/bin all
```
The IPBus documentation [suggest](https://ipbus.web.cern.ch/doc/user/html/performance.html#performance-tweaks-with-ethtool) to set the interrupt coalesce timer of the network card to the lowest value possible:
```
$ sudo ethtool -C <iface> rx-usecs 0
or
$ sudo ethtool -C <iface> rx-usecs 1
```

# Repository structure
The repository has 5 folders:
* cfg/ - XML files needed to setup IPBUS
* example/ - Ready to use scripts for basic tests
* pyarcadia/ - Root of the pyarcadia Python package
* src/ - C++ sources to interface to the DAQ Board
* work/ - Working directory

# Run the software
The sample scripts can be lauched from the working directory:
```
cd work
PYTHONPATH=.. python3 -i ../examples/test_baseline.py
```

# Legacy CLI interface
Print help string with available options:
```
$ ./arcadia-cli -h
```

Dump FPGA registers:
```
$ ./arcadia-cli --dump-regs

regfile.board_id: 0x0
regfile.ctrl: 0x0
regfile.debug: 0xaaaa1234
regfile.fwrev: 0x20210326
regfile.id0_lane_sync: 0x0
regfile.id1_lane_sync: 0x0
regfile.id2_lane_sync: 0x0
regfile.mode: 0x0
regfile.status: 0x0
```

Read/write one fpga registers (debug register):
```
$ ./arcadia-cli --reg regfile.debug --read
Read reg: debug val: 0xaaaa1234

$ ./arcadia-cli --reg regfile.debug --write 0xdeadbeef
write reg: debug val: 0xdeadbeef
```

Read/write arcadia GCR 0x10 register on chip 0 (different chip can be selected with the `--chip` option):
```
$ ./arcadia-cli --gcr 0x10 --read
read grc: 16 val: 0x0

$ ./arcadia-cli --gcr 0x10 --write 0xdead
read grc: 16 val: 0xdead
```

Run daq, adding the `-v` option to any of the following commands will print some very rough statistics to stdout:
```
$ ./arcadia-cli --daq
(daq started for chip id0. Data will bi saved to dout0.raw)

$ ./arcadia-cli --daq=id0,id1,id2
(daq started for chip 0,1 and 2. Data will bi saved to dout{id0,id1,id2}.raw)

$ ./arcadia-cli --daq --daq-mode 10
(daq started on chip 0, data generator enabled with divider set to 10 (~25 Mbps))
```

The data generator fills the board data fifo with a simple 32-bit counter, received data can be verified with:
```
$ ./chk_counter dout.raw
```
