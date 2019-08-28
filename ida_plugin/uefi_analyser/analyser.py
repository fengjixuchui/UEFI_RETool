import json
import idaapi
import idautils
import idc
from terminaltables import SingleTable

import utils
from guids import ami_guids, edk2_guids, edk_guids
from tables import (
    BOOT_SERVICES_OFFSET_x64, 
    BOOT_SERVICES_OFFSET_x86
)

class Analyser():
    def __init__(self):
        path = idaapi.get_input_file_path()
        with open(path, "rb") as f:
            header = bytearray(f.read(1024))
        self.arch = utils.get_machine_type(header)
        self.subsystem = utils.check_subsystem(header)
        self.valid = True
        if not self.subsystem:
            print("[ERROR] Wrong subsystem")
            self.valid = False
        # define the architecture of the investigated image
        if not (self.arch == "x86" or self.arch == "x64"):
            print("[ERROR] Wrong architecture")
            self.valid = False
        if self.arch == "x86":
            self.BOOT_SERVICES_OFFSET = BOOT_SERVICES_OFFSET_x86
        if self.arch == "x64":
            self.BOOT_SERVICES_OFFSET = BOOT_SERVICES_OFFSET_x64
        self.base = idaapi.get_imagebase()

        # define required structures in the IDA
        idc.Til2Idb(-1, "EFI_GUID")
        idc.Til2Idb(-1, "EFI_SYSTEM_TABLE")
        idc.Til2Idb(-1, "EFI_RUNTIME_SERVICES")
        idc.Til2Idb(-1, "EFI_BOOT_SERVICES")

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
        self.Protocols["Data"] = []

    @staticmethod
    def help():
        print("Methods:")
        print(" * analyser.get_boot_services()")
        print("   - check: analyser.gBServices[<service_name>]")
        print(" * analyser.get_protocols()")
        print("   - check: analyser.Protocols['All']")
        print(" * analyser.get_prot_names()")
        print("   - check: analyser.Protocols['All']")
        print("Commands:")
        print(" * analyser.list_boot_services()")
        print(" * analyser.list_protocols()")
        print(" * analyser.make_comments()")
        print(" * analyser.make_names()")
        print(" * analyser.set_types()")
        print(" * analyser.print_all()")
        print(" * analyser.analyse_all()")

    def get_boot_services(self):
        for ea_start in idautils.Functions():
            for ea in idautils.FuncItems(ea_start):
                for service_name in self.BOOT_SERVICES_OFFSET:
                    if (idc.GetMnem(ea) == "call" and \
                        idc.get_operand_value(ea, 0) == self.BOOT_SERVICES_OFFSET[service_name]
                        ):
                        if self.gBServices[service_name].count(ea) == 0:
                            self.gBServices[service_name].append(ea)


    def get_protocols(self):
        for service_name in self.gBServices:
            for address in self.gBServices[service_name]:
                ea, found = 0, False
                if self.arch == "x86":
                    for i in range(1, 25):
                        ea = address - i
                        if (idc.get_operand_value(ea, 0) > self.base and idc.GetMnem(ea) == "push"):
                            found = True
                            break
                if self.arch == "x64":
                    for i in range(1, 10):
                        ea = address - i
                        if (idc.get_operand_value(ea, 1) > self.base and idc.GetMnem(ea) == "lea"):
                            found = True
                            break
                if not found:
                    continue
                for xref in idautils.DataRefsFrom(ea):
                    if (idc.GetMnem(xref) == ""):
                        CurrentGUID = utils.get_guid(xref)
                        protocol_record = {}
                        protocol_record["address"] = xref
                        protocol_record["service"] = service_name
                        protocol_record["guid"] = CurrentGUID
                        if not self.Protocols["All"].count(protocol_record):
                            self.Protocols["All"].append(protocol_record)

    def get_prot_names(self):
        for index in range(len(self.Protocols["All"])):
            fin = False
            for prot_name in self.Protocols["Edk2Guids"].keys():
                guid_idb = self.Protocols["All"][index]["guid"]
                guid_conf = self.Protocols["Edk2Guids"][prot_name]
                if (guid_idb == guid_conf):
                    self.Protocols["All"][index]["protocol_name"] = prot_name
                    self.Protocols["All"][index]["protocol_place"] = "edk2_guids"
                    fin = True
                    break
            if fin: continue
            for prot_name in self.Protocols["EdkGuids"].keys():
                guid_idb = self.Protocols["All"][index]["guid"]
                guid_conf = self.Protocols["EdkGuids"][prot_name]
                if (guid_idb == guid_conf):
                    self.Protocols["All"][index]["protocol_name"] = prot_name
                    self.Protocols["All"][index]["protocol_place"] = "edk_guids"
                    fin = True
                    break
            if fin: continue
            for prot_name in self.Protocols["AmiGuids"].keys():
                guid_idb = self.Protocols["All"][index]["guid"]
                guid_conf = self.Protocols["AmiGuids"][prot_name]
                if (guid_idb == guid_conf):
                    self.Protocols["All"][index]["protocol_name"] = prot_name
                    self.Protocols["All"][index]["protocol_place"] = "ami_guids"
                    fin = True
                    break
            if fin: continue
            if not "protocol_name" in self.Protocols["All"][index]:
                self.Protocols["All"][index]["protocol_name"] = "ProprietaryProtocol"
                self.Protocols["All"][index]["protocol_place"] = "unknown"

    def rename_supposed_guids(self):
        EFI_GUID = "EFI_GUID *"
        segments = [
            ".text", 
            ".data"
        ]
        for segment in segments:
            seg_start, seg_end = 0, 0
            for seg in idautils.Segments():
                if idc.SegName(seg) == segment:
                    seg_start = idc.SegStart(seg)
                    seg_end = idc.SegEnd(seg)
                    break
            ea = seg_start
            while (ea <= seg_end - 15):
                prot_name = ""
                if idc.Name(ea).find("unk_") != -1:
                    find = False
                    CurrentGuid = []
                    CurrentGuid.append(idc.Dword(ea))
                    CurrentGuid.append(idc.Word(ea + 4))
                    CurrentGuid.append(idc.Word(ea + 6))
                    for addr in range(ea + 8, ea + 16, 1):
                        CurrentGuid.append(idc.Byte(addr))
                    for name in self.Protocols["Edk2Guids"]:
                        if self.Protocols["Edk2Guids"][name] == CurrentGuid:
                            prot_name = name + "_" + hex(ea)
                            find = True
                            break
                    for name in self.Protocols["EdkGuids"]:
                        if self.Protocols["EdkGuids"][name] == CurrentGuid:
                            prot_name = name + "_" + hex(ea)
                            find = True
                            break
                    for name in self.Protocols["AmiGuids"]:
                        if self.Protocols["AmiGuids"][name] == CurrentGuid:
                            prot_name = name + "_" + hex(ea)
                            find = True
                            break
                    if (find and \
                        idc.Name(ea) != prot_name and \
                        CurrentGuid[0] != 0
                        ):
                        idc.SetType(ea, EFI_GUID)
                        idc.MakeName(ea, prot_name)
                ea += 1

    def make_comments(self):
        self.get_boot_services()
        empty = True
        for service in self.gBServices:
            for address in self.gBServices[service]:
                """ utils.set_hexrays_comment(address, "EFI_BOOT_SERVICES->{0}".format(service)) """
                message = "EFI_BOOT_SERVICES->{0}".format(service)
                idc.MakeComm(address, message)
                empty = False
                print("[{ea}] {message}".format(ea=hex(address), message=message))
        if empty:
            print(" * list is empty")
    
    def make_names(self):
        EFI_GUID = "EFI_GUID *"
        self.get_boot_services()
        self.get_protocols()
        self.get_prot_names()
        data = self.Protocols["All"]
        empty = True
        for element in data:
            try:
                idc.SetType(element["address"], EFI_GUID)
                name = element["protocol_name"] + "_" + hex(element["address"])
                idc.MakeName(element["address"], name)
                empty = False
                print("[{ea}] {name}".format(ea=hex(element["address"]), name=name))
            except:
                continue
        if empty:
            print(" * list is empty")

    def set_types(self):
        """ handle (EFI_BOOT_SERVICES *) type """
        RAX = 0
        O_REG = 1
        O_MEM = 2
        EFI_BOOT_SERVICES = "EFI_BOOT_SERVICES *"
        empty = True
        for service in self.gBServices:
            for address in self.gBServices[service]:
                ea = address
                num_of_attempts = 10
                for _ in range(num_of_attempts):
                    ea = idc.prev_head(ea)
                    if (idc.GetMnem(ea) == "mov" and idc.get_operand_type(ea, 1) == O_MEM):
                        if (idc.get_operand_type(ea, 0) == O_REG and idc.get_operand_value(ea, 0) == RAX):
                            gBs_var = idc.get_operand_value(ea, 1)
                            gBs_var_type = idc.get_type(gBs_var)
                            if (gBs_var_type == "EFI_BOOT_SERVICES *"):
                                empty = False
                                print("[{0}] EFI_BOOT_SERVICES->{1}".format(hex(address).replace("L", ""), service))
                                print("\t [address] {0}".format(hex(gBs_var).replace("L", "")))
                                print("\t [message] type already applied")
                                break
                            if idc.SetType(gBs_var, EFI_BOOT_SERVICES):
                                empty = False
                                old_name = idc.Name(gBs_var)
                                idc.MakeName(gBs_var, "gBs_" + old_name)
                                print("[{0}] EFI_BOOT_SERVICES->{1}".format(hex(address).replace("L", ""), service))
                                print("\t [address] {0}".format(hex(gBs_var).replace("L", "")))
                                print("\t [message] type successfully applied")
                            else:
                                empty = False
                                print("[{0}] EFI_BOOT_SERVICES->{1}".format(hex(address).replace("L", ""), service))
                                print("\t [address] {0}".format(hex(gBs_var).replace("L", "")))
                                print("\t [message] type not applied")
                            break
        if empty:
            print(" * list is empty")

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
    
    def analyse_all(self):
        print("Comments:")
        self.make_comments()
        print("Names:")
        self.make_names()
        print("Types:")
        self.set_types()
        self.rename_supposed_guids()

def main():
    analyser = Analyser()
    if analyser.valid:
        analyser.print_all()
        analyser.analyse_all()

if __name__=="__main__":
    main()
