CXX = g++
CXXFLAGS = -g -std=c++11 -Wall -Wextra -O2
LIBS = -I/opt/cactus/include -I./cxxopts -L/opt/cactus/lib -lcactus_uhal_uhal -lcactus_uhal_grammars -lcactus_uhal_log -lpthread -linih

all: arcadia-cli chk_counter

arcadia-cli: DAQBoard_comm.o main.o
	$(CXX) $(CXXFLAGS) $(LIBS) $^ -o $@

chk_counter: chk_counter.o
	$(CXX) $(CXXFLAGS) $^ -o $@

%.o: %.cpp
	$(CXX) $(CXXFLAGS) $(LIBS) -c -o $@ $<

clean:
	rm -f *.o arcadia-cli chk_counter
