/*
    DESCRIPTION:
    Ubuntu Server 20.04 LTS variables used by the Packer Plugin for VMware vSphere (vsphere-iso).
*/

// Guest Operating System Metadata
vm_guest_os_language = "en_US"
vm_guest_os_keyboard = "us"
vm_guest_os_timezone = "UTC"
vm_guest_os_type = "ubuntu64Guest"


// Virtual Machine Hardware Settings
vm_firmware              = "efi"
vm_cpu_count             = 2
vm_mem_size              = 2048
vm_disk_size             = 40960
vm_disk_thin_provisioned = true
vm_interface_name         = "vmxnet3"
vm_network_name           = "VM Network"

// Removable Media Settings
iso_url            = "https://releases.ubuntu.com/focal/ubuntu-20.04.5-live-server-amd64.iso"
iso_checksum_value = "5035be37a7e9abbdc09f0d257f3e33416c1a0fb322ba860d42d74aa75c3468d4"

// Boot Settings
vm_boot_wait  = "2s"

// Communicator Settings
ssh_port    = 22
ssh_timeout = "15m"


