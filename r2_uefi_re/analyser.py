"""
Currently incompatible with latest radare2
"""

import os
import sys
import json
import r2pipe
import click
import argparse
import click
from terminaltables import SingleTable

import utils
from guids import edk_guids, ami_guids, edk2_guids

MIN_SET_LEN = 8

OFFSET = {
    "InstallProtocolInterface": 0x80,
    "ReinstallProtocolInterface": 0x88,
    "UninstallProtocolInterface": 0x90,
    "HandleProtocol": 0x98,
    "RegisterProtocolNotify": 0xA8,
    "OpenProtocol": 0x118,
    "CloseProtocol": 0x120,
    "OpenProtocolInformation": 0x128,
    "ProtocolsPerHandle": 0x130,
    "LocateHandleBuffer": 0x138,
    "LocateProtocol": 0x140,
    "InstallMultipleProtocolInterfaces": 0x148,
    "UninstallMultipleProtocolInterfaces": 0x150
}

LEA_NUM = {
    "InstallProtocolInterface": 2,
    "ReinstallProtocolInterface": 1,
    "UninstallProtocolInterface": 1,
    "HandleProtocol": 1,
    "RegisterProtocolNotify": 1,
    "OpenProtocol": 1,
    "CloseProtocol": 1,
    "OpenProtocolInformation": 1,
    "LocateHandleBuffer": 2,
    "LocateProtocol": 1
}

class Analyser():
    def __init__(self, module_path):
        self.module_path = module_path
        """
        '-2' for disabling warnings
        """
        self.r2 = r2pipe.open(module_path, ["-2"])
        self.r2.cmd("aaa")
        
        self.gBServices = {}
        self.gBServices["InstallProtocolInterface"] = []
        self.gBServices["ReinstallProtocolInterface"] = []
        self.gBServices["UninstallProtocolInterface"] = []
        self.gBServices["HandleProtocol"] = []
        self.gBServices["RegisterProtocolNotify"] = []
        self.gBServices["OpenProtocol"] = []
        self.gBServices["CloseProtocol"] = []
        self.gBServices["OpenProtocolInformation"] = []
        self.gBServices["ProtocolsPerHandle"] = []
        self.gBServices["LocateHandleBuffer"] = []
        self.gBServices["LocateProtocol"] = []
        self.gBServices["InstallMultipleProtocolInterfaces"] = []
        self.gBServices["UninstallMultipleProtocolInterfaces"] = []

        self.Protocols = {}
        self.Protocols["AmiGuids"] = ami_guids.ami_guids
        self.Protocols["EdkGuids"] = edk_guids.edk_guids
        self.Protocols["Edk2Guids"] = edk2_guids.edk2_guids
        self.Protocols["All"] = [
            # {
            #   address: ...
            #   service: ...
            #   guid: ...
            # }, 
            # ...
        ]
        self.Protocols["PropGuids"] = []
        self.info = self.get_info()


    def get_info(self):
        info = json.loads(self.r2.cmd("ij"))
        return info
    
    """
    format: {
        func_name: func_address,
        ...
    } 
    """
    def get_funcs(self):
        funcs = {}
        json_funcs = json.loads(self.r2.cmd("aflj"))
        if len(json_funcs) == 0:
            return {}
        for func_info in json_funcs:
            funcs[func_info["name"]] = func_info["offset"]
        return funcs

    def get_boot_services(self):
        funcs = self.get_funcs()
        pdfs = []
        for name in funcs:
            func_info = self.r2.cmd("pdfj @ {name}".format(name=funcs[name]))
            pdfs.append(json.loads(func_info))
        for func_info in pdfs:
            if ("ops" in func_info):
                fcode = func_info["ops"]
                for line in fcode:
                    if ("ptr"    in line and \
                        "type"   in line and \
                        "offset" in line and \
                        "disasm" in line
                    ):
                        if (line["type"] == "ucall" and line["disasm"].find("call qword [") > -1):
                            for service_name in OFFSET:
                                ea = line["offset"]
                                if (line["ptr"] == OFFSET[service_name] and \
                                    self.gBServices[service_name].count(ea) == 0
                                    ):
                                    self.gBServices[service_name].append(ea)

    """ return 0 if ea is start of block """
    def prev_head(self, ea):
        addresses = []
        i = 0
        self.r2.cmd("s {addr}".format(addr=ea))
        block = json.loads(self.r2.cmd("pdfj"))
        for instr in block["ops"]:
            addresses.append(instr["offset"])
        i = addresses.index(ea)
        if i > 0:
            return addresses[i - 1]
        else:
            return 0

    def get_guid(self, address):
        self.r2.cmd("s {addr}".format(addr=address))
        guid_bytes = json.loads(self.r2.cmd("pcj 16"))
        CurrentGUID = []
        CurrentGUID.append(utils.get_dword(bytearray(guid_bytes[:4:])))
        CurrentGUID.append(utils.get_word(bytearray(guid_bytes[4:6:])))
        CurrentGUID.append(utils.get_word(bytearray(guid_bytes[6:8:])))
        CurrentGUID += guid_bytes[8:16:]
        return CurrentGUID

    def get_protocols(self):
        baddr = 0
        if "baddr" in self.info["bin"]:
            baddr = self.get_info()["bin"]["baddr"]
        for service_name in self.gBServices:
            if service_name in LEA_NUM.keys():
                for address in self.gBServices[service_name]:
                    ea = address
                    lea_counter = 0
                    while (True):
                        ea = self.prev_head(ea)
                        if ea == 0:
                            break
                        instr = json.loads(self.r2.cmd("pdj1 @ {addr}".format(addr=ea)))[0]
                        if (instr["type"] == "lea"):
                            lea_counter += 1
                            if (lea_counter == LEA_NUM[service_name]):
                                break
                    if ea == 0:
                        continue
                    guid_addr = instr.get("ptr")
                    if (guid_addr is None) or (guid_addr < baddr):
                        continue
                    CurrentGUID = self.get_guid(guid_addr)
                    if len(set(CurrentGUID)) > MIN_SET_LEN:
                        protocol_record = {}
                        protocol_record["address"] = guid_addr
                        protocol_record["service"] = service_name
                        protocol_record["guid"] = CurrentGUID
                        if self.Protocols["All"].count(protocol_record) == 0:
                            self.Protocols["All"].append(protocol_record)

    def get_prot_names(self):
        for index in range(len(self.Protocols["All"])):
            fin = False
            for prot_name in self.Protocols["Edk2Guids"].keys():
                guid_r2 = self.Protocols["All"][index]["guid"]
                guid_conf = self.Protocols["Edk2Guids"][prot_name]
                if (guid_r2 == guid_conf):
                    self.Protocols["All"][index]["protocol_name"] = prot_name
                    self.Protocols["All"][index]["protocol_place"] = "edk2_guids"
                    fin = True
                    break
            if fin: continue
            for prot_name in self.Protocols["EdkGuids"].keys():
                guid_r2 = self.Protocols["All"][index]["guid"]
                guid_conf = self.Protocols["EdkGuids"][prot_name]
                if (guid_r2 == guid_conf):
                    self.Protocols["All"][index]["protocol_name"] = prot_name
                    self.Protocols["All"][index]["protocol_place"] = "edk_guids"
                    fin = True
                    break
            if fin: continue
            for prot_name in self.Protocols["AmiGuids"].keys():
                guid_r2 = self.Protocols["All"][index]["guid"]
                guid_conf = self.Protocols["AmiGuids"][prot_name]
                if (guid_r2 == guid_conf):
                    self.Protocols["All"][index]["protocol_name"] = prot_name
                    self.Protocols["All"][index]["protocol_place"] = "ami_guids"
                    fin = True
                    break
            if fin: continue
            if not "protocol_name" in self.Protocols["All"][index]:
                self.Protocols["All"][index]["protocol_name"] = "ProprietaryProtocol"
                self.Protocols["All"][index]["protocol_place"] = "unknown"
                self.Protocols["PropGuids"].append(guid_r2)

    def list_boot_services(self):
        self.get_boot_services()
        empty = True
        table_data = []
        table_instance = SingleTable(table_data)
        table_data.append(["Address", "Service"])
        print("Boot services:")
        for service in self.gBServices:
            for address in self.gBServices[service]:
                table_data.append([hex(address), service])
                empty = False
        if empty:
            print(" * list is empty")
        else:
            print(table_instance.table)

    def list_protocols(self):
        self.get_boot_services()
        self.get_protocols()
        self.get_prot_names()
        data = self.Protocols["All"]
        print("Protocols:")
        if len(data) == 0:
            print(" * list is empty")
        else:
            table_data = []
            table_instance = SingleTable(table_data)
            table_data.append(["GUID", "Protocol name", "Address", "Service", "Protocol place"])
            for element in data:
                guid = str(map(hex, element["guid"]))
                guid = guid.replace(", ", "-")
                guid = guid.replace("L", "")
                guid = guid.replace("'", "")
                table_data.append([
                    guid,
                    element["protocol_name"],
                    hex(element["address"]),
                    element["service"],
                    element["protocol_place"]
                    ])
            print(table_instance.table)

    def print_all(self):
        self.list_boot_services()
        self.list_protocols()

if __name__=="__main__":
    click.echo(click.style("UEFI_RETool", fg="cyan"))
    click.echo(click.style("A tool for UEFI module analysis with radare2", fg="cyan"))
    program = "python " + os.path.basename(__file__)
    parser = argparse.ArgumentParser(description="UEFI module analyser",
		prog=program)
    parser.add_argument("module",
		type=str, 
		help="path to UEFI module")
    args = parser.parse_args()
    if os.path.isfile(args.module):
        analyser = Analyser(args.module)
        analyser.print_all()
    else:
        print("Invalid argument")
