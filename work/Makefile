ETH ?= enp2s0

.PHONY: bin

bin:
	make -C bin all

cxxopts:
	git clone --depth=1 https://github.com/jarro2783/cxxopts.git
	cp cxxopts/include/cxxopts.hpp bin
	rm -rf cxxopts

eth_config:
	-sudo ethtool -C ${ETH} rx-usecs 0
	-sudo route add -host 10.0.8.15 dev ${ETH}
	-sudo ifconfig ${ETH} up netmask 255.255.255.0 10.0.8.1
