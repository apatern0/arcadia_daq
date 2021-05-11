Minimal cli tool for the arcadia DAQ Board

# Build and Setup
To build and use this tool the [IPBus software](https://ipbus.web.cern.ch/doc/user/html/software/installation.html) need to be installed in `/opt/cactus`.
The the tool can then be build with
```
$ make all
```
then every time you want to use the software you will need to set:
```
$ export LD_LIBRARY_PATH=$LD_LIBRARY_PATH:/opt/cactus/lib/
```
The IPBus documentation [suggest](https://ipbus.web.cern.ch/doc/user/html/performance.html#performance-tweaks-with-ethtool) to set the interrupt coalesce timer of the network card to the lowest value possible:
```
$ sudo ethtool -C <iface> rx-usecs 0
or
$ sudo ethtool -C <iface> rx-usecs 1
```

# Examples of use
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
$ ./arcadia-cli --reg debug --read
Read reg: debug val: 0xaaaa1234

$ ./arcadia-cli --reg debug --write 0xdeadbeef
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
$ ./arca`dia-cli --daq
(daq started for chip 0. Data will bi saved to dout0.raw)

$ ./arcadia-cli --daq=0,1,2
(daq started for chip 0,1 and 2. Data will bi saved to dout{0,1,2}.raw)

$ ./arcadia-cli --daq --daq-mode 0x10
(daq started on chip 0, data generator enabled with divider set to 10 (~25 Mbps))
```

The data generator fills the fifo with a simple 32-bit counter, received data can be verified with:
```
$ ./chk_counter dout.raw
```
