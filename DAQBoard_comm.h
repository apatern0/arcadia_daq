#ifndef DAQUTIL_H
#define DAQUTIL_H

#include <stdint.h>
#include <string>
#include <thread>
#include <atomic>
#include <map>

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

typedef struct {
	int word_address;
	int mask;
	int offset;
	int default_value;
} arcadia_gcr_param;

const int register_address_max = 12;
static std::map <std::string, arcadia_gcr_param> registers_map = {
	{"READOUT_CLK_DIVIDER",       {0, 0x000f,  0, 3}},
	{"TIMING_CLK_DIVIDER",        {0, 0x000f,  4, 8}},
	{"MAX_READS",                 {0, 0x000f,  8, 8}},
	{"TOKEN_COUNTER",             {0, 0x000f, 12, 8}},

	{"TEST_PULSE_MASK",           {1, 0xffff, 0, 0}},
	{"SECTION_READ_MASK",         {2, 0xffff, 0, 0}},
	{"SECTION_CLOCK_MASK",        {3, 0xffff, 0, 0}},

	{"DIGITAL_INJECTION",         {4, 0xffff, 0, 0}},
	{"FORCE_ENABLE_INJECTION",    {5, 0xffff, 0, 0xffff}},
	{"FORCE_DISABLE_MASK",        {6, 0xffff, 0, 0xffff}},

	{"OPERATION",                 {7, 0x0001, 0, 0}},
	{"SERIALIZER_SYNC",           {7, 0x0001, 1, 0}},
	{"LVDS_STRENGTH",             {7, 0x0007, 2, 4}},
	{"SECTION_CLOCK_GATING",      {7, 0x0001, 5, 0}},
	{"TIMESTAMP_LATCHES",         {7, 0x0001, 6, 1}},
	{"DISABLE_SMART_READOUT",     {7, 0x0001, 7, 0}},
	{"EOS_CLOCK_GATING_ENABLE",   {7, 0x0001, 8, 0}},

	{"HELPER_SECCFG_SECTIONS",    { 8, 0xffff,  0, 0xffff}},
	{"HELPER_SECCFG_COLUMNS",     { 9, 0xffff,  0, 0xffff}},
	{"HELPER_SECCFG_PRSTART",     {10, 0x007f,  0, 0x007f}},
	{"HELPER_SECCFG_PRSKIP",      {10, 0x007f,  7, 0x0000}},
	{"HELPER_SECCFG_CFGDATA",     {10, 0x0003, 14, 0x0001}},
	{"HELPER_SECCFG_PRSTOP",      {11, 0x007f,  0, 0x0000}},
	{"HELPER_SECCFG_PIXELSELECT", {11, 0x001f,  7, 0x001f}},
};


class DAQBoard_comm{
private:

	const bool verbose = false;
	const std::string device_str;
	uhal::ConnectionManager ConnectionMgr;
	uhal::HwInterface lHW;

	std::array<bool, 3> spi_unavaiable = {false};
	const std::array<const std::string, 3> master_ids = {"spi_id0", "spi_id1", "spi_id2"};

	std::array<std::thread, 3> data_reader;
	std::array<std::atomic_bool, 3> run_daq_flag;

	std::array<uint16_t, register_address_max> register_address_array;
	static int conf_handler(void* user, const char* section, const char* name,
			const char* value);

	void daq_loop(const std::string fname, uint8_t chip_id);

public:

	DAQBoard_comm(std::string connection_xml_path, std::string device_id, bool verbose=false);
	int read_conf(std::string fname);

	int spi_transfer(ARCADIA_command command, uint16_t payload, uint8_t chip_id, uint32_t* rcv_data);
	int read_register(uint8_t chip_id, uint16_t addr, uint16_t* data);
	int write_register(uint8_t chip_id, uint16_t addr, uint16_t data);

	int read_fpga_register(std::string reg_handle, uint32_t* data);
	int write_fpga_register(std::string reg_handle, uint32_t data);
	void dump_DAQBoard_reg();

	int start_daq(uint8_t chip_id, std::string fname = "dout");
	int stop_daq(uint8_t chip_id);

};
#endif
