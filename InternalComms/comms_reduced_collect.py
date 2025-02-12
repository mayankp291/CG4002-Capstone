import multiprocessing as mp
import os
import signal
from socket import *
import sys
import struct
import threading
from crccheck.crc import Crc8
import time
import datetime
from bluepy.btle import DefaultDelegate, Peripheral, Scanner, BTLEDisconnectError
import csv
import keyboard
import time

# the peripheral class is used to connect and disconnect

# timeouts in seconds
CONNECTION_TIMEOUT = 3

Service_UUID =  "0000dfb0-0000-1000-8000-00805f9b34fb"
Characteristic_UUID = "0000dfb1-0000-1000-8000-00805f9b34fb"


macAddresses = {
    1: "D0:39:72:BF:BF:BB", #imu1
    2: "D0:39:72:BF:C6:07", #VEST1
    3: "D0:39:72:BF:C3:BF", #GUN1
    4: "D0:39:72:BF:C8:A8", #IMU2
    5: "D0:39:72:BF:BF:DD", #vest2
    6: "D0:39:72:BF:C8:CF" #gun2
}

DATA_PACKET_SIZE = 20

SYN_FLAGS = [False] * 6
ACK_FLAGS = [False] * 6

# Device IDs
IMU_PLAYER_1 = 1
VEST_PLAYER_1= 2
GUN_PLAYER_1 = 3
IMU_PLAYER_2 = 4
VEST_PLAYER_2 = 5
GUN_PLAYER_2 = 6

SYN_PACKET = 'S'
ACK_PACKET = 'A'
MOTION_PACKET = 'M'
AMMO_PACKET = 'B'
HEALTH_PACKET = 'H'

arr1 = []
arr2 = []
arr3 =[]
arr4 = []
arr5=[]
arr6=[]

arr11 = []
arr22 = []
arr33 =[]
arr44 = []
arr55 =[]
arr66 =[]

keyPress = False
key_input = ""
counter = 1
ACTION  = 'SHIELD'

NUM_OF_DATA_POINTS = 128
flag = threading.Event()
flag.clear()

class CheckSumFailedError(Exception):
    pass

# each beetle has a delegate to handle BLE transactions
class MyDelegate(DefaultDelegate):
    def __init__(self, playerId, deviceId, dataBuffer, lock, receivingBuffer, hasHandshaken, serialSvc, serialChar):
        DefaultDelegate.__init__(self)
        self.playerId = playerId
        self.deviceId = deviceId
        self.lock = lock
        self.hasHandshaken = hasHandshaken
        self.dataBuffer = dataBuffer
        self.receivingBuffer = receivingBuffer
        self.serialSvc = serialSvc
        self.serialChar = serialChar
        self.motionPacketsCount = 0
        self.gunPacketsCount = 0
        self.fragPacketsCount = 0
        self.startTime = None
        self.endTime = None
        self.transmissionSpeed = 0

    def sendAckPacket(self):
        self.serialChar.write(bytes("A", "utf-8"))

    def handleAckPacket(self):
        ACK_FLAGS[self.deviceId] = True
        print("received ack from beetle")
        self.serialChar.write(bytes('A', encoding="utf-8"))
        print("HandshakeCompleted")
        self.sendAckPacket()
        self.hasHandshaken = True
        # self.startTime = time.time()
        # self.startTime = datetime.now()

    def checkSum(self, data):
        packet = struct.unpack('<20b', data)
        checksum = 0

        for i in range(19):
            checksum = (checksum ^ packet[i])

        if checksum == packet[19]:
            return True
        else:
            return False
        
    def handleCheckSumError(self, data):
        # If there is a problem, then drop
        self.receivingBuffer = b''
        print("Checksum failed for device", self.deviceId ,", packet dropped")

    def savedata(self, data):
        

        global counter
        if flag.is_set():
            motiondata = data['motionData']
            row = list(motiondata.values())
            arr1.append(row[0])
            arr2.append(row[1])
            arr3.append(row[2])
            arr4.append(row[3])
            arr5.append(row[4])
            arr6.append(row[5])
            print("DATA RECV", row)
            
        else:
            # put line
            # newline
            # empty arr
            # only save when arrays are non-empty
            if(arr1):
                print(f"Data collected and saved for {ACTION}, iteration {counter}")
                counter+=1
                file1 = open("../dataCollect/aX.txt", "a")
                file2 = open("../dataCollect/aY.txt", "a")
                file3 = open("../dataCollect/aZ.txt", "a")
                file4 = open("../dataCollect/gX.txt", "a")
                file5 = open("../dataCollect/gY.txt", "a")
                file6 = open("../dataCollect/gZ.txt", "a")
                file7 = open("../dataCollect/action.txt", "a")
                
                # convert list to comma-separated string
                data_str1 = ','.join(str(item) for item in arr1)
                data_str2 = ','.join(str(item) for item in arr2)
                data_str3 = ','.join(str(item) for item in arr3)
                data_str4 = ','.join(str(item) for item in arr4)
                data_str5 = ','.join(str(item) for item in arr5)
                data_str6 = ','.join(str(item) for item in arr6)
                
                # print(data_str1)
                # Write some data to each file
                file1.write(data_str1 + "\n")
                file2.write(data_str2 + "\n")
                file3.write(data_str3 + "\n")
                file4.write(data_str4 + "\n")
                file5.write(data_str5 + "\n")
                file6.write(data_str6 + "\n")
                # 3 GRENADE
                file7.write("1\n")

                # Close all the files
                file1.close()
                file2.close()
                file3.close()
                file4.close()
                file5.close()
                file6.close()

                arr1.clear()
                arr2.clear()
                arr3.clear()
                arr4.clear()
                arr5.clear()
                arr6.clear()
                
                
                
            # print("FLAG UNSET")
            # flag.clear()



    def handleNotification(self, cHandle, data):
        try:

            self.receivingBuffer += data
            if len(self.receivingBuffer) >=20:
                # print("Data received from beetle: ", self.receivingBuffer)
                # self.endTime = time.time()
                # self.endTime = datetime.now()
                # self.transmissionSpeed = (self.motionPacketsCount + self.gunPacketsCount + self.fragPacketsCount) * 8 / (1000 * (self.endTime - self.startTime).total_seconds())
                # if self.endTime - self.startTime > 10:
                #     self.transmissionSpeed = (self.motionPacketsCount + self.gunPacketsCount + self.fragPacketsCount) * 8 / 10

                dataPacket = self.receivingBuffer[0:20]
                if not self.checkSum(dataPacket):
                    raise CheckSumFailedError("Checksum failed")
                unpackedPacket = ()
                expectedPacketFormat = ("bb6h5xb")
                unpackedPacket = struct.unpack_from(expectedPacketFormat, dataPacket, 0)
                # dataPacket = dataPacket[::-1]
                # print(unpackedPacket)
                packetType = chr(unpackedPacket[0])
                # print("packetType, deviceId, length ", packetType , "," , self.deviceId,
                #       ",", len(self.receivingBuffer) )
                # # , ",", self.transmissionSpeed, "kbps"
                # print("Fragmented Packets Count for device:", self.deviceId, ":", self.fragPacketsCount)
                if packetType == 'A':
                    self.handleAckPacket()
                if packetType == 'M':
                    sendData = {
                        "playerID": self.playerId,
                        "beetleID": self.deviceId,
                        "motionData": {
                            "aX": unpackedPacket[2],
                            "aY": unpackedPacket[3],
                            "aZ": unpackedPacket[4],
                            "gX": unpackedPacket[5],
                            "gY": unpackedPacket[6],
                            "gZ": unpackedPacket[7]
                        }
                    }
                    self.motionPacketsCount += 1
                    # print("MotionPacketsCount: ", self.motionPacketsCount)
                    print(sendData)
                    self.savedata(sendData)
                    # self.lock.acquire()
                    # self.dataBuffer.put(sendData)
                    # self.lock.release()

            else:
                self.fragPacketsCount += 1
                self.receivingBuffer = self.receivingBuffer + data
                if len(self.receivingBuffer) == 20:
                    self.handleNotification(None, self.receivingBuffer)
                self.receivingBuffer = b''

        except CheckSumFailedError:
            self.handleCheckSumError(data)



class BeetleConnectionThread:
    def __init__(self, playerId, beetleId, macAddress, dataBuffer, lock, receivingBuffer):
        self.beetleId = beetleId
        self.macAddress = macAddress
        self.dataBuffer = dataBuffer
        self.playerId = playerId
        self.dev = None
        self.deleg = None
        self.lock = lock
        self.serialSvc = None
        self.serialChar = None
        self.receivingBuffer = receivingBuffer
        self.hasHandshaken = False

    def writetoBeetle(self):
        pass

    def openBeetleConnection(self):
        # while True:
        try:
            self.dev = Peripheral(self.macAddress)
            print("Connected to Beetle: ", self.macAddress)
            self.serialSvc = self.dev.getServiceByUUID(Service_UUID)
            self.serialChar = self.serialSvc.getCharacteristics(Characteristic_UUID)[0]
            deviceDelegate = MyDelegate(self.playerId, self.beetleId, self.dataBuffer, self.lock,
                                        self.receivingBuffer, self.hasHandshaken, self.serialSvc, self.serialChar)
            self.dev.withDelegate(deviceDelegate)
            return True
            # break
        except BTLEDisconnectError:
            print("Connection failed")
            return False
            # return


    def startThreeWayHandshake(self, hasHandshake):

        while not hasHandshake:
            self.dev.waitForNotifications(1.0)

            if not SYN_FLAGS[self.beetleId]:
                print("sending syn to beetle")
                self.serialChar.write(bytes('S', encoding="utf-8"))
                SYN_FLAGS[self.beetleId] = True
            if ACK_FLAGS[self.beetleId]:
                print("received ack from beetle")
                self.serialChar.write(bytes('A', encoding="utf-8"))
                hasHandshake = True
                print("HandshakeCompleted")
        return hasHandshake

    def sendSynMessage(self):
        self.dev.waitForNotifications(1.0)
        if not SYN_FLAGS[self.beetleId]:
            print("sending syn to beetle")
            self.serialChar.write(bytes('S', encoding="utf-8"))
            SYN_FLAGS[self.beetleId] = True

    def executeCommunications(self):
        # connect to beetle
        hasHandshake = False
        isConnected = False
        while True:
            try:
                if not hasHandshake:
                    if not isConnected:
                        isConnected = self.openBeetleConnection()
                    # hasHandshake = self.startThreeWayHandshake(hasHandshake)
                    self.sendSynMessage()
                if not self.dev.waitForNotifications(CONNECTION_TIMEOUT):
                    self.hasHandshaken = False
                    isConnected = False
                    hasHandshake = False
                    SYN_FLAGS[self.beetleId] = False
                    ACK_FLAGS[self.beetleId] = False
                    self.dev.disconnect()
                    # continue
                # if keyboard.is_pressed("a"):
                #     self.isKeyPressed = True
                #     global keyPress
                #     keyPress = True
            except KeyboardInterrupt:
                self.dev.disconnect()
                self.hasHandshaken = False
                isConnected = False
                hasHandshake = False
                SYN_FLAGS[self.beetleId] = False
                ACK_FLAGS[self.beetleId] = False
            except BTLEDisconnectError:
                print("Device Disconnected")
                self.hasHandshaken = False
                isConnected = False
                hasHandshake = False
                SYN_FLAGS[self.beetleId] = False
                ACK_FLAGS[self.beetleId] = False

            except Exception:
                pass




class Check_Thread(threading.Thread):
    def __init__(self) -> None:
        super().__init__()
    def run(self):
        while True:
            if keyboard.is_pressed("a"):
                if flag.is_set():
                    print("FLAG IS CLEARED")
                    flag.clear()
                else:
                    flag.set()
                    print("FLAG IS SET")
                time.sleep(0.5)

                
                


if __name__ == '__main__':
    try:
        lock = mp.Lock()

        # using a multiprocessing queue FIFO
        dataBuffer = mp.Queue()
        receivingBuffer1 = b''
        receivingBuffer2 = b''
        receivingBuffer3 = b''


        # Player 1 (IMU)
        IMU1_Beetle = BeetleConnectionThread(1, IMU_PLAYER_1, macAddresses.get(1), dataBuffer, lock, receivingBuffer3)
        IMU1_Thread = threading.Thread(target=IMU1_Beetle.executeCommunications, args = ())
        
        check_thread = Check_Thread()
        check_thread.start()

        IMU1_Thread.start()
        IMU1_Thread.join()
        check_thread.join()
        # while True: time.sleep(100)

        # signal.pause()

    except (KeyboardInterrupt, SystemExit):
        print("Ended Comms")
        # sys.exit()
