# (C) Copyright Red Hat 2022.
# SPDX-License-Identifier: Apache-2.0

import os
import sys
import json
import re
import time
import signal
import argparse
import getpass
from time import sleep
from os import system
from threading import Thread
from pathlib import Path
from shutil import which
from pyVim import connect
from pyVmomi import vim

# pip install --upgrade pyvmomi
# Based on examples from
# pyvmomi-community-samples: https://github.com/vmware/pyvmomi-community-samples
# kcli: https://github.com/vmware/pyvmomi-community-samples

class Parser:
    """
    From: https://github.com/vmware/pyvmomi-community-samples/blob/master/samples/tools/cli.py
    Samples specific argument parser.
    Wraps argparse to ease the setup of argument requirements for the samples.

    Example:
        parser = cli.Parser()
        parser.add_required_arguments(cli.Argument.VM_NAME)
        parser.add_optional_arguments(cli.Argument.DATACENTER_NAME, cli.Argument.NIC_NAME)
        parser.add_custom_argument(
            '--disk-number', required=True, help='Disk number to change mode.')
        args = parser.get_args()
    """

    def __init__(self):
        """
        Defines two arguments groups.
        One for the standard arguments and one for sample specific arguments.
        The standard group cannot be extended.
        """
        self._parser = argparse.ArgumentParser(description='Arguments for talking to vCenter')
        self._standard_args_group = self._parser.add_argument_group('standard arguments')
        self._specific_args_group = self._parser.add_argument_group('sample-specific arguments')

        # because -h is reserved for 'help' we use -s for service
        self._standard_args_group.add_argument('-s', '--host',
                                               required=True,
                                               action='store',
                                               help='vSphere service address to connect to')

        # because we want -p for password, we use -o for port
        self._standard_args_group.add_argument('-o', '--port',
                                               type=int,
                                               default=443,
                                               action='store',
                                               help='Port to connect on')

        self._standard_args_group.add_argument('-u', '--user',
                                               required=True,
                                               action='store',
                                               help='User name to use when connecting to host')

        self._standard_args_group.add_argument('-p', '--password',
                                               required=False,
                                               action='store',
                                               help='Password to use when connecting to host')

        self._standard_args_group.add_argument('-nossl', '--disable-ssl-verification',
                                               required=False,
                                               action='store_true',
                                               help='Disable ssl host certificate verification')

    def get_args(self):
        """
        Supports the command-line arguments needed to form a connection to vSphere.
        """
        args = self._parser.parse_args()
        return self._prompt_for_password(args)

    def _add_sample_specific_arguments(self, is_required: bool, *args):
        """
        Add an argument to the "sample specific arguments" group
        Requires a predefined argument from the Argument class.
        """
        for arg in args:
            name_or_flags = arg["name_or_flags"]
            options = arg["options"]
            options["required"] = is_required
            self._specific_args_group.add_argument(*name_or_flags, **options)

    def add_required_arguments(self, *args):
        """
        Add a required argument to the "sample specific arguments" group
        Requires a predefined argument from the Argument class.
        """
        self._add_sample_specific_arguments(True, *args)

    def add_optional_arguments(self, *args):
        """
        Add an optional argument to the "sample specific arguments" group.
        Requires a predefined argument from the Argument class.
        """
        self._add_sample_specific_arguments(False, *args)

    def add_custom_argument(self, *name_or_flags, **options):
        """
        Uses ArgumentParser.add_argument() to add a full definition of a command line argument
        to the "sample specific arguments" group.
        https://docs.python.org/3/library/argparse.html#the-add-argument-method
        """
        self._specific_args_group.add_argument(*name_or_flags, **options)

    def set_epilog(self, epilog):
        """
        Text to display after the argument help
        """
        self._parser.epilog = epilog

    def _prompt_for_password(self, args):
        """
        if no password is specified on the command line, prompt for it
        """
        if not args.password:
            args.password = getpass.getpass(
                prompt='"--password" not provided! Please enter password for host %s and user %s: '
                       % (args.host, args.user))
        return args
    
class Argument:
    """
    From: https://github.com/vmware/pyvmomi-community-samples/blob/master/samples/tools/cli.py
    Predefined arguments to use in the Parser

    Example:
        parser = cli.Parser()
        parser.add_optional_arguments(cli.Argument.VM_NAME)
        parser.add_optional_arguments(cli.Argument.DATACENTER_NAME, cli.Argument.NIC_NAME)
    """
    def __init__(self):
        pass

    DATACENTER_NAME = {
        'name_or_flags': ['--datacenter-name'],
        'options': {'action': 'store', 'help': 'Datacenter name'}
    }
    DATASTORE_NAME = {
        'name_or_flags': ['--datastore-name'],
        'options': {'action': 'store', 'help': 'Datastore name'}
    }
    CLUSTER_NAME = {
        'name_or_flags': ['--cluster-name'],
        'options': {'action': 'store', 'help': 'Cluster name'}
    }
    FOLDER_NAME = {
        'name_or_flags': ['--folder-name'],
        'options': {'action': 'store', 'help': 'Folder name'}
    }
    TEMPLATE = {
        'name_or_flags': ['--template'],
        'options': {'action': 'store', 'help': 'Name of the template/VM'}
    }
    VMFOLDER = {
        'name_or_flags': ['--vm-folder'],
        'options': {'action': 'store', 'help': 'Name of the VMFolder'}
    }
    VMDK_PATH = {
        'name_or_flags': ['--vmdk-path'],
        'options': {'action': 'store', 'help': 'Path of the VMDK file.'}
    }
    OVA_PATH = {
        'name_or_flags': ['--ova-path'],
        'options': {'action': 'store', 'help': 'Path to the OVA file.'}
    }
    OVF_PATH = {
        'name_or_flags': ['--ovf-path'],
        'options': {'action': 'store', 'help': 'Path to the OVF file.'}
    }


def imagetovmdk(url):    
    name=Path(url).stem
    vmdkfile=name + ".vmdk"
    print("Converting " + url + " to vmdk...")
    os.popen(f"qemu-img convert -O vmdk -o subformat=streamOptimized {url} {vmdkfile}").read()
    if os.path.exists(vmdkfile):
        return vmdkfile
    return None

def createovf(vmdkfile, name):
    vmdk_info = json.loads(os.popen(f"qemu-img info {vmdkfile} --output json").read())    
    name=Path(vmdkfile).stem
    ovfpath=name + ".ovf"
    virtual_size = vmdk_info['virtual-size']
    actual_size = vmdk_info['actual-size']
    ovfcontent = open(f"template.ovf.j2").read().format(name=name, virtual_size=virtual_size,
                                                                      actual_size=actual_size, vmdk_file=vmdkfile)
    with open(ovfpath, 'w') as f:
        f.write(ovfcontent)
    ovfd = open(ovfpath).read()
    ovfd = re.sub('<Name>.*</Name>', f'<Name>{name}</Name>', ovfd)
    return ovfpath

def get_obj_in_list(obj_name, obj_list):
    """
    Gets an object out of a list (obj_list) whose name matches obj_name.
    """
    for obj in obj_list:
        if obj.name == obj_name:
            return obj
    print("Unable to find object by the name of %s in list:\n%s" %
          (obj_name, map(lambda o: o.name, obj_list)))
    exit(1)

def selectdatacenter(si, args):
    '''
    Either return the datacenter selected, or error if not found
    If not datacenter is specified, return the first in the list
    '''
    datacenter_list = si.content.rootFolder.childEntity    
    if args:
        datacenter = get_obj_in_list(args, datacenter_list)
        return datacenter
    elif len(datacenter_list) > 0:
        return datacenter_list[0]
    else:
        print("No datacenter found!")
        exit(1)

def selectcluster(si, args):
    '''
    Either return the cluster selected, or error if not found
    If no cluster is specified, return the first in the list
    '''
    cluster_list = si.hostFolder.childEntity
    if args:
        cluster = get_obj_in_list(args, cluster_list)
        return cluster
    elif len(cluster_list) > 0:
        return cluster_list[0]
    else: 
        print("No cluster found!")
        exit(1)
   
def selectdatastore(si, args):
    '''
    Either return the datastore selected, or error if not found
    If no datastore is specified, return the first in the list
    '''
    datastore_list = si.datastoreFolder.childEntity
    if args:
        datastore = get_obj_in_list(args, datastore_list)
        return datastore
    elif len(datastore_list) > 0:
        return datastore_list[0]
    else:
        print("No datastore found!")
        exit(1)

def get_ovf_descriptor(ovf_path):
    """
    Read in the OVF descriptor.
    """
    if os.path.exists(ovf_path):
        with open(ovf_path, 'r') as ovf_file:
            try:
                ovfd = ovf_file.read()
                ovf_file.close()
                return ovfd
            except Exception:
                print("Could not read file: %s" % ovf_path)
                exit(1)

def keep_lease_alive(lease):
    """
    Keeps the lease alive while POSTing the VMDK.
    """
    while True:
        sleep(5)
        try:
            # Choosing arbitrary percentage to keep the lease alive.
            lease.HttpNfcLeaseProgress(50)
            if lease.state == vim.HttpNfcLease.State.done:
                return
            # If the lease is released, we get an exception.
            # Returning to kill the thread.
        except Exception:
            return
    
def createuploadtemplate(args, ovf, vmdkfile):
    si = connect.SmartConnectNoSSL(host=args.host, port=443, user=args.user, pwd=args.password)

    def logout(*args):
        si.content.sessionManager.Logout()
        print("Logging off")
        exit(0)
    
    if si:
        datacenter = selectdatacenter(si, args.datacenter_name)
        datastore = selectdatastore(datacenter, args.datastore_name)
        cluster = selectcluster(datacenter, args.cluster_name)
        ovffd = get_ovf_descriptor(ovf)
        manager = si.content.ovfManager
        resourcepool = cluster.resourcePool        
        spec_params = vim.OvfManager.CreateImportSpecParams()
        import_spec = manager.CreateImportSpec(ovffd,
                                               resourcepool,
                                               datastore,
                                               spec_params)
        print("***********************************************************************************************")
        print("Datacenter: " + datacenter.name + " Datastore: " + datastore.name + " Cluster: " + cluster.name)
        print("Creating template: " + args.template + " using vmdk: " + vmdkfile + " and ovf: " +  ovf)
        print("On Host " + args.host + "...")
        print("***********************************************************************************************")        
        print("Press Ctrl-C to cancel in 5 seconds!")
        signal.signal(signal.SIGINT, logout)        
        time.sleep(5)

        lease = resourcepool.ImportVApp(import_spec.importSpec,
                                                 datacenter.vmFolder)
        while True:
            if lease.state == vim.HttpNfcLease.State.ready:
                url = lease.info.deviceUrl[0].url.replace('*', args.host)
                # Spawn a dawmon thread to keep the lease active while POSTing
                # VMDK.
                keepalive_thread = Thread(target=keep_lease_alive, args=(lease,))
                keepalive_thread.start()
                # POST the VMDK to the host via curl. Requests library would work
                # too.
                curl_cmd = (
                    "curl -Ss -X POST --insecure -T %s -H 'Content-Type: \
                    application/x-vnd.vmware-streamVmdk' %s" %
                    (vmdkfile, url))
                system(curl_cmd)
                lease.HttpNfcLeaseComplete()
                keepalive_thread.join()
                logout()
            elif lease.state == vim.HttpNfcLease.State.error:
                print("Lease error: " + lease.state.error)
                exit(1)
        
               
if __name__ == "__main__":
    parser = Parser()
    parser.add_optional_arguments(
        Argument.DATACENTER_NAME, Argument.DATASTORE_NAME, Argument.CLUSTER_NAME, Argument.TEMPLATE)
    parser.add_custom_argument(
        '-i', '--image', required=True, help='url to the qcow2 image built')
    
    args = parser.get_args()
    if not args.template:
        args.template="podvm-base"
    if not which('qemu-img'):
        print("Please install qemu-img and try again")
        sys.exit(1)
    vmdkfile=imagetovmdk(args.image)
    if vmdkfile:
        ovf=createovf(vmdkfile, args.template)
    else:
        print("Could not create vmdk!")
        exit(1)
    createuploadtemplate(args, ovf, vmdkfile)
