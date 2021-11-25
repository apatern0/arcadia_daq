set fw_dir $::env(HOME)/Downloads
if {[info exists ::env(FIRMWARE_DIR)] == 1} {
	set fw_dir $::env(FIRMWARE_DIR)
}
puts "Looking for latest firmware in: $fw_dir"

set s " "
set fw [exec find $fw_dir -type f -name {*.bit} -printf {%T@ %p\n} | sort -n | tail -1 | cut -f2- -d$s]
set fw [string range $fw 0 end-4]
puts "Using $fw"

#disconnect_hw_server localhost:3121
open_hw_manager
connect_hw_server -allow_non_jtag
open_hw_target

# Program and Refresh the XC7K325T Device
current_hw_device [get_hw_devices xc7k325t_0]
refresh_hw_device -update_hw_probes false [lindex [get_hw_devices xc7k325t_0] 0]
set_property PROBES.FILE "$fw.ltx" [get_hw_devices xc7k325t_0]
set_property FULL_PROBES.FILE "$fw.ltx" [get_hw_devices xc7k325t_0]
set_property PROGRAM.FILE "$fw.bit" [get_hw_devices xc7k325t_0]
program_hw_devices [get_hw_devices xc7k325t_0]
 
refresh_hw_device [lindex [get_hw_devices] 0]
