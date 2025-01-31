#!/usr/bin/env python
"""
The Pozyx ready to localize tutorial (c) Pozyx Labs
Please read the tutorial that accompanies this sketch:
https://www.pozyx.io/Documentation/Tutorials/ready_to_localize/Python

This tutorial requires at least the contents of the Pozyx Ready to Localize kit. It demonstrates the positioning capabilities
of the Pozyx device both locally and remotely. Follow the steps to correctly set up your environment in the link, change the
parameters and upload this sketch. Watch the coordinates change as you move your device around!
"""
from time import sleep

from pypozyx import (POZYX_POS_ALG_UWB_ONLY, POZYX_3D, Coordinates, POZYX_SUCCESS, PozyxConstants, version,
                     DeviceCoordinates, PozyxSerial, get_first_pozyx_serial_port, SingleRegister, DeviceList, PozyxRegisters)
#from pythonosc.udp_client import SimpleUDPClient

import csv

from datetime import datetime

from pypozyx.tools.version_check import perform_latest_version_check

from pypozyx.structures.device_information import DeviceDetails

import argparse

# Global settings

# Check for the latest PyPozyx version. Skip if this takes too long or is not needed by setting to False.
check_pypozyx_version = True
# Set if you want to save positioning data to csv file to analyze it later
save_to_csv = True
# Enable to send position data through OSC
use_processing = False
# Configure if you want to route OSC to outside your localhost. Networking knowledge is required.
ip = "127.0.0.1"
network_port = 8888
# Necessary anchor data for calibration, change the IDs and coordinates yourself according to your measurement
anchors = [DeviceCoordinates(0x6a11, 1, Coordinates(-155, 12210, 1500)),
            DeviceCoordinates(0x6a19, 1, Coordinates(5170, 11572, 2900)),
            DeviceCoordinates(0x6a6b, 1, Coordinates(0, 0, 2900)),
            DeviceCoordinates(0x676d, 1, Coordinates(4330, 0, 2900))]
# Set if you use remote anchor
remote_id = 0x6e66               # remote device network ID
remote = False                   # whether to use a remote device
# Set serial port or leave it empty to make auto connect
serial_port = ''


class ReadyToLocalize(object):
    """Continuously calls the Pozyx positioning function and prints its position."""

    def __init__(self, pozyx, osc_udp_client, anchors, algorithm=POZYX_POS_ALG_UWB_ONLY, dimension=POZYX_3D, height=1000, remote_id=None):
        self.pozyx = pozyx
        self.osc_udp_client = osc_udp_client

        self.anchors = anchors
        self.algorithm = algorithm
        self.dimension = dimension
        self.height = height
        self.remote_id = remote_id

    def setup(self):
        """Sets up the Pozyx for positioning by calibrating its anchor list."""
        print("------------POZYX POSITIONING V{} -------------".format(version))
        print("")
        print("- System will manually configure tag")
        print("")
        print("- System will auto start positioning")
        print("")
        if self.remote_id is None:
            self.pozyx.printDeviceInfo(self.remote_id)
        else:
            for device_id in [None, self.remote_id]:
                self.pozyx.printDeviceInfo(device_id)
        print("")
        print("------------POZYX POSITIONING V{} -------------".format(version))
        print("")

        self.setAnchorsManual(save_to_flash=False)
        self.printPublishConfigurationResult()
        system_details = DeviceDetails()
        status = pozyx.getDeviceDetails(system_details, remote_id=self.remote_id)
        dev_id = "{}".format("0x%0.4x" % system_details.id)

        if save_to_csv:
            filename = 'pozyx-data-' + dev_id + '-' + datetime.now().strftime('%Y%m%d-%H%M%S') + '.csv'
            self.csv_file = open(filename, mode='w+')
            self.csv_writer = csv.writer(self.csv_file, delimiter=',', quotechar='"', quoting=csv.QUOTE_MINIMAL)
            self.csv_writer.writerow(['x', 'y', 'z'])

    def loop(self):
        """Performs positioning and displays/exports the results."""
        position = Coordinates()
        status = self.pozyx.doPositioning(
            position, self.dimension, self.height, self.algorithm, remote_id=self.remote_id)
        if status == POZYX_SUCCESS:
            self.printPublishPosition(position)
        else:
            self.printPublishErrorCode("positioning")

    def printPublishPosition(self, position):
        """Prints the Pozyx's position and possibly sends it as a OSC packet"""
        network_id = self.remote_id
        if network_id is None:
            network_id = 0
        print("POS ID {}, x(mm): {pos.x} y(mm): {pos.y} z(mm): {pos.z}".format(
            "0x%0.4x" % network_id, pos=position))
        if save_to_csv:
            self.csv_writer.writerow([position.x, position.y, position.z])
        if self.osc_udp_client is not None:
            self.osc_udp_client.send_message(
                "/position", [network_id, int(position.x), int(position.y), int(position.z)])

    def printPublishErrorCode(self, operation):
        """Prints the Pozyx's error and possibly sends it as a OSC packet"""
        error_code = SingleRegister()
        network_id = self.remote_id
        if network_id is None:
            self.pozyx.getErrorCode(error_code)
            print("LOCAL ERROR %s, %s" % (operation, self.pozyx.getErrorMessage(error_code)))
            if self.osc_udp_client is not None:
                self.osc_udp_client.send_message("/error", [operation, 0, error_code[0]])
            return
        status = self.pozyx.getErrorCode(error_code, self.remote_id)
        if status == POZYX_SUCCESS:
            print("ERROR %s on ID %s, %s" %
                  (operation, "0x%0.4x" % network_id, self.pozyx.getErrorMessage(error_code)))
            if self.osc_udp_client is not None:
                self.osc_udp_client.send_message(
                    "/error", [operation, network_id, error_code[0]])
        else:
            self.pozyx.getErrorCode(error_code)
            print("ERROR %s, couldn't retrieve remote error code, LOCAL ERROR %s" %
                  (operation, self.pozyx.getErrorMessage(error_code)))
            if self.osc_udp_client is not None:
                self.osc_udp_client.send_message("/error", [operation, 0, -1])
            # should only happen when not being able to communicate with a remote Pozyx.

    def setAnchorsManual(self, save_to_flash=False):
        """Adds the manually measured anchors to the Pozyx's device list one for one."""
        status = self.pozyx.clearDevices(remote_id=self.remote_id)
        for anchor in self.anchors:
            status &= self.pozyx.addDevice(anchor, remote_id=self.remote_id)
        if len(self.anchors) > 4:
            status &= self.pozyx.setSelectionOfAnchors(PozyxConstants.ANCHOR_SELECT_AUTO, len(self.anchors),
                                                       remote_id=self.remote_id)

        if save_to_flash:
            self.pozyx.saveAnchorIds(remote_id=self.remote_id)
            self.pozyx.saveRegisters([PozyxRegisters.POSITIONING_NUMBER_OF_ANCHORS], remote_id=self.remote_id)
        return status

    def printPublishConfigurationResult(self):
        """Prints and potentially publishes the anchor configuration result in a human-readable way."""
        list_size = SingleRegister()

        self.pozyx.getDeviceListSize(list_size, self.remote_id)
        print("List size: {0}".format(list_size[0]))
        if list_size[0] != len(self.anchors):
            self.printPublishErrorCode("configuration")
            return
        device_list = DeviceList(list_size=list_size[0])
        self.pozyx.getDeviceIds(device_list, self.remote_id)
        print("Calibration result:")
        print("Anchors found: {0}".format(list_size[0]))
        print("Anchor IDs: ", device_list)

        for i in range(list_size[0]):
            anchor_coordinates = Coordinates()
            self.pozyx.getDeviceCoordinates(device_list[i], anchor_coordinates, self.remote_id)
            print("ANCHOR, 0x%0.4x, %s" % (device_list[i], str(anchor_coordinates)))
            if self.osc_udp_client is not None:
                self.osc_udp_client.send_message(
                    "/anchor", [device_list[i], int(anchor_coordinates.x), int(anchor_coordinates.y), int(anchor_coordinates.z)])
                sleep(0.025)

    def printPublishAnchorConfiguration(self):
        """Prints and potentially publishes the anchor configuration"""
        for anchor in self.anchors:
            print("ANCHOR,0x%0.4x,%s" % (anchor.network_id, str(anchor.coordinates)))
            if self.osc_udp_client is not None:
                self.osc_udp_client.send_message(
                    "/anchor", [anchor.network_id, int(anchor.coordinates.x), int(anchor.coordinates.y), int(anchor.coordinates.z)])
                sleep(0.025)
    def close(self):
        if save_to_csv:
            self.csv_file.close()


if __name__ == "__main__":
    
    parser = argparse.ArgumentParser()
    parser.add_argument("-p", "--port", type=str,
                        help="sets the uart port of pozyx, use first pozyx device if empty")
    args = parser.parse_args()

    if args.port:
        serial_port = args.port

    if check_pypozyx_version:
        perform_latest_version_check()

    # shortcut to not have to find out the port yourself
    if serial_port == '':
        serial_port = get_first_pozyx_serial_port()
        print(serial_port)
        if serial_port is None:
            print("No Pozyx connected. Check your USB cable or your driver!")
            quit()

    if not remote:
        remote_id = None

    osc_udp_client = None
    if use_processing:
        osc_udp_client = SimpleUDPClient(ip, network_port)

    # positioning algorithm to use, other is PozyxConstants.POSITIONING_ALGORITHM_TRACKING
    algorithm = PozyxConstants.POSITIONING_ALGORITHM_UWB_ONLY
    # positioning dimension. Others are PozyxConstants.DIMENSION_2D, PozyxConstants.DIMENSION_2_5D
    dimension = PozyxConstants.DIMENSION_3D
    # height of device, required in 2.5D positioning
    height = 1000

    # connect to pozyx device
    try:
        pozyx = PozyxSerial(serial_port)
    except:
        print("Can't connect to serial port. Quit...")
        quit()

    r = ReadyToLocalize(pozyx, osc_udp_client, anchors, algorithm, dimension, height, remote_id)
    r.setup()
    while True:
        try:
            r.loop()
        except KeyboardInterrupt:
            r.close()
            quit()
