Comprehensive DAQ for the ARCADIA DMAPS chip.

# Pre-requisites
To build and use this tool the [IPBus software](https://ipbus.web.cern.ch/doc/user/html/software/installation.html) need to be installed in `/opt/cactus`.

The C++ sources needs to be compiled via:
```
$ make -C work/bin all
```

In order to properly configure the ethernet link, run:
```
$ make -C work eth_config
```

By default it assumes the ethernet device is enp2s0, if your setup is different, you can specify it by appending ETH=xxx with xxx being your device.

# Repository structure
The repository has 5 folders:
* cfg/ - XML files needed to setup IPBUS
* docs/ - Documentation builder
* example/ - Ready to use scripts for basic tests
* pyarcadia/ - Pyarcadia Python package
* src/ - C++ sources to interface to the DAQ Board
* work/ - Working directory

# Build the documentation
In order to build the documentation from the provided reStructuredText python docstrings, please run:
```
$ make -C docs html
```

You can later view it by opening with your browser the following HTML document: `docs/_build/index.html`

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
