#ifndef DAQUTIL_H
#define DAQUTIL_H

#include <stdint.h>
#include <string.h>
#include <thread>
#include <atomic>

#include "uhal/uhal.hpp"

enum ARCADIA_command {
	ARCADIA_WR_PNTR = 0x0,
	ARCADIA_WR_DATA = 0x1,
	ARCADIA_WR_STAT = 0x2,
	ARCADIA_WR_ICR0 = 0x3,
	ARCADIA_WR_ICR1 = 0x4,
	ARCADIA_RD_PNTR = 0x8,
	ARCADIA_RD_DATA = 0x9,
	ARCADIA_RD_STAT = 0xa,
	ARCADIA_RD_ICR0 = 0xb,
	ARCADIA_RD_ICR1 = 0xc
};

class DAQBoard_comm{
private:

	const std::string device_str;
	uhal::ConnectionManager ConnectionMgr;
	uhal::HwInterface lHW;

	const std::array<const std::string, 3> master_ids = {"spi_id0", "spi_id1", "spi_id2"};

	std::array<std::thread, 3> data_reader;
	std::array<std::atomic_bool, 3> run_daq_flag;

	void DAQ_loop(const std::string fname, uint8_t chip_id);

public:

	DAQBoard_comm(std::string connection_xml_path, std::string device_id);

	int SPI_transfer(ARCADIA_command command, uint16_t payload, uint8_t chip_id, uint32_t* rcv_data);
	int Read_Register(uint8_t chip_id, uint16_t addr, uint16_t* data);
	int Write_Register(uint8_t chip_id, uint16_t addr, uint16_t data);

	int Read_DAQ_register(std::string reg_handle, uint32_t* data);
	int Write_DAQ_register(std::string reg_handle, uint32_t data);
	void Dump_DAQBoard_reg();

	int start_DAQ(uint8_t chip_id, std::string fname = "dout");
	int stop_DAQ(uint8_t chip_id);

};
#endif
