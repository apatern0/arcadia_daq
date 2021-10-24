CXX := g++
PYTHON := python3

SRC := ../../src
OPT ?= 3

CXXFLAGS = -g -std=c++11 -Wall -Wextra -O$(OPT)
LIBS = -I/opt/cactus/include -I. -L/opt/cactus/lib -lcactus_uhal_uhal -lcactus_uhal_grammars -lcactus_uhal_log -lpthread -lboost_system
PYLIBS = $(shell $(PYTHON) -m pybind11 --includes)

all: arcadia-cli chk_counter arcadia_daq.so

arcadia-cli: DAQBoard_comm.o main.o
	$(CXX) $(CXXFLAGS) $(LIBS) $^ -o $@

chk_counter: chk_counter.o
	$(CXX) $(CXXFLAGS) $^ -o $@

arcadia_daq.so: DAQBoard_comm.o ${SRC}/DAQ_pybind.cpp
	$(CXX) $(CXXFLAGS) $(LIBS) $(PYLIBS) -shared -fPIC $^ -o $@

DAQBoard_comm.o: ${SRC}/DAQBoard_comm.cpp
	$(CXX) $(CXXFLAGS) $(LIBS) -shared -fPIC -c -o $@ $<

%.o: ${SRC}/%.cpp
	$(CXX) $(CXXFLAGS) $(LIBS) -c -o $@ $<

clean:
	rm -f *.o arcadia-cli chk_counter DAQ_pybind.so
