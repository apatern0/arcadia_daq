#include <iostream>
#include <fstream>
#include <unistd.h>
#include <stdexcept>
#include <chrono>

#include <boost/property_tree/ptree.hpp>
#include <boost/property_tree/ini_parser.hpp>

#include "DAQBoard_comm.h"

#define SPI_CHAR_LEN 0x18
#define SPI_GO_BUSY  0x100
#define SPI_RX_NEG   0x200
#define SPI_TX_NEG   0x400
#define SPI_LSB      0x800
#define SPI_IE       0x1000
#define SPI_ASS      0x2000

#define SPI_CLOCK_DIV 7

/*
 * Chip Class
 */
ChipIf::ChipIf(uint8_t id, FPGAIf* fpga_ptr) {
	if(id > 2)
		throw std::runtime_error("Invalid chip id: " + std::to_string(id));

	chip_id = id;
	fpga = fpga_ptr;

	max_packets = 2048/64*1024*1024;
	run_flag = false;
	daq_timeout = false;
	spi_unavailable = false;

	GCR_address_array = std::vector<uint16_t>(calc_gcr_max_addr());
	ctrl_address_array = std::vector<uint32_t>(calc_cmd_max_addr());

	// init register array with default values
	for(auto const& reg: GCR_map){
		arcadia_reg_param const& param = reg.second;
		GCR_address_array[param.word_address] |= (param.default_value << param.offset);
	}
}

int ChipIf::spi_transfer(ARCADIA_command command, uint16_t payload, uint32_t* rcv_data){

	const uhal::Node& SPI_CTRL_Node = fpga->lHW.getNode("spi_id" + std::to_string(chip_id) + ".CTRL");
	const uhal::Node& SPI_TxRx_node = fpga->lHW.getNode("spi_id" + std::to_string(chip_id) + ".TxRx0");

	// prepare CTRL register
	SPI_CTRL_Node.write(SPI_ASS | SPI_RX_NEG | SPI_CHAR_LEN);

	// write TX register
	SPI_TxRx_node.write((command<<20) | payload);

	// set CTRL register to start transfer
	SPI_CTRL_Node.write(SPI_GO_BUSY | SPI_ASS | SPI_RX_NEG | SPI_CHAR_LEN);
	fpga->lHW.dispatch();

	// wait done
	bool done = false;
	for(int tryes=0; tryes<3; tryes++){
		uhal::ValWord<uint32_t> CTRL_val = SPI_CTRL_Node.read();
		fpga->lHW.dispatch();

		done = ((CTRL_val.value() & SPI_GO_BUSY) == 0);
		if (done)
			break;
	}

	if(!done){
		std::cout << "Timeout on SPI xfer" << std::endl;
		return -1;
	}

	// read RX register
	uhal::ValWord<uint32_t> RX_data = SPI_TxRx_node.read();
	fpga->lHW.dispatch();

	if (rcv_data != NULL)
		*rcv_data = RX_data.value();

	return 0;
}

int ChipIf::read_gcr(uint16_t addr, uint16_t* data, bool force_update){
	if (spi_unavailable)
		return -1;

	if (force_update) {
		int gcr_address = addr | 0x2000;
		int res;
		uint32_t reg_data;

		res = spi_transfer(ARCADIA_WR_PNTR, gcr_address, NULL);
		if (res){
			std::cerr << "Failed to set WR_PNTR" << std::endl;
			return res;
		}

		res = spi_transfer(ARCADIA_RD_DATA, 0, &reg_data);
		if (res){
			std::cerr << "Failed to read data" << std::endl;
			return res;
		}

		GCR_address_array[addr] = (reg_data&0xffff);
	}

	if (data != NULL)
		*data = GCR_address_array[addr];

	return 0;
}


int ChipIf::write_gcr(uint16_t addr, uint16_t data) {
	if (spi_unavailable)
		return -1;

	if (addr > GCR_address_array.size()){
		std::cerr << "Invalid address" << std::endl;
		return -1;
	}

	int gcr_address = addr | 0x2000;
	int res;

	res = spi_transfer(ARCADIA_WR_PNTR, gcr_address, NULL);
	if (res){
		std::cerr << "Failed to set WR_PNTR" << std::endl;
		return res;
	}

	res = spi_transfer(ARCADIA_WR_DATA, data, NULL);
	if (res){
		std::cerr << "Failed to read data" << std::endl;
		return res;
	}

	// update cached value
	GCR_address_array[addr] = data;

	return res;
}

int ChipIf::write_gcrpar(std::string gcrpar, uint16_t value) {
	if (spi_unavailable)
		return -1;

	auto search = GCR_map.find(gcrpar);
	if (search == GCR_map.end()){
		std::cerr << "Error: Invalid GCR parameter: " << gcrpar << std::endl;
		return -1;
	}

	arcadia_reg_param const& param = search->second;

	// read current cached gcr value
	uint16_t reg_data = GCR_address_array[param.word_address];
	// clear paramer bits
	reg_data &= ~(param.mask << param.offset);
	// set parameter bits
	reg_data |= ((value & param.mask) << param.offset);
	// write
	int res = write_gcr(param.word_address, reg_data);

	//std::cout << "write gcr: " << std::dec << param.word_address << " val: 0x" << std::hex << reg_data << std::endl;

	return res;
}

int ChipIf::read_gcrpar(std::string gcrpar, uint16_t* value, bool force_update) {
	if (spi_unavailable)
		return -1;

	auto search = GCR_map.find(gcrpar);
	if (search == GCR_map.end()){
		std::cerr << "Error: Invalid GCR parameter: " << gcrpar << std::endl;
		return -1;
	}

	arcadia_reg_param const& param = search->second;

	uint16_t reg_data;
	int res = read_gcr(param.word_address, &reg_data, force_update);
	if (res)
		return res;

	reg_data = (reg_data>>param.offset) & param.mask;

	if (value != NULL)
		*value = reg_data;

	return res;
}


int ChipIf::reinitialize_gcr(uint16_t addr) {
	uint16_t reg_value = 0;

	for(auto const& reg: GCR_map){

		arcadia_reg_param const& param = reg.second;
		if (param.word_address != addr)
			continue;

		reg_value |= ((param.default_value & param.mask) << param.offset);

	}

	int res = write_gcr(addr, reg_value);
	return res;
}

int ChipIf::write_icr(std::string icr_reg, uint16_t value) {
	if (spi_unavailable)
		return -1;

	if (icr_reg != "ICR0" && icr_reg != "ICR1"){
		std::cerr << "No such reg: " << icr_reg << std::endl;
		return -1;
	}

	int res = -1;

	if (icr_reg == "ICR0"){
		res = spi_transfer(ARCADIA_WR_ICR0, value, NULL);
	}
	else if (icr_reg == "ICR1"){
		res = spi_transfer(ARCADIA_WR_ICR1, value, NULL);
	}
	else {
		std::cerr << "No such reg: " << icr_reg << std::endl;
		res = -1;
	}

	return res;
}

int ChipIf::check_gcr_consistency() {
	if (spi_unavailable)
		return -1;

	int errcount = 0;
	uint32_t gcr_addr_max = GCR_address_array.size();

	for(uint32_t addr = 0; addr < gcr_addr_max; addr++){

		uint16_t reg_data = 0;
		uint16_t reg_cached = GCR_address_array[addr];

		uint16_t res = read_gcr(addr, &reg_data);

		if (res){
			std::cerr << "Falied to read gcr: " << addr << std::endl;
			errcount++;
		}
		else if (reg_data != reg_cached){
			std::cout << "gcr " << addr << " mismatch.  Read: " << std::hex << reg_data <<
				" cached: " << reg_cached << std::endl;
			errcount++;
		}
	}

	std::cout << "Check completed with " << errcount << " errors." << std::endl;

	return errcount;

}

int ChipIf::send_controller_command(const std::string cmd, uint32_t arg, uint32_t* resp) {
	auto search = ctrl_cmd_map.find(cmd);

	if (search == ctrl_cmd_map.end()){
		std::cerr << "Invalid command: " << cmd << std::endl;
		return -1;
	}

	arcadia_reg_param const& param = search->second;

	// clear field
	ctrl_address_array[param.word_address] &= ~(param.mask << param.offset);
	// set field
	ctrl_address_array[param.word_address] |= (arg & param.mask) << param.offset;

	uint32_t command = (param.word_address<<20) | ctrl_address_array[param.word_address];

	fpga->write_register("controller_id" + std::to_string(chip_id), command);

	// always read response to free fifo
	uint32_t value;
	fpga->read_register("controller_id" + std::to_string(chip_id), &value);

	if (resp)
		*resp = value;

	return 0;
}

int ChipIf::send_pulse(uint32_t t_on, uint32_t t_off, uint32_t tp_number) {
	if (spi_unavailable)
		std::cout << "WARNING: chip not configured" << std::endl;

	send_controller_command("loadTPOnTime", t_on, NULL);
	send_controller_command("loadTPOffTime", t_off, NULL);
	send_controller_command("loadTPNumber", tp_number, NULL);

	//std::cout << "pulsing.." << chip_id << std::endl;
	send_controller_command("runTPSequence", 0, NULL);

	return 0;
}

int ChipIf::fifo_read(uint32_t stopafter) {
	const uhal::Node& Node_fifo_data = fpga->lHW.getNode("fifo_id" + std::to_string(chip_id) + ".data");
	uint32_t packets_fifo = fifo_count();

	if (packets_fifo == 0)
		return -1;

	if (packet_count > max_packets) {
		std::cerr << "Currently reached maximum packets. Unable to read " << std::dec << packets_fifo << " packets from FPGA." << std::endl;
		Node_fifo_data.readBlock(packets_fifo*2);
		sleep(1);
		return -1;
	}

	uint32_t packets_to_read;
	if(stopafter) {
		packets_to_read = stopafter - packet_count;
		if(packets_to_read > packets_fifo)
			packets_to_read = packets_fifo;
	} else
		packets_to_read = packets_fifo;

	uint32_t bytes_to_read = packets_to_read*2;
	uhal::ValVector<uint32_t> data = Node_fifo_data.readBlock(bytes_to_read);
	fpga->lHW.dispatch();

	uint32_t bytes_read = data.size();

	if (bytes_read < bytes_to_read){
		std::cerr << "Read " << bytes_read << " from FIFO, instead of the requested " << bytes_to_read << std::endl;
		return -1;
	}

	for (size_t index = 0; index < bytes_read-1; index += 2) {
		uint64_t p = data[index];
		p = (p << 32) | data[index+1];
		packets.push_back( p );
	}

	packet_count += bytes_read/2;

	return bytes_read/2;
}

void ChipIf::fifo_read_loop(uint32_t stopafter, uint32_t timeout, uint32_t idle_timeout) {
	std::chrono::steady_clock::time_point start_time = std::chrono::steady_clock::now();
	std::chrono::steady_clock::time_point idle_start_time = start_time;

	while (run_flag) {
		/*
		 * Check timeouts
		 */
		std::chrono::steady_clock::time_point time_now = std::chrono::steady_clock::now();
		uint32_t elapsed_secs =
			std::chrono::duration_cast<std::chrono::seconds>(time_now-start_time).count();

		// Idle Timeout
		if (idle_timeout != 0) {
			uint32_t elapsed_secs_idle =
				std::chrono::duration_cast<std::chrono::seconds>(time_now-idle_start_time).count();

			if (elapsed_secs_idle > idle_timeout){
				run_flag = false;
				if (stopafter !=0 && packet_count < stopafter)
					daq_timeout = true;
			}
		}

		// Timeout
		if (timeout != 0){
			if (elapsed_secs > timeout){
				run_flag = false;
				if (stopafter !=0 && packet_count < stopafter)
					daq_timeout = true;
			}
		}

		/*
		 * No timeouts -> Continue!
		 */

		idle_start_time = std::chrono::steady_clock::now();
		fifo_read(stopafter);

		// stop if maxpkg found
		if (stopafter != 0 && packet_count >= stopafter)
			run_flag = false;
	}
}


int ChipIf::fifo_read_start(uint32_t stopafter, uint32_t timeout, uint32_t idle_timeout) {
	packets.reserve(100*1024*1024/64);

	packets_reset();

	run_flag = true;
	dataread_thread = std::thread(&ChipIf::fifo_read_loop, this, stopafter, timeout, idle_timeout);

	//std::cout << chip_id << ": Data read thread started" << std::endl;

	return 0;
}

void ChipIf::packets_reset() {
	packets.clear();
	packet_count = 0;
}

int ChipIf::fifo_read_stop() {
	run_flag = false;

	return 0;
}


int ChipIf::fifo_read_wait() {
	dataread_thread.join();

	return 0;
}


uint32_t ChipIf::fifo_count() {
	const uhal::Node& Node_fifo_data = fpga->lHW.getNode("fifo_id" + std::to_string(chip_id) + ".data");
	const uhal::Node& Node_fifo_occupancy = fpga->lHW.getNode("fifo_id" + std::to_string(chip_id) + ".occupancy");
	uhal::ValWord<uint32_t> fifo_occupancy = Node_fifo_occupancy.read();
	fpga->lHW.dispatch();
	uint32_t occupancy = (fifo_occupancy.value() & 0x1ffff);
	
	if (occupancy > Node_fifo_data.getSize())
		throw std::runtime_error("DAQ board returned an invalid fifo occupancy value of " + std::to_string(occupancy) + "(> fifo size)");

	if (occupancy % 2)
		throw std::runtime_error("DAQ board returned an invalid fifo occupancy value of " + std::to_string(occupancy) + " (odd instead of even)");

	return (uint32_t) occupancy/2;
}


uint32_t ChipIf::packets_count() {
	return packet_count;
}

int ChipIf::fifo_reset() {
	if (run_flag){
		std::cerr << "DAQ Thread running, refusing to reset fifo" << std::endl;
		return -1;
	}

	const uhal::Node& node_fifo_reset = fpga->lHW.getNode("fifo_id" + std::to_string(chip_id) + ".reset");
	node_fifo_reset.write(0xffffffff);
	fpga->lHW.dispatch();

	//std::cout << chip_id << " : reset sent" << std::endl;

	return 0;
}


uint32_t ChipIf::calibrate_deserializers() {
	const int TAP_VALUES = 32;
	const int LANES = 16;

	uint16_t calibration_array[LANES][TAP_VALUES] = {0};

	send_controller_command("resetISERDES", 1, NULL);
	send_controller_command("resetIDELAYTCTRL", 1, NULL);

	// try all possible taps_values
	for(int tap_val=0; tap_val < TAP_VALUES; tap_val++){

		// set delay taps to tap_val
		for(int tap = 0; tap < LANES; tap++){
			std::stringstream ss;
			ss << "setIDELAYTap" << std::hex << tap;
			send_controller_command(ss.str(), tap_val, NULL);
		}

		std::this_thread::sleep_for(std::chrono::milliseconds(50));
		send_controller_command("syncTX", 0xffff, NULL);
		std::this_thread::sleep_for(std::chrono::milliseconds(50));
		send_controller_command("resetCounters", 1, NULL);
		std::this_thread::sleep_for(std::chrono::milliseconds(50));

		uint32_t locked;
		send_controller_command("readTxState", 0, &locked);

		for(int lane = 0; lane < LANES; lane++){
			if(((locked >> lane) & 0b1) == 0) {
				calibration_array[lane][tap_val] = 0xffff;
				continue;
			}

			uint32_t status;
			send_controller_command("read8b10bErrCounters", lane*2, &status);
			calibration_array[lane][tap_val] = status&0xffff;
		}

	}

	uint32_t best_taps[LANES] = {0};
	for (int lane = 0; lane < LANES; lane++) {
		int start   = -1;
		int stop    = -1;
		int restart = -1;

		for(int tap_val=0; tap_val < TAP_VALUES; tap_val++) {
			//std::cout << std::hex << calibration_array[lane][tap_val] << " ";
			if (calibration_array[lane][tap_val] == 0) {
				if(start == -1)
					start = tap_val;
				else if(stop != -1 && restart == -1)
					restart = tap_val;
			} else if(start != -1 && stop == -1)
				stop = tap_val;
		}

		//std::cout << std::endl;

		if (start == -1)
			std::cerr << "Error: can't find optimal taps in lane: " << lane << std::endl;
		else {
			if(stop == -1)
				stop = TAP_VALUES;

			if(restart != -1)
				start = restart - TAP_VALUES;

			int avg = (stop+start)/2;

			best_taps[lane] = (avg < 0) ? TAP_VALUES+avg : avg;
		}
	}


	for(int lane = 0; lane < LANES; lane++){
		std::stringstream ss;
		ss << "setIDELAYTap" << std::hex << lane;
		send_controller_command(ss.str(), best_taps[lane], NULL);
	}

	std::this_thread::sleep_for(std::chrono::milliseconds(50));
	send_controller_command("syncTX", 0xffff, NULL);
	std::this_thread::sleep_for(std::chrono::milliseconds(50));
	send_controller_command("resetCounters", 1, NULL);
	std::this_thread::sleep_for(std::chrono::milliseconds(50));

	uint32_t locked;
	send_controller_command("readTxState", 0, &locked);

	for(int lane = 0; lane < LANES; lane++){
		uint32_t status, errors;
		send_controller_command("read8b10bErrCounters", lane*2, &errors);
		errors &= 0xffff;

		status = (errors == 0) ? 0 : 1;
		locked = locked & ~(status << lane);
		//printf("Lane %d errors %d status %d locked %x\n", lane, errors, status, locked);
	}

	return locked;
}

/*
 * FPGA If
 */

FPGAIf::FPGAIf(std::string connection_xml_path, std::string device_id, bool verbose) :
	verbose(verbose),
	device_str(device_id),
	ConnectionMgr("file://" + connection_xml_path),
	lHW(ConnectionMgr.getDevice(device_str))
{
	// init class data
	for (uint8_t id: {0, 1, 2}) {

		chips[id] = new ChipIf(id, this);

		// init firmware spi controller
		std::string spi_id = "spi_id" + std::to_string(id);
		lHW.getNode(spi_id + ".CTRL").write(0);
		lHW.getNode(spi_id + ".DIVIDER").write(SPI_CLOCK_DIV);
		lHW.getNode(spi_id + ".SS").write(1);

		try {
			lHW.dispatch();
		}
		catch(...){
			throw std::runtime_error("SPI core " + spi_id + " configuration fail.");
		}
	}
}

int FPGAIf::read_conf(std::string fname) {
	boost::property_tree::ptree pt;
	boost::property_tree::ini_parser::read_ini(fname.c_str(), pt);

	for (auto& section : pt) {
		std::cout << '[' << section.first << "]\n";
		std::string section_str(section.first);

		for (auto& key : section.second) {
			std::cout << key.first << "=" << key.second.get_value<std::string>() << "\n";

			// parse section name/reg
			std::string register_name(key.first);
			std::string value(key.second.get_value<std::string>());

			if (section_str == "id0" || section_str == "id1" || section_str == "id2"){
				uint16_t reg_value = strtol(value.c_str(), NULL, 0);
				uint8_t chip_id = section_str.at(2);
				ChipIf* chip = chips[chip_id];

				// handle ICR0
				if (register_name == "ICR0" || register_name == "IRC1"){
					//std::cout << register_name << " : " << std::hex << reg_value << std::endl;
					chip->write_icr(register_name, reg_value);
					continue;
				}

				// if not ICR0, lookup regname
				auto search = GCR_map.find(register_name);
				if (search == GCR_map.end()){
					std::cerr << "Warning: invalid conf key found: " << register_name << std::endl;
					continue;
				}

				chip->write_gcrpar(register_name, reg_value);

				continue;

			} else if (section_str == "controller_id0" || section_str == "controller_id1" ||
					section_str == "controller_id2"){

				uint8_t chip_id = section_str.at(13);
				ChipIf* chip = chips[chip_id];

				uint32_t reg_value = strtol(value.c_str(), NULL, 0);
				chip->send_controller_command(register_name, reg_value, NULL);

				continue;

			} else {
				std::cerr << "Invalid section: " << section_str << std::endl;
				continue;
			}
		}
	}

	return 0;
}

int FPGAIf::read_register(const std::string reg_handler, uint32_t* data) {
	const uhal::Node& reg_Node = lHW.getNode(reg_handler);

	uhal::ValWord<uint32_t> reg_data = reg_Node.read();
	lHW.dispatch();

	if (data)
		*data = reg_data.value();

	return 0;
}

int FPGAIf::write_register(const std::string reg_handler, uint32_t data) {
	const uhal::Node& reg_Node = lHW.getNode(reg_handler);

	reg_Node.write(data);
	lHW.dispatch();

	return 0;
}

void FPGAIf::dump_DAQBoard_reg() {
	for(auto reg: lHW.getNodes("regfile\\..*")){
		const uhal::Node& reg_Node = lHW.getNode(reg);
		uhal::ValWord<uint32_t> reg_data = reg_Node.read();
		lHW.dispatch();

		std::cout << reg << ": 0x" << std::hex << reg_data.value() << std::endl;
	}
}

