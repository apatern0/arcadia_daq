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


DAQBoard_comm::DAQBoard_comm(std::string connection_xml_path,	std::string device_id,
		bool verbose) :
		verbose(verbose),
		device_str(device_id),
		ConnectionMgr("file://" + connection_xml_path),
		lHW(ConnectionMgr.getDevice(device_str))
{

	// init class data
	for (std::string id: {"id0", "id1", "id2"}){

		// init chipstructs
		chip_stuctmap.insert(std::make_pair(id, new chip_struct()));

		// init register array with default values
		for(auto const& reg: GCR_map){
			arcadia_reg_param const& param = reg.second;
			chip_stuctmap[id]->GCR_address_array[param.word_address] |=
				(param.default_value << param.offset);
		}

	}


	// init firmware spi controller
	for (std::string id: {"id0", "id1", "id2"}){

		std::string spi_id = "spi_" + id;
		lHW.getNode(spi_id + ".CTRL").write(0);
		lHW.getNode(spi_id + ".DIVIDER").write(SPI_CLOCK_DIV);
		lHW.getNode(spi_id + ".SS").write(1);

		try {
			lHW.dispatch();
		}
		catch(...){
			chip_stuctmap[id]->spi_unavaiable = true;
			std::cerr << "SPI core " << spi_id << " configuration fail" << std::endl;
		}

	}

}


bool DAQBoard_comm::chipid_valid(std::string chip_id){

	return (chip_stuctmap.find(chip_id) != chip_stuctmap.end());

}

int DAQBoard_comm::read_conf(std::string fname){

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

				// handle ICR0
				if (register_name == "ICR0" || register_name == "IRC1"){
					//std::cout << register_name << " : " << std::hex << reg_value << std::endl;
					write_icr(section_str, register_name, reg_value);
					continue;
				}

				// if not ICR0, lookup regname
				auto search = GCR_map.find(register_name);
				if (search == GCR_map.end()){
					std::cerr << "Warning: invalid conf key found: " << register_name << std::endl;
					continue;
				}

				arcadia_reg_param const& param = search->second;
				// clear parameter bits in register
				chip_stuctmap[section_str]->GCR_address_array[param.word_address] &=
					~(param.mask << param.offset);
				// set paramter bits in register
				chip_stuctmap[section_str]->GCR_address_array[param.word_address] |=
					(reg_value & param.mask) << param.offset;

				// write reg
				write_gcr(section_str, param.word_address,
						chip_stuctmap[section_str]->GCR_address_array[param.word_address]);

				continue;

			} else if (section_str == "controller_id0" || section_str == "controller_id1" ||
					section_str == "controller_id2"){

				uint32_t reg_value = strtol(value.c_str(), NULL, 0);
				send_controller_command(section_str, register_name, reg_value, NULL);

				continue;

			} else {
				std::cerr << "Unknown section: " << section_str << std::endl;
				continue;
			}
		}
	}

	return 0;
}


int DAQBoard_comm::spi_transfer(ARCADIA_command command, uint16_t payload,
		std::string chip_id, uint32_t* rcv_data){

	const uhal::Node& SPI_CTRL_Node = lHW.getNode("spi_" + chip_id + ".CTRL");
	const uhal::Node& SPI_TxRx_node = lHW.getNode("spi_" + chip_id + ".TxRx0");

	// prepare CTRL register
	SPI_CTRL_Node.write(SPI_ASS | SPI_RX_NEG | SPI_CHAR_LEN);

	// write TX register
	SPI_TxRx_node.write((command<<20) | payload);

	// set CTRL register to start transfer
	SPI_CTRL_Node.write(SPI_GO_BUSY | SPI_ASS | SPI_RX_NEG | SPI_CHAR_LEN);
	lHW.dispatch();

	// wait done
	bool done = false;
	for(int tryes=0; tryes<3; tryes++){
		uhal::ValWord<uint32_t> CTRL_val = SPI_CTRL_Node.read();
		lHW.dispatch();

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
	lHW.dispatch();

	if (rcv_data != NULL)
		*rcv_data = RX_data.value();

	return 0;
}


int DAQBoard_comm::read_gcr(std::string chip_id, uint16_t addr, uint16_t* data,
		bool force_update){

	if (!chipid_valid(chip_id)){
		std::cerr << "unknown id: " << chip_id << std::endl;
		return -1;
	}

	if (chip_stuctmap[chip_id]->spi_unavaiable)
		return -1;

	if (force_update){

		int gcr_address = addr | 0x2000;
		int res;
		uint32_t reg_data;

		res = spi_transfer(ARCADIA_WR_PNTR, gcr_address, chip_id, NULL);
		if (res){
			std::cerr << "Failed to set WR_PNTR" << std::endl;
			return res;
		}

		res = spi_transfer(ARCADIA_RD_DATA, 0, chip_id, &reg_data);
		if (res){
			std::cerr << "Failed to read data" << std::endl;
			return res;
		}

		chip_stuctmap[chip_id]->GCR_address_array[addr] = (reg_data&0xffff);

	}

	if (data != NULL)
		*data = chip_stuctmap[chip_id]->GCR_address_array[addr];

	return 0;
}


int DAQBoard_comm::write_gcr(std::string chip_id, uint16_t addr, uint16_t data){

	if (!chipid_valid(chip_id)){
		std::cerr << "unknown id: " << chip_id << std::endl;
		return -1;
	}

	if (chip_stuctmap[chip_id]->spi_unavaiable)
		return -1;

	if (addr > chip_stuctmap[chip_id]->GCR_address_array.size()){
		std::cerr << "Invalid address" << std::endl;
		return -1;
	}

	int gcr_address = addr | 0x2000;
	int res;

	res = spi_transfer(ARCADIA_WR_PNTR, gcr_address, chip_id, NULL);
	if (res){
		std::cerr << "Failed to set WR_PNTR" << std::endl;
		return res;
	}

	res = spi_transfer(ARCADIA_WR_DATA, data, chip_id, NULL);
	if (res){
		std::cerr << "Failed to read data" << std::endl;
		return res;
	}

	// update cached value
	chip_stuctmap[chip_id]->GCR_address_array[addr] = data;

	return res;
}


int DAQBoard_comm::write_gcrpar(std::string chip_id, std::string gcrpar, uint16_t value){

	if (!chipid_valid(chip_id)){
		std::cerr << "unknown id: " << chip_id << std::endl;
		return -1;
	}

	if (chip_stuctmap[chip_id]->spi_unavaiable)
		return -1;

	auto search = GCR_map.find(gcrpar);
	if (search == GCR_map.end()){
		std::cerr << "Error: Invalid GCR parameter: " << gcrpar << std::endl;
		return -1;
	}

	arcadia_reg_param const& param = search->second;

	// read current cached gcr value
	uint16_t reg_data = chip_stuctmap[chip_id]->GCR_address_array[param.word_address];
	// clear paramer bits
	reg_data &= ~(param.mask << param.offset);
	// set parameter bits
	reg_data |= ((value & param.mask) << param.offset);
	// write
	int res = write_gcr(chip_id, param.word_address, reg_data);

	//std::cout << "write gcr: " << std::dec << param.word_address << " val: 0x" << std::hex << reg_data << std::endl;

	return res;
}


int DAQBoard_comm::read_gcrpar(std::string chip_id, std::string gcrpar, uint16_t* value,
		bool force_update){

	if (!chipid_valid(chip_id)){
		std::cerr << "unknown id: " << chip_id << std::endl;
		return -1;
	}

	if (chip_stuctmap[chip_id]->spi_unavaiable)
		return -1;

	auto search = GCR_map.find(gcrpar);
	if (search == GCR_map.end()){
		std::cerr << "Error: Invalid GCR parameter: " << gcrpar << std::endl;
		return -1;
	}

	arcadia_reg_param const& param = search->second;

	uint16_t reg_data;
	int res = read_gcr(chip_id, param.word_address, &reg_data, force_update);
	if (res)
		return res;

	reg_data = (reg_data>>param.offset) & param.mask;

	if (value != NULL)
		*value = reg_data;

	return res;
}


int DAQBoard_comm::reinitialize_gcr(std::string chip_id, uint16_t addr){

	if (!chipid_valid(chip_id)){
		std::cerr << "unknown id: " << chip_id << std::endl;
		return -1;
	}

	uint16_t reg_value = 0;

	for(auto const& reg: GCR_map){

		arcadia_reg_param const& param = reg.second;
		if (param.word_address != addr)
			continue;

		reg_value |= ((param.default_value & param.mask) << param.offset);

	}

	int res = write_gcr(chip_id, addr, reg_value);
	return res;
}


int DAQBoard_comm::write_icr(std::string chip_id, std::string icr_reg, uint16_t value){

	if (!chipid_valid(chip_id)){
		std::cerr << "unknown id: " << chip_id << std::endl;
		return -1;
	}

	if (chip_stuctmap[chip_id]->spi_unavaiable)
		return -1;

	if (icr_reg != "ICR0" && icr_reg != "ICR1"){
		std::cerr << "No such reg: " << icr_reg << std::endl;
		return -1;
	}

	int res = -1;

	if (icr_reg == "ICR0"){
		res = spi_transfer(ARCADIA_WR_ICR0, value, chip_id, NULL);
	}
	else if (icr_reg == "ICR1"){
		res = spi_transfer(ARCADIA_WR_ICR1, value, chip_id, NULL);
	}
	else {
		std::cerr << "No such reg: " << icr_reg << std::endl;
		res = -1;
	}

	return res;
}


int DAQBoard_comm::check_consistency(const std::string chip_id){

	if (!chipid_valid(chip_id)){
		std::cerr << "unknown id: " << chip_id << std::endl;
		return -1;
	}

	if (chip_stuctmap[chip_id]->spi_unavaiable)
		return -1;


	int errcount = 0;
	uint32_t gcr_addr_max = chip_stuctmap[chip_id]->GCR_address_array.size();

	for(uint32_t addr = 0; addr < gcr_addr_max; addr++){

		uint16_t reg_data = 0;
		uint16_t reg_cached = chip_stuctmap[chip_id]->GCR_address_array[addr];

		uint16_t res = read_gcr(chip_id, addr, &reg_data);

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


int DAQBoard_comm::read_fpga_register(const std::string reg_handler, uint32_t* data){

	const uhal::Node& reg_Node = lHW.getNode(reg_handler);

	uhal::ValWord<uint32_t> reg_data = reg_Node.read();
	lHW.dispatch();

	if (data)
		*data = reg_data.value();

	return 0;
}


int DAQBoard_comm::write_fpga_register(const std::string reg_handler, uint32_t data){

	const uhal::Node& reg_Node = lHW.getNode(reg_handler);

	reg_Node.write(data);
	lHW.dispatch();

	return 0;
}


int DAQBoard_comm::send_controller_command(const std::string controller_id,
		const std::string cmd, uint32_t arg, uint32_t* resp){

	auto search = ctrl_cmd_map.find(cmd);

	if (search == ctrl_cmd_map.end()){
		std::cerr << "Invalid command: " << cmd << std::endl;
		return -1;
	}

	std::string chip_id = controller_id.substr(11,3);
	arcadia_reg_param const& param = search->second;

	// clear field
	chip_stuctmap[chip_id]->ctrl_address_array[param.word_address] &=
		~(param.mask << param.offset);
	// set field
	chip_stuctmap[chip_id]->ctrl_address_array[param.word_address] |=
		(arg & param.mask) << param.offset;

	uint32_t command = (param.word_address<<20) |
		chip_stuctmap[chip_id]->ctrl_address_array[param.word_address];

	write_fpga_register(controller_id, command);

	// always read response to free fifo
	uint32_t value;
	read_fpga_register(controller_id, &value);

	if (resp)
		*resp = value;

	return 0;
}


int DAQBoard_comm::send_pulse(const std::string chip_id,
		uint32_t t_on, uint32_t t_off, uint32_t tp_number){

	if (!chipid_valid(chip_id)){
		std::cerr << "unknown id: " << chip_id << std::endl;
		return -1;
	}

	if (chip_stuctmap[chip_id]->spi_unavaiable)
		std::cout << "WARNING: chip not configured" << std::endl;

	const std::string controller_id = "controller_" + chip_id;

	send_controller_command(controller_id, "loadTPOnTime", t_on, NULL);
	send_controller_command(controller_id, "loadTPOffTime", t_off, NULL);
	send_controller_command(controller_id, "loadTPNumber", tp_number, NULL);

	//std::cout << "pulsing.." << chip_id << std::endl;
	send_controller_command(controller_id, "runTPSequence", 0, NULL);

	return 0;
}


void DAQBoard_comm::dump_DAQBoard_reg(){

	for(auto reg: lHW.getNodes("regfile\\..*")){
		const uhal::Node& reg_Node = lHW.getNode(reg);
		uhal::ValWord<uint32_t> reg_data = reg_Node.read();
		lHW.dispatch();

		std::cout << reg << ": 0x" << std::hex << reg_data.value() << std::endl;
	}

}


void DAQBoard_comm::daq_read(std::string chip_id, const std::string fname, uint32_t stopafter) {
	const std::string filename = fname + chip_id + ".raw";

	const uhal::Node& Node_fifo_data = lHW.getNode("fifo_" + chip_id + ".data");
	std::ofstream outstrm(filename, std::ios::out | std::ios::trunc | std::ios::binary);

	if (!outstrm.is_open())
		throw std::runtime_error("Can't open file for write");

	chip_stuctmap[chip_id]->packet_count = 0;

	uint32_t occupancy = get_fifo_occupancy(chip_id);

	chip_stuctmap[chip_id]->packet_count += occupancy;

	stopafter *= 2;
	occupancy = (occupancy > stopafter) ? stopafter : occupancy;
	uhal::ValVector<uint32_t> data = Node_fifo_data.readBlock(occupancy);
	lHW.dispatch();

	if (data.size() < occupancy){
		std::cout << "fail to read data" << std::endl;
		return;
	}

	outstrm.write((char*)data.value().data(), data.size()*4);

	outstrm.close();
}

void DAQBoard_comm::daq_loop(const std::string fname, std::string chip_id,
		uint32_t stopafter, uint32_t timeout, uint32_t idle_timeout){

	const std::string filename = fname + chip_id + ".raw";

	const uhal::Node& Node_fifo_data = lHW.getNode("fifo_" + chip_id + ".data");
	std::ofstream outstrm(filename, std::ios::out | std::ios::trunc | std::ios::binary);

	if (!outstrm.is_open())
		throw std::runtime_error("Can't open file for write");

	std::chrono::steady_clock::time_point start_time = std::chrono::steady_clock::now();
	std::chrono::steady_clock::time_point idle_start_time = start_time;
	chip_stuctmap[chip_id]->packet_count = 0;

	const int max_iter = 5000;
	uint32_t iter = 0, max_occ = 0;
	double acc = 0.0;
	const double alpha = 1.0/max_iter;

	while (chip_stuctmap[chip_id]->run_flag){
		/*
		 * Check timeouts
		 */
		std::chrono::steady_clock::time_point time_now = std::chrono::steady_clock::now();
		uint32_t elapsed_secs =
			std::chrono::duration_cast<std::chrono::seconds>(time_now-start_time).count();

		// Idle Timeout
		if (idle_timeout != 0){
			uint32_t elapsed_secs_idle =
				std::chrono::duration_cast<std::chrono::seconds>(time_now-idle_start_time).count();

			if (elapsed_secs_idle > idle_timeout){
				chip_stuctmap[chip_id]->run_flag = false;
				if (stopafter !=0 && chip_stuctmap[chip_id]->packet_count < stopafter)
					chip_stuctmap[chip_id]->daq_timedout = true;
			}
		}

		// Timeout
		if (timeout != 0){
			if (elapsed_secs > timeout){
				chip_stuctmap[chip_id]->run_flag = false;
				if (stopafter !=0 && chip_stuctmap[chip_id]->packet_count < stopafter)
					chip_stuctmap[chip_id]->daq_timedout = true;
			}
		}

		/*
		 * No timeouts -> Continue!
		 */
		uint32_t occupancy = get_fifo_occupancy(chip_id);

		if (occupancy == 0)
			continue;
		
		idle_start_time = std::chrono::steady_clock::now();

		// print very rough statistics
		if (verbose) {
			acc = (alpha * occupancy) + (1.0 - alpha) * acc;
			iter++;
			max_occ = std::max(max_occ, occupancy);
			if (iter == max_iter){
				std::cout << chip_id << ": " << (int)acc <<  " peak: " << max_occ << std::endl;
				iter=0;
				max_occ=0;
			}
		}

		uint32_t to_read;
		if(stopafter) {
			to_read = (stopafter - chip_stuctmap[chip_id]->packet_count)*2;
			if(to_read > occupancy)
				to_read = occupancy;
		} else
			to_read = occupancy;

		uhal::ValVector<uint32_t> data = Node_fifo_data.readBlock(to_read); // Occupancy returns 32-bit packets at a time
		lHW.dispatch();

		uint32_t read = data.size();

		if (read < to_read){
			std::cout << "fail to read data" << std::endl;
			continue;
		}

		chip_stuctmap[chip_id]->packet_count += read/2;

		outstrm.write((char*)data.value().data(), data.size()*4);
		outstrm.flush();

		// stop if maxpkg found
		if (stopafter != 0 && chip_stuctmap[chip_id]->packet_count >= stopafter)
			chip_stuctmap[chip_id]->run_flag = false;

	}

	outstrm.close();
}


int DAQBoard_comm::start_daq(std::string chip_id, uint32_t stopafter, uint32_t timeout,
		uint32_t idle_timeout, std::string fname){

	if (!chipid_valid(chip_id)){
		std::cerr << "can't start thread, unknown id: " << chip_id << std::endl;
		return -1;
	}

	chip_stuctmap[chip_id]->run_flag = true;
	chip_stuctmap[chip_id]->dataread_thread =
		std::thread(&DAQBoard_comm::daq_loop, this, fname, chip_id, stopafter, timeout, idle_timeout);

	//std::cout << chip_id << ": Data read thread started" << std::endl;

	return 0;
}


int DAQBoard_comm::stop_daq(std::string chip_id){

	if (!chipid_valid(chip_id)){
		std::cerr << "can't stop thread, unknown id: " << chip_id << std::endl;
		return -1;
	}

	chip_stuctmap[chip_id]->run_flag = false;

	return 0;
}


int DAQBoard_comm::wait_daq_finished(){

	int retcode = 0;

	for (auto const& ch: chip_stuctmap){

		if (!ch.second->run_flag || !ch.second->dataread_thread.joinable())
			continue;

		ch.second->dataread_thread.join();
		//std::cout << ch.first << ": Data read thread stopped" << std::endl;
		if (ch.second->daq_timedout){
			std::cout << "    (thread timed out)" << std::endl;
			retcode = -1;
		}

	}

	return retcode;
}


uint32_t DAQBoard_comm::get_fifo_occupancy(std::string chip_id){
	if (!chipid_valid(chip_id)){
		std::cerr << "unknown id: " << chip_id << std::endl;
		return 0;
	}

	const uhal::Node& Node_fifo_data = lHW.getNode("fifo_" + chip_id + ".data");
	const uhal::Node& Node_fifo_occupancy = lHW.getNode("fifo_" + chip_id + ".occupancy");
	uhal::ValWord<uint32_t> fifo_occupancy = Node_fifo_occupancy.read();
	lHW.dispatch();
	uint32_t occupancy = (fifo_occupancy.value() & 0x1ffff);
	
	if (occupancy > Node_fifo_data.getSize())
		throw std::runtime_error("DAQ board returned an invalid fifo occupancy value (> fifo size)");

	if (occupancy % 2)
		throw std::runtime_error("DAQ board returned an invalid fifo occupancy value (odd instead of even)");

	return (uint32_t) occupancy/2;
}


uint32_t DAQBoard_comm::get_packet_count(std::string chip_id){
	if (!chipid_valid(chip_id)){
		std::cerr << "unknown id: " << chip_id << std::endl;
		return 0;
	}

	return chip_stuctmap[chip_id]->packet_count;
}


int DAQBoard_comm::reset_fifo(std::string chip_id){

	if (!chipid_valid(chip_id)){
		std::cerr << "nu such id: " << chip_id << std::endl;
		return -1;
	}

	if (chip_stuctmap[chip_id]->run_flag){
		std::cerr << "DAQ Thread running, refusing to reset fifo" << std::endl;
		return -1;
	}

	const uhal::Node& node_fifo_reset = lHW.getNode("fifo_" + chip_id + ".reset");
	node_fifo_reset.write(0xffffffff);
	lHW.dispatch();

	std::cout << chip_id << " : reset sent" << std::endl;

	return 0;
}


uint32_t DAQBoard_comm::cal_serdes_idealy(std::string controller_id){

	const int TAP_VALUES = 32;
	const int LANES = 16;

	uint16_t calibration_array[LANES][TAP_VALUES] = {0};

	send_controller_command(controller_id, "resetISERDES", 1, NULL);
	send_controller_command(controller_id, "resetIDELAYTCTRL", 1, NULL);

	// try all possible taps_values
	for(int tap_val=0; tap_val < TAP_VALUES; tap_val++){

		// set delay taps to tap_val
		for(int tap = 0; tap < LANES; tap++){
			std::stringstream ss;
			ss << "setIDELAYTap" << std::hex << tap;
			send_controller_command(controller_id, ss.str(), tap_val, NULL);
		}

		std::this_thread::sleep_for(std::chrono::milliseconds(50));
		send_controller_command(controller_id, "syncTX", 0xffff, NULL);
		std::this_thread::sleep_for(std::chrono::milliseconds(50));
		send_controller_command(controller_id, "resetCounters", 1, NULL);
		std::this_thread::sleep_for(std::chrono::milliseconds(50));

		uint32_t locked;
		send_controller_command(controller_id, "readTxState", 0, &locked);

		for(int lane = 0; lane < LANES; lane++){
			if(((locked >> lane) & 0b1) == 0) {
				calibration_array[lane][tap_val] = 0xffff;
				continue;
			}

			uint32_t status;
			send_controller_command(controller_id, "read8b10bErrCounters", lane*2, &status);
			calibration_array[lane][tap_val] = status&0xffff;
		}

	}

	uint32_t best_taps[LANES] = {0};
	for (int lane = 0; lane < LANES; lane++) {
		int start   = -1;
		int stop    = -1;
		int restart = -1;

		for(int tap_val=0; tap_val < TAP_VALUES; tap_val++) {
			std::cout << std::hex << calibration_array[lane][tap_val] << " ";
			if (calibration_array[lane][tap_val] == 0) {
				if(start == -1)
					start = tap_val;
				else if(stop != -1 && restart == -1)
					restart = tap_val;
			} else if(start != -1 && stop == -1)
				stop = tap_val;
		}

		std::cout << std::endl;

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
		send_controller_command(controller_id, ss.str(), best_taps[lane], NULL);
	}

	std::this_thread::sleep_for(std::chrono::milliseconds(50));
	send_controller_command(controller_id, "syncTX", 0xffff, NULL);
	std::this_thread::sleep_for(std::chrono::milliseconds(50));
	send_controller_command(controller_id, "resetCounters", 1, NULL);
	std::this_thread::sleep_for(std::chrono::milliseconds(50));

	uint32_t locked;
	send_controller_command(controller_id, "readTxState", 0, &locked);

	for(int lane = 0; lane < LANES; lane++){
		uint32_t status, errors;
		send_controller_command(controller_id, "read8b10bErrCounters", lane*2, &errors);
		errors &= 0xffff;

		status = (errors == 0) ? 0 : 1;
		locked = locked & ~(status << lane);
		printf("Lane %d errors %d status %d locked %x\n", lane, errors, status, locked);
	}

	return locked;
}
