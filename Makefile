CXX = g++
CXXFLAGS = -g -Wall -Wextra -O2
LIBS = -I/opt/cactus/include -I./cxxopts -L/opt/cactus/lib -lcactus_uhal_uhal -lcactus_uhal_grammars -lcactus_uhal_log -lpthread

all: main chk_counter

main: DAQBoard_comm.o main.o
	$(CXX) $(CXXFLAGS) $(LIBS) $^ -o $@

chk_counter: chk_counter.o
	$(CXX) $(CXXFLAGS) $^ -o $@

%.o: %.cpp
	$(CXX) $(CXXFLAGS) $(LIBS) -c -o $@ $<

clean:
	rm -f *.o main chk_counter
