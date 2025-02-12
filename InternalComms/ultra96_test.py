#!/usr/bin/env python
# -*- coding: utf-8 -*- 

# Ultra96 Server
from socket import *
from Crypto import Random
from Crypto.Cipher import AES
from Crypto.Util.Padding import pad, unpad
import base64
from multiprocessing import Process, Queue, Lock, queues, Event
import json
import paho.mqtt.client as paho
from paho import mqtt
from ast import literal_eval
import threading
import random
import time
import traceback
from copy import deepcopy
import numpy as np
from scipy.stats import skew
from scipy.fftpack import fft
from pynq import Overlay
from pynq import allocate
import atexit
import os
import pickle
from PlayerState import Player

import tensorflow as tf
import numpy as np
from scipy.stats import skew
from scipy.fftpack import fft
from slidingwindow import SlidingWindow

model = tf.keras.models.load_model('my_model.h5')

# ### kill all child processes on exit
# def cleanup():
#     os.killpg(0, signal.SIGTERM)

# atexit.register(cleanup)

# data = {"playerID": 1, 2, “beetleID”: 1-6, “sensorData”: {}}
# len_data

prediction_array = []
NUM_OUTPUT = 1
NUM_FEATURES = 8
NUM_INPUT = NUM_FEATURES * 6
SAMPLE_SIZE = 40
SHOOT_MAX_TIME_LIMIT = 2
GRENADE_MAX_TIME_LIMIT = 6


beetleID_mapping = {
    1: "IMU1", #imu1
    2: "VEST1", #VEST1
    3: "GUN1", #GUN1
    4: "IMU2", #IMU2
    5: "VEST2", #vest2
    6: "GUN2", #gun2
    7: "TEST"
}

### try

MQTT_USERNAME = "capstonekillingus"
MQTT_PASSWORD = "capstonekillingus"
imu_queue_p1 = Queue()
imu_queue_p2 = Queue()
action_p1_queue = Queue()
action_p2_queue = Queue()
viz_queue = Queue()
eval_queue = Queue()
intcomms_queue = Queue()
recv_queue = Queue()


processing = Event()
processing.clear()
grenadeP1Miss = Event()
grenadeP1Miss.clear()
grenadeP2Miss = Event()
grenadeP2Miss.clear()
grenadeP1Hit = Event()
grenadeP1Hit.clear()
grenadeP2Hit = Event()
grenadeP2Hit.clear()
shootP1Hit = Event()
shootP1Hit.clear()
shootP2Hit = Event()
shootP2Hit.clear()
relayFlag = Event()
relayFlag.set()
reloadSendRelayP1 = Event()
reloadSendRelayP1.clear() 
reloadSendRelayP2 = Event()
reloadSendRelayP2.clear()
evalServerConnected = Event()
evalServerConnected.set()

player_state = {
    "p1":
    {
        "hp": 100,
        "action": "none",
        "bullets": 6,
        "grenades": 2,
        "shield_time": 0,
        "shield_health": 0,
        "num_deaths": 0,
        "num_shield": 3
    },
    "p2":
    {
        "hp": 100,
        "action": "none",
        "bullets": 6,
        "grenades": 2,
        "shield_time": 0,
        "shield_health": 0,
        "num_deaths": 0,
        "num_shield": 3
    }
}

player_state_intcomms = {
    "p1":
    {
        "hp": 100,
        "action": "none",
        "bullets": 6,
    },
    "p2":
    {
        "hp": 100,
        "action": "none",
        "bullets": 6,
    }
}



class Relay_Server_Send(Process):
    def __init__(self, sock):
        super().__init__()
        self.sock = sock
        print("[RELAY_SEND] Ready to send data to Relay")

    
    def run(self):
        while True:
            send_data = intcomms_queue.get()
            send_data = json.loads(send_data)
            ### send RELOAD only if bullets are 0
            # both reload action and 0 bullets
            if reloadSendRelayP1.is_set() and reloadSendRelayP2.is_set():
                reloadSendRelayP1.clear()
                reloadSendRelayP2.clear()
            # p1 0 bullets and p2 non zero bullets
            elif reloadSendRelayP1.is_set():
                reloadSendRelayP1.clear()
                send_data['p2']['action'] = 'none'
            # p2 0 bullets and p1 non zero bullets
            elif reloadSendRelayP2.is_set():
                reloadSendRelayP2.clear()
                send_data['p1']['action'] = 'none'
            self.send(send_data)

    def send(self, data):
        try:
            data = str(data)
            self.sock.sendall(data.encode("utf-8"))
            print('[RELAY_SEND] Sent to Relay Laptop: {}'.format(data))
        except Exception as e:
            print('Connection to Relay Laptop lost')
            print(e)
            # self.relaySocket.close()

# TCP Server to receive data from the Relay Laptops
class Relay_Server(Process):
    def __init__(self, host, port):
        super().__init__()
        self.host = host
        self.port = port
        self.server = socket(AF_INET, SOCK_STREAM)
        self.server.setsockopt(SOL_SOCKET, SO_REUSEADDR, 1)
        self.server.bind((self.host, self.port))

    def run(self):
        self.server.listen(1)
        print("[RELAY SERVER] Listening for connections on host {} port {} \n".format(self.host, self.port))
        while True:
            client, address = self.server.accept()
            # TODO Add client to where it connected to
            print("[RELAY SERVER] Client connected from {} \n".format(address))
            client_handler = Process(
                target=self.handle_client,
                args=(client, address)
            )
            client_handler.start()

    ###
    # Data flow: get len, get msg, check len == len(msg), convert msg to dict
    ###
    def handle_client(self, request, client_address):
        try:
            if relayFlag.is_set():
                relayFlag.clear()
                sending_thread = Relay_Server_Send(request)
                sending_thread.start()
                
            while True:
                # receive data from client
                # (protocol) len(data)_dataRELAY_SEND
                data = b''
                while not data.endswith(b'_'):
                    _d = request.recv(1)
                    if not _d:
                        data = b''
                        break
                    data += _d
                if len(data) == 0:
                    print('no more data from the client')
                    request.close()

                # Get Length of data
                data = data.decode("utf-8")
                length = int(data[:-1])               

                # Get data
                data = b''
                while len(data) < length:
                    _d = request.recv(length - len(data))
                    if not _d:
                        data = b''
                        break
                    data += _d
                if len(data) == 0:
                    print('no more data from the client')

                data = data.decode("utf8")  # Decode raw bytes to UTF-8
                # format string for length and type
                
                # print("[LENGTH] {}, [DATATYPE] {}".format(length, data_type))
                # print("[DATA]", data)                
                
                # check length of data
                if length != len(data):
                    print("Error", data)
                    print('Error: packet length does not match, packet dropped')
                
                else:
                    # convert data to dict {'playerID':, 'beetleID':, 'sensorData':}
                    data = literal_eval(data)

                    ### process incoming data
                    # playerid, data
                    beetleID = data["beetleID"]
                    data_device = beetleID_mapping[beetleID]

                    if not processing.is_set() and (data_device == "IMU1" or data_device == "IMU2"):
                        # convert string to numpy array of ints
                        new_array = np.frombuffer(base64.binascii.a2b_base64(data["sensorData"]), dtype=np.int32).reshape(SAMPLE_SIZE, 6)
                        # print(new_array, new_array.shape)
                        if data_device == "IMU1":
                            imu_queue_p1.put(('p1', new_array))
                            # print("IMU 1 RECV")
                        else:
                            imu_queue_p2.put(('p2', new_array))
                            # print("IMU 2 RECV")
                        
                        # grenadeSendRelay.set()
                    
                    elif data_device == "VEST1":
                        print("VEST 1 RECV")
                        shootP1Hit.set()
                    
                    elif data_device == "VEST2":
                        print("VEST 2 RECV")
                        shootP2Hit.set()

                    elif data_device == "GUN1":
                        # shot by player
                        print("GUN 1 RECV")
                        if evalServerConnected.is_set():
                            action_p1_queue.put("shoot")

                    elif data_device == "GUN2":
                        print("GUN 2 RECV")
                        if evalServerConnected.is_set():
                            action_p2_queue.put("shoot")

        except Exception as e:
            print("Client disconnected")
            request.close()
            print(e)
            traceback.print_exc()


class Game_Engine(Process):
    def __init__(self):
        super().__init__()
        self.p1 = Player()
        self.p2 = Player() 

    def run(self):
        # flow = get both player actions -> process actions -> send to visualizer and eval server -> get updated state from eval server
        while True:
            self.p1.update_shield_time()
            self.p2.update_shield_time()

            # get both player actions
            try:
                action_p1 = action_p1_queue.get(timeout=30)
                action_p2 = action_p2_queue.get(timeout=30)
            except Exception as e:
                print("Game Engine: Timeout waiting for player actions")
                try:
                    while True:
                        action_p1_queue.get_nowait()
                except queues.Empty:
                    pass
                try:
                    while True:
                        action_p2_queue.get_nowait()
                except queues.Empty:
                    pass
                print("Game Engine: Resetting player actions")
                break

            # set flag for processing
            processing.set()

            action_p1_viz = action_p1
            action_p2_viz = action_p2

            # logout
            if action_p1 == "logout" and action_p2 == "logout":
                self.p1.logout()
                self.p2.logout()
            elif action_p1 == "logout":
                self.p1.logout()
                action_p1_viz = "none"
            elif action_p2 == "logout":
                self.p1.logout()
                action_p2_viz = "none"
            
            # shield
            if action_p1 == "shield":
                self.p1.shield()
            
            if action_p2 == "shield":
                self.p2.shield()
            
            # reload
            if action_p1 == "reload":
                if self.p1.bullets <= 0:
                    reloadSendRelayP1.set() 
                self.p1.reload()


            if action_p2 == "reload":
                if self.p2.bullets <= 0:
                    reloadSendRelayP2.set() 
                self.p2.reload()
            
            if action_p1 == "shoot" or action_p2 == "shoot":
                action_p1_viz, action_p2_viz = self.triggerShoot(action_p1, action_p2)
            
            if action_p1 == "grenade" or action_p2 == "grenade":
                action_p1_viz, action_p2_viz = self.triggerGrenade(action_p1_viz, action_p2_viz)

            self.p1.update_shield_time()
            self.p2.update_shield_time()
            viz_dict = {"p1": self.p1.get_dict(), "p2": self.p2.get_dict()}
            viz_dict["p1"]["action"] = action_p1_viz
            viz_dict["p2"]["action"] = action_p2_viz
            viz_queue.put(('STATE', json.dumps(viz_dict)))
            eval_dict = {"p1": self.p1.get_dict(), "p2": self.p2.get_dict()}
            # print("[INTERNAL STATE]", eval_dict)
            eval_queue.put(json.dumps(eval_dict))

            # clear all the flags
            shootP1Hit.clear()
            shootP2Hit.clear()
            grenadeP1Hit.clear()
            grenadeP2Hit.clear()
            grenadeP1Miss.clear()
            grenadeP2Miss.clear()
            # sync states
            recv_state = recv_queue.get()
            # update internal state from eval server
            self.p1.initialize_from_dict(recv_state["p1"])
            self.p2.initialize_from_dict(recv_state["p2"])
            # send_dict = {"p1": self.p1.get_dict(), "p2": self.p2.get_dict()}
            # print("[SYNCED STATE]", send_dict)

            # clear processing flag
            processing.clear()

    def triggerShoot(self, action_p1, action_p2):
        action_p1_viz = action_p1
        action_p2_viz = action_p2
        isPlayerOneShootInvalid = (self.p1.bullets <= 0)
        isPlayerTwoShootInvalid = (self.p2.bullets <= 0)
        # both shoot
        if action_p1 == "shoot" and action_p2 == "shoot":
            self.p1.shoot()
            self.p2.shoot()
            start_time = time.time()
            # check until time, if vest not recv send as miss
            while time.time() - start_time < SHOOT_MAX_TIME_LIMIT:
                # as both are in range of each other only one needs to be checked
                if shootP1Hit.is_set() or shootP2Hit.is_set():
                    # udpate internal state for shoot hit
                    self.p1.shoot_hit()
                    self.p2.shoot_hit()
                    action_p1_viz = "shoot_p2_hits"
                    action_p2_viz = "shoot_p1_hits"
                    break
            if not shootP1Hit.is_set() and not shootP2Hit.is_set():
                # clear flags
                action_p1_viz = "shoot_p2_misses"
                action_p2_viz = "shoot_p1_misses"
            if isPlayerOneShootInvalid:
                action_p1_viz = "shoot_p2_invalid"
            if isPlayerTwoShootInvalid:
                action_p2_viz = "shoot_p1_invalid"
        elif action_p1 == "shoot":
            self.p1.shoot()
            start_time = time.time()
            while time.time() - start_time < SHOOT_MAX_TIME_LIMIT:
                if shootP2Hit.is_set():
                    self.p2.shoot_hit()
                    action_p1_viz = "shoot_p2_hits"
                    break
            if not shootP2Hit.is_set():
                if isPlayerOneShootInvalid:
                    action_p1_viz = "shoot_p2_invalid"
                else:
                    action_p1_viz = "shoot_p2_misses"
        else:
            self.p2.shoot()
            start_time = time.time()
            while time.time() - start_time < SHOOT_MAX_TIME_LIMIT:
                if shootP1Hit.is_set():
                    self.p1.shoot_hit()
                    action_p2_viz = "shoot_p1_hits"
                    break
            if not shootP1Hit.is_set():
                if isPlayerTwoShootInvalid:
                    action_p2_viz = "shoot_p1_invalid"
                else:
                    action_p2_viz = "shoot_p1_misses"
        return action_p1_viz, action_p2_viz

    def triggerGrenade(self, action_p1, action_p2):
        action_p1_viz = "none"
        action_p2_viz = "none"
        isPlayerOneGrenadeInvalid = (self.p1.grenades <= 0)
        isPlayerTwoGrenadeInvalid = (self.p2.grenades <= 0)
        if action_p1 == "grenade" and action_p2 == "grenade":
            self.p1.grenade()
            self.p2.grenade()
            if isPlayerOneGrenadeInvalid and isPlayerTwoGrenadeInvalid:
                # when two players have insufficient number of grenades
                return action_p1, action_p2
            start_time = time.time()
            send_dict = {"p1": self.p1.get_dict(), "p2": self.p2.get_dict()}
            send_dict["p1"]["action"] = action_p1
            send_dict["p2"]["action"] = action_p2
            # send check
            viz_queue.put(('CHECK', json.dumps(send_dict)))
            # wait for 3 sec
            while (time.time() - start_time) < GRENADE_MAX_TIME_LIMIT:
                # as both are in range of each other only one needs to be checked
                if grenadeP1Hit.is_set() or grenadeP2Hit.is_set():
                    if not isPlayerOneGrenadeInvalid:
                        self.p1.grenade_hit()
                        action_p1_viz = "grenade_p2_hits"
                    if not isPlayerTwoGrenadeInvalid:
                        self.p2.grenade_hit()
                        action_p2_viz = "grenade_p1_hits"
                    break
                elif grenadeP1Miss.is_set() or grenadeP2Miss.is_set():
                    if not isPlayerOneGrenadeInvalid:
                        action_p1_viz = "grenade_p2_misses"
                    if not isPlayerTwoGrenadeInvalid:
                        action_p2_viz = "grenade_p1_misses"
                    break
        elif action_p1 == "grenade":
            self.p1.grenade()
            if isPlayerOneGrenadeInvalid:
                # when player one have insufficient number of grenades
                return action_p1, action_p2
            send_dict = {"p1": self.p1.get_dict(), "p2": self.p2.get_dict()}
            send_dict["p1"]["action"] = action_p1
            send_dict["p2"]["action"] = action_p2
            viz_queue.put(('CHECK', json.dumps(send_dict)))
            start_time = time.time()
            while time.time() - start_time < GRENADE_MAX_TIME_LIMIT:
                if grenadeP2Hit.is_set():
                    self.p2.grenade_hit()
                    action_p1_viz = "grenade_p2_hits"
                    break
                elif grenadeP2Miss.is_set():
                    action_p1_viz = "grenade_p2_misses"
                    break   
        else:
            self.p2.grenade()
            if isPlayerTwoGrenadeInvalid:
                # when player two have insufficient number of grenades
                return action_p1, action_p2
            send_dict = {"p1": self.p1.get_dict(), "p2": self.p2.get_dict()}
            send_dict["p1"]["action"] = action_p1
            send_dict["p2"]["action"] = action_p2
            viz_queue.put(('CHECK', json.dumps(send_dict)))
            start_time = time.time()
            while time.time() - start_time < GRENADE_MAX_TIME_LIMIT:
                if grenadeP1Hit.is_set():
                    self.p1.grenade_hit()
                    action_p2_viz = "grenade_p1_hits"
                    break
                elif grenadeP1Miss.is_set():
                    action_p2_viz = "grenade_p1_misses"
                    break  
        return action_p1_viz, action_p2_viz

class AI_Process(Process):
    def __init__(self, q):
        super().__init__()
        # DMA BUFFER CONFIG
        self.ol = Overlay('new_design_1_wrapper.bit')
        self.dma = self.ol.axi_dma_0
        self.input_buffer = allocate(shape=(NUM_INPUT), dtype=np.int32)
        self.output_buffer = allocate(shape=(NUM_OUTPUT,), dtype=np.int32)
        self.imu_data = np.empty((40,6), dtype=np.int32)
        self.imu_queue = q
        self.player = None
        self.features = None


    def run(self):
        while True:
            self.player, self.imu_data = self.imu_queue.get()
            self.AI_actual()
                
    def extract_features(self):

        mean_acc_x = np.mean(self.imu_data[0])
        mean_acc_y = np.mean(self.imu_data[1])
        mean_acc_z = np.mean(self.imu_data[2])
        mean_gyro_x = np.mean(self.imu_data[3])
        mean_gyro_y = np.mean(self.imu_data[4])
        mean_gyro_z = np.mean(self.imu_data[5])

        sd_acc_x = np.std(self.imu_data[0])
        sd_acc_y = np.std(self.imu_data[1])
        sd_acc_z = np.std(self.imu_data[2])
        sd_gyro_x = np.std(self.imu_data[3])
        sd_gyro_y = np.std(self.imu_data[4])
        sd_gyro_z = np.std(self.imu_data[5])

        max_acc_x = np.amax(self.imu_data[0])
        max_acc_y = np.amax(self.imu_data[1])
        max_acc_z = np.amax(self.imu_data[2])
        max_gyro_x = np.amax(self.imu_data[3])
        max_gyro_y = np.amax(self.imu_data[4])
        max_gyro_z = np.amax(self.imu_data[5])

        min_acc_x = np.amin(self.imu_data[0])
        min_acc_y = np.amin(self.imu_data[1])
        min_acc_z = np.amin(self.imu_data[2])
        min_gyro_x = np.amin(self.imu_data[3])
        min_gyro_y = np.amin(self.imu_data[4])
        min_gyro_z = np.amin(self.imu_data[5])

        rms_acc_x = np.sqrt(np.mean(self.imu_data[0] ** 2))
        rms_acc_y = np.sqrt(np.mean(self.imu_data[1] ** 2))
        rms_acc_z = np.sqrt(np.mean(self.imu_data[2] ** 2))
        rms_gyro_x = np.sqrt(np.mean(self.imu_data[3] ** 2))
        rms_gyro_y = np.sqrt(np.mean(self.imu_data[4] ** 2))
        rms_gyro_z = np.sqrt(np.mean(self.imu_data[5] ** 2))

        skew_acc_x = skew(self.imu_data[0])
        skew_acc_y = skew(self.imu_data[1])
        skew_acc_z = skew(self.imu_data[2])
        skew_gyro_x = skew(self.imu_data[3])
        skew_gyro_y = skew(self.imu_data[4])
        skew_gyro_z = skew(self.imu_data[5])

        mag_acc_x = np.amax(np.abs(fft(self.imu_data[0])))
        mag_acc_y = np.amax(np.abs(fft(self.imu_data[1])))
        mag_acc_z = np.amax(np.abs(fft(self.imu_data[2])))
        mag_gyro_x = np.amax(np.abs(fft(self.imu_data[3])))
        mag_gyro_y = np.amax(np.abs(fft(self.imu_data[4])))
        mag_gyro_z = np.amax(np.abs(fft(self.imu_data[5])))

        phase_acc_x = np.amax(np.angle(fft(self.imu_data[0])))
        phase_acc_y = np.amax(np.angle(fft(self.imu_data[1])))
        phase_acc_z = np.amax(np.angle(fft(self.imu_data[2])))
        phase_gyro_x = np.amax(np.angle(fft(self.imu_data[3])))
        phase_gyro_y = np.amax(np.angle(fft(self.imu_data[4])))
        phase_gyro_z = np.amax(np.angle(fft(self.imu_data[5])))

        self.features = np.array([mean_acc_x, mean_acc_y, mean_acc_z, mean_gyro_x, mean_gyro_y, mean_gyro_z, sd_acc_x,
                               sd_acc_y, sd_acc_z, sd_gyro_x, sd_gyro_y, sd_gyro_z,
                               max_acc_x, max_acc_y, max_acc_z, max_gyro_x, max_gyro_y, max_gyro_z,
                               min_acc_x, min_acc_y, min_acc_z, min_gyro_x, min_gyro_y, min_gyro_z,
                               rms_acc_x, rms_acc_y, rms_acc_z, rms_gyro_x, rms_gyro_y, rms_gyro_z,
                               skew_acc_x, skew_acc_y, skew_acc_z, skew_gyro_x, skew_gyro_y, skew_gyro_z,
                               mag_acc_x, mag_acc_y, mag_acc_z, mag_gyro_x, mag_gyro_y, mag_gyro_z,
                               phase_acc_x, phase_acc_y, phase_acc_z, phase_gyro_x, phase_gyro_y, phase_gyro_z]).astype(np.int32)
        

    def detect_start_of_move(self):

        # define threshold values as hard-coded values
        ## OLD
        # x_thresh = 18300
        # y_thresh = 11000
        # z_thresh = 17000
        
        # ## NEW
        # x_thresh = 19300
        # y_thresh = 15000
        # z_thresh = 18000

        ## TEST
        x_thresh = 19300
        y_thresh = 13000
        z_thresh = 18000   

        # x_thresh = 15300
        # y_thresh = 9000
        # z_thresh = 18000 

        # x_thresh = y_thresh = z_thresh = 9000

        # np_imu_data = np.array(self.imu_data)

        # compare each data point in window to threshold
        for j in range(self.imu_data.shape[0]):
            acc_vals = self.imu_data[j, :3]

            if (abs(acc_vals[0]) > x_thresh) or (abs(acc_vals[1]) > y_thresh) or (abs(acc_vals[2]) > z_thresh):
                # potential start of move action identified
                # check next few data points to confirm start of move action
                for k in range(j+1, j+4):
                    try:
                        next_acc_vals = self.imu_data[k, :3]

                    except IndexError:
                        # if index is out of range, move to next window
                        break

                    if not ((abs(next_acc_vals[0]) > x_thresh) or (abs(next_acc_vals[1]) > y_thresh) or (abs(next_acc_vals[2]) > z_thresh)):
                        # not the start of move action, move to next window
                        break
                else:
                    # confirmed start of move action
                    # np_imu_data = np_imu_data[j:]
                    # print("Start of move action detected", self.imu_data.shape)
                    self.imu_data = np.transpose(self.imu_data)
                    # print(self.imu_data.shape)
                    return 
                    # return self.imu_data.T

        # return None
        self.imu_data = None


    def detect_start_of_move2(self, imu_data):

        ## TEST
        x_thresh = 19300
        y_thresh = 13000
        z_thresh = 18000   

        np_imu_data = np.array(imu_data)

        # compare each data point in window to threshold
        abs_acc_vals = np.abs(np_imu_data[:, :3])
        mask = (abs_acc_vals > [x_thresh, y_thresh, z_thresh]).any(axis=1)
        idx = np.argmax(mask)
        if mask[idx]:
            # potential start of move action identified
            # check next few data points to confirm start of move action
            k = min(idx+4, np_imu_data.shape[0])

            # Try the below two lines for mask and see if either one is correct
            mask = (abs_acc_vals[idx+1:k] > [x_thresh, y_thresh, z_thresh]).any(axis=1)

            # mask = (np.abs(np_imu_data[idx+1:k, :3]) > [x_thresh, y_thresh, z_thresh]).any(axis=1)
            if not mask.any():
                # confirmed start of move action
                # np_imu_data = np_imu_data[idx:]
                return np_imu_data.T

        return None
    

    def detect_start_of_move3(self):
        x_thresh = 19300
        y_thresh = 13000
        z_thresh = 18000   

        np_imu_data = np.array(self.imu_data)

        # Sliding window approach with window size of 5
        window_size = 5
        for j in range(0, np_imu_data.shape[0] - window_size + 1, window_size):
            acc_vals = np_imu_data[j:j+window_size, :3]
            
            # Check if any of the values in the window exceed the threshold
            if (np.abs(acc_vals) > [x_thresh, y_thresh, z_thresh]).any():
                # potential start of move action identified
                # Check next few windows to confirm start of move action
                for k in range(j+window_size, j+window_size*4, window_size):
                    next_acc_vals = np_imu_data[k:k+window_size, :3]
                    if not (np.abs(next_acc_vals) > [x_thresh, y_thresh, z_thresh]).any():
                        # not the start of move action, move to next window
                        break
                else:
                    # confirmed start of move action
                    np_imu_data = np_imu_data[j:]
                    return np_imu_data.T

        return None



    def AI_actual(self):
        global prediction_array, NUM_INPUT
        
        self.detect_start_of_move()

        if self.imu_data is None:
            return None

        mapping = {0: 'logout', 1: 'shield', 2: 'reload', 3: 'grenade', 4: 'idle'}
        self.extract_features()

        predictions = model.predict(imu_data, verbose=False)
        predicted_class = np.argmax(predictions[0])
        print("PREDICTED CLASS", self.player, predicted_class)
        # prediction_array.append(predicted_class)

        # for i in range(NUM_INPUT):
        #     self.input_buffer[i] = self.features[i]

        # run = True
        # while run:
        #     try:
        #         # aiflag.clear()
        #         self.dma.sendchannel.transfer(self.input_buffer)
        #         self.dma.recvchannel.transfer(self.output_buffer)
        #         self.dma.sendchannel.wait()
        #         self.dma.recvchannel.wait()

        #         action = self.output_buffer[0]

        #         # prediction_array.append(action)
        #         print('Predicted class:', self.player, action, mapping[action])
                
        #         run = False
        #         if not mapping[action] == 'idle':
        #             if self.player == 'p1':
        #                 if evalServerConnected.is_set():
        #                     action_p1_queue.put(mapping[action])
        #             else:
        #                 if evalServerConnected.is_set():
        #                     action_p2_queue.put(mapping[action])

        #     except RuntimeError as e:
        #         print(e)
        #         break


class AI_Thread_1(Process):
    def __init__(self):
        super().__init__()
        # DMA BUFFER CONFIG
        self.ol = Overlay('new_design_1_wrapper.bit')
        self.dma = self.ol.axi_dma_0
        self.input_buffer = allocate(shape=(NUM_INPUT), dtype=np.int32)
        self.output_buffer = allocate(shape=(NUM_OUTPUT,), dtype=np.int32)
        self.imu_data = np.empty((40,6), dtype=np.int32)
        self.player = None
        self.features = None


    def run(self):
        while True:
            self.player, self.imu_data = imu_queue_p1.get()
            self.AI_actual()
                
    def extract_features(self):

        mean_acc_x = np.mean(self.imu_data[0])
        mean_acc_y = np.mean(self.imu_data[1])
        mean_acc_z = np.mean(self.imu_data[2])
        mean_gyro_x = np.mean(self.imu_data[3])
        mean_gyro_y = np.mean(self.imu_data[4])
        mean_gyro_z = np.mean(self.imu_data[5])

        sd_acc_x = np.std(self.imu_data[0])
        sd_acc_y = np.std(self.imu_data[1])
        sd_acc_z = np.std(self.imu_data[2])
        sd_gyro_x = np.std(self.imu_data[3])
        sd_gyro_y = np.std(self.imu_data[4])
        sd_gyro_z = np.std(self.imu_data[5])

        max_acc_x = np.amax(self.imu_data[0])
        max_acc_y = np.amax(self.imu_data[1])
        max_acc_z = np.amax(self.imu_data[2])
        max_gyro_x = np.amax(self.imu_data[3])
        max_gyro_y = np.amax(self.imu_data[4])
        max_gyro_z = np.amax(self.imu_data[5])

        min_acc_x = np.amin(self.imu_data[0])
        min_acc_y = np.amin(self.imu_data[1])
        min_acc_z = np.amin(self.imu_data[2])
        min_gyro_x = np.amin(self.imu_data[3])
        min_gyro_y = np.amin(self.imu_data[4])
        min_gyro_z = np.amin(self.imu_data[5])

        rms_acc_x = np.sqrt(np.mean(self.imu_data[0] ** 2))
        rms_acc_y = np.sqrt(np.mean(self.imu_data[1] ** 2))
        rms_acc_z = np.sqrt(np.mean(self.imu_data[2] ** 2))
        rms_gyro_x = np.sqrt(np.mean(self.imu_data[3] ** 2))
        rms_gyro_y = np.sqrt(np.mean(self.imu_data[4] ** 2))
        rms_gyro_z = np.sqrt(np.mean(self.imu_data[5] ** 2))

        skew_acc_x = skew(self.imu_data[0])
        skew_acc_y = skew(self.imu_data[1])
        skew_acc_z = skew(self.imu_data[2])
        skew_gyro_x = skew(self.imu_data[3])
        skew_gyro_y = skew(self.imu_data[4])
        skew_gyro_z = skew(self.imu_data[5])

        mag_acc_x = np.amax(np.abs(fft(self.imu_data[0])))
        mag_acc_y = np.amax(np.abs(fft(self.imu_data[1])))
        mag_acc_z = np.amax(np.abs(fft(self.imu_data[2])))
        mag_gyro_x = np.amax(np.abs(fft(self.imu_data[3])))
        mag_gyro_y = np.amax(np.abs(fft(self.imu_data[4])))
        mag_gyro_z = np.amax(np.abs(fft(self.imu_data[5])))

        phase_acc_x = np.amax(np.angle(fft(self.imu_data[0])))
        phase_acc_y = np.amax(np.angle(fft(self.imu_data[1])))
        phase_acc_z = np.amax(np.angle(fft(self.imu_data[2])))
        phase_gyro_x = np.amax(np.angle(fft(self.imu_data[3])))
        phase_gyro_y = np.amax(np.angle(fft(self.imu_data[4])))
        phase_gyro_z = np.amax(np.angle(fft(self.imu_data[5])))

        self.features = np.array([mean_acc_x, mean_acc_y, mean_acc_z, mean_gyro_x, mean_gyro_y, mean_gyro_z, sd_acc_x,
                               sd_acc_y, sd_acc_z, sd_gyro_x, sd_gyro_y, sd_gyro_z,
                               max_acc_x, max_acc_y, max_acc_z, max_gyro_x, max_gyro_y, max_gyro_z,
                               min_acc_x, min_acc_y, min_acc_z, min_gyro_x, min_gyro_y, min_gyro_z,
                               rms_acc_x, rms_acc_y, rms_acc_z, rms_gyro_x, rms_gyro_y, rms_gyro_z,
                               skew_acc_x, skew_acc_y, skew_acc_z, skew_gyro_x, skew_gyro_y, skew_gyro_z,
                               mag_acc_x, mag_acc_y, mag_acc_z, mag_gyro_x, mag_gyro_y, mag_gyro_z,
                               phase_acc_x, phase_acc_y, phase_acc_z, phase_gyro_x, phase_gyro_y, phase_gyro_z]).astype(np.int32)
        

    def detect_start_of_move(self):

        # define threshold values as hard-coded values
        ## OLD
        # x_thresh = 18300
        # y_thresh = 11000
        # z_thresh = 17000
        
        # ## NEW
        # x_thresh = 19300
        # y_thresh = 15000
        # z_thresh = 18000

        ## TEST
        x_thresh = 19300
        y_thresh = 13000
        z_thresh = 18000   

        # x_thresh = 15300
        # y_thresh = 9000
        # z_thresh = 18000 

        # x_thresh = y_thresh = z_thresh = 9000

        # np_imu_data = np.array(self.imu_data)

        # compare each data point in window to threshold
        for j in range(self.imu_data.shape[0]):
            acc_vals = self.imu_data[j, :3]

            if (abs(acc_vals[0]) > x_thresh) or (abs(acc_vals[1]) > y_thresh) or (abs(acc_vals[2]) > z_thresh):
                # potential start of move action identified
                # check next few data points to confirm start of move action
                for k in range(j+1, j+4):
                    try:
                        next_acc_vals = self.imu_data[k, :3]

                    except IndexError:
                        # if index is out of range, move to next window
                        break

                    if not ((abs(next_acc_vals[0]) > x_thresh) or (abs(next_acc_vals[1]) > y_thresh) or (abs(next_acc_vals[2]) > z_thresh)):
                        # not the start of move action, move to next window
                        break
                else:
                    # confirmed start of move action
                    # np_imu_data = np_imu_data[j:]
                    # print("Start of move action detected", self.imu_data.shape)
                    self.imu_data = np.transpose(self.imu_data)
                    # print(self.imu_data.shape)
                    return 
                    # return self.imu_data.T

        # return None
        self.imu_data = None


    def detect_start_of_move2(self, imu_data):

        ## TEST
        x_thresh = 19300
        y_thresh = 13000
        z_thresh = 18000   

        np_imu_data = np.array(imu_data)

        # compare each data point in window to threshold
        abs_acc_vals = np.abs(np_imu_data[:, :3])
        mask = (abs_acc_vals > [x_thresh, y_thresh, z_thresh]).any(axis=1)
        idx = np.argmax(mask)
        if mask[idx]:
            # potential start of move action identified
            # check next few data points to confirm start of move action
            k = min(idx+4, np_imu_data.shape[0])

            # Try the below two lines for mask and see if either one is correct
            mask = (abs_acc_vals[idx+1:k] > [x_thresh, y_thresh, z_thresh]).any(axis=1)

            # mask = (np.abs(np_imu_data[idx+1:k, :3]) > [x_thresh, y_thresh, z_thresh]).any(axis=1)
            if not mask.any():
                # confirmed start of move action
                # np_imu_data = np_imu_data[idx:]
                return np_imu_data.T

        return None
    

    def detect_start_of_move3(self):
        x_thresh = 19300
        y_thresh = 13000
        z_thresh = 18000   

        np_imu_data = np.array(self.imu_data)

        # Sliding window approach with window size of 5
        window_size = 5
        for j in range(0, np_imu_data.shape[0] - window_size + 1, window_size):
            acc_vals = np_imu_data[j:j+window_size, :3]
            
            # Check if any of the values in the window exceed the threshold
            if (np.abs(acc_vals) > [x_thresh, y_thresh, z_thresh]).any():
                # potential start of move action identified
                # Check next few windows to confirm start of move action
                for k in range(j+window_size, j+window_size*4, window_size):
                    next_acc_vals = np_imu_data[k:k+window_size, :3]
                    if not (np.abs(next_acc_vals) > [x_thresh, y_thresh, z_thresh]).any():
                        # not the start of move action, move to next window
                        break
                else:
                    # confirmed start of move action
                    np_imu_data = np_imu_data[j:]
                    return np_imu_data.T

        return None



    def AI_actual(self):
        global prediction_array, NUM_INPUT

        # parsed_imu_data = self.detect_start_of_move2(imu_data)

        # parsed_imu_data = self.detect_start_of_move3(imu_data)
        
        # parsed_imu_data = self.detect_start_of_move()
        self.detect_start_of_move()

        # if parsed_imu_data is None:
        #     print("No move detected")
        #     return None
        if self.imu_data is None:
            # print("No move detected")
            return None

        mapping = {0: 'logout', 1: 'shield', 2: 'reload', 3: 'grenade', 4: 'idle'}
        self.extract_features()
        # features = self.extract_features(parsed_imu_data)

        for i in range(NUM_INPUT):
            self.input_buffer[i] = self.features[i]

        run = True

        while run:
            try:
                # aiflag.clear()
                self.dma.sendchannel.transfer(self.input_buffer)
                self.dma.recvchannel.transfer(self.output_buffer)
                self.dma.sendchannel.wait()
                self.dma.recvchannel.wait()

                action = self.output_buffer[0]

                # prediction_array.append(action)
                print('Predicted class:', self.player, action, mapping[action])
                
                run = False
                if not mapping[action] == 'idle':
                    if self.player == 'p1':
                        if evalServerConnected.is_set():
                            action_p1_queue.put(mapping[action])
                    else:
                        if evalServerConnected.is_set():
                            action_p2_queue.put(mapping[action])

                # aiflag.set()
            except RuntimeError as e:
                print(e)
                # print("Error config: ", self.dma.register_map)


class AI_Thread_2(Process):
    def __init__(self):
        super().__init__()
        # DMA BUFFER CONFIG
        self.ol = Overlay('new_design_1_wrapper.bit')
        self.dma = self.ol.axi_dma_0
        self.input_buffer = allocate(shape=(NUM_INPUT), dtype=np.int32)
        self.output_buffer = allocate(shape=(NUM_OUTPUT,), dtype=np.int32)
        self.imu_data = np.empty((40,6), dtype=np.int32)
        self.player = None
        self.features = None


    def run(self):
        while True:
            # if not imu_queue_p1.empty() or not imu_queue_p2.empty():
            #     ### get player id (p1 or p2)
            # try:
            #     # if aiflag.is_set():
            #     self.player, self.imu_data = imu_queue_p1.get_nowait()
            #     self.AI_actual()
            #     # player, imu_data = imu_queue_p1.get_nowait()
            #     # self.AI_actual(player, imu_data)
            # except:
                # pass
            # try:
            #     # if aiflag.is_set():
            #     self.player, self.imu_data = imu_queue_p2.get_nowait()
            #     self.AI_actual()
            #     # player, imu_data = imu_queue_p2.get_nowait()
            #     # self.AI_actual(player, imu_data)
            # except:
            #     pass
            # if imu_queue_p1.empty
            self.player, self.imu_data = imu_queue_p2.get()
            self.AI_actual()
                
    def extract_features(self):

        mean_acc_x = np.mean(self.imu_data[0])
        mean_acc_y = np.mean(self.imu_data[1])
        mean_acc_z = np.mean(self.imu_data[2])
        mean_gyro_x = np.mean(self.imu_data[3])
        mean_gyro_y = np.mean(self.imu_data[4])
        mean_gyro_z = np.mean(self.imu_data[5])

        sd_acc_x = np.std(self.imu_data[0])
        sd_acc_y = np.std(self.imu_data[1])
        sd_acc_z = np.std(self.imu_data[2])
        sd_gyro_x = np.std(self.imu_data[3])
        sd_gyro_y = np.std(self.imu_data[4])
        sd_gyro_z = np.std(self.imu_data[5])

        max_acc_x = np.amax(self.imu_data[0])
        max_acc_y = np.amax(self.imu_data[1])
        max_acc_z = np.amax(self.imu_data[2])
        max_gyro_x = np.amax(self.imu_data[3])
        max_gyro_y = np.amax(self.imu_data[4])
        max_gyro_z = np.amax(self.imu_data[5])

        min_acc_x = np.amin(self.imu_data[0])
        min_acc_y = np.amin(self.imu_data[1])
        min_acc_z = np.amin(self.imu_data[2])
        min_gyro_x = np.amin(self.imu_data[3])
        min_gyro_y = np.amin(self.imu_data[4])
        min_gyro_z = np.amin(self.imu_data[5])

        rms_acc_x = np.sqrt(np.mean(self.imu_data[0] ** 2))
        rms_acc_y = np.sqrt(np.mean(self.imu_data[1] ** 2))
        rms_acc_z = np.sqrt(np.mean(self.imu_data[2] ** 2))
        rms_gyro_x = np.sqrt(np.mean(self.imu_data[3] ** 2))
        rms_gyro_y = np.sqrt(np.mean(self.imu_data[4] ** 2))
        rms_gyro_z = np.sqrt(np.mean(self.imu_data[5] ** 2))

        skew_acc_x = skew(self.imu_data[0])
        skew_acc_y = skew(self.imu_data[1])
        skew_acc_z = skew(self.imu_data[2])
        skew_gyro_x = skew(self.imu_data[3])
        skew_gyro_y = skew(self.imu_data[4])
        skew_gyro_z = skew(self.imu_data[5])

        mag_acc_x = np.amax(np.abs(fft(self.imu_data[0])))
        mag_acc_y = np.amax(np.abs(fft(self.imu_data[1])))
        mag_acc_z = np.amax(np.abs(fft(self.imu_data[2])))
        mag_gyro_x = np.amax(np.abs(fft(self.imu_data[3])))
        mag_gyro_y = np.amax(np.abs(fft(self.imu_data[4])))
        mag_gyro_z = np.amax(np.abs(fft(self.imu_data[5])))

        phase_acc_x = np.amax(np.angle(fft(self.imu_data[0])))
        phase_acc_y = np.amax(np.angle(fft(self.imu_data[1])))
        phase_acc_z = np.amax(np.angle(fft(self.imu_data[2])))
        phase_gyro_x = np.amax(np.angle(fft(self.imu_data[3])))
        phase_gyro_y = np.amax(np.angle(fft(self.imu_data[4])))
        phase_gyro_z = np.amax(np.angle(fft(self.imu_data[5])))

        self.features = np.array([mean_acc_x, mean_acc_y, mean_acc_z, mean_gyro_x, mean_gyro_y, mean_gyro_z, sd_acc_x,
                               sd_acc_y, sd_acc_z, sd_gyro_x, sd_gyro_y, sd_gyro_z,
                               max_acc_x, max_acc_y, max_acc_z, max_gyro_x, max_gyro_y, max_gyro_z,
                               min_acc_x, min_acc_y, min_acc_z, min_gyro_x, min_gyro_y, min_gyro_z,
                               rms_acc_x, rms_acc_y, rms_acc_z, rms_gyro_x, rms_gyro_y, rms_gyro_z,
                               skew_acc_x, skew_acc_y, skew_acc_z, skew_gyro_x, skew_gyro_y, skew_gyro_z,
                               mag_acc_x, mag_acc_y, mag_acc_z, mag_gyro_x, mag_gyro_y, mag_gyro_z,
                               phase_acc_x, phase_acc_y, phase_acc_z, phase_gyro_x, phase_gyro_y, phase_gyro_z]).astype(np.int32)
        

    def detect_start_of_move(self):

        # define threshold values as hard-coded values
        # ## OLD
        # x_thresh = 18300
        # y_thresh = 11000
        # z_thresh = 17000
        
        # ## NEW
        # x_thresh = 19300
        # y_thresh = 15000
        # z_thresh = 18000

        ## TEST
        x_thresh = 19300
        y_thresh = 13000
        z_thresh = 18000   

        # x_thresh = 15300
        # y_thresh = 9000
        # z_thresh = 18000 

        # x_thresh = y_thresh = z_thresh = 9000

        # np_imu_data = np.array(self.imu_data)

        # compare each data point in window to threshold
        for j in range(self.imu_data.shape[0]):
            acc_vals = self.imu_data[j, :3]

            if (abs(acc_vals[0]) > x_thresh) or (abs(acc_vals[1]) > y_thresh) or (abs(acc_vals[2]) > z_thresh):
                # potential start of move action identified
                # check next few data points to confirm start of move action
                for k in range(j+1, j+4):
                    try:
                        next_acc_vals = self.imu_data[k, :3]

                    except IndexError:
                        # if index is out of range, move to next window
                        break

                    if not ((abs(next_acc_vals[0]) > x_thresh) or (abs(next_acc_vals[1]) > y_thresh) or (abs(next_acc_vals[2]) > z_thresh)):
                        # not the start of move action, move to next window
                        break
                else:
                    # confirmed start of move action
                    # np_imu_data = np_imu_data[j:]
                    # print("Start of move action detected", self.imu_data.shape)
                    self.imu_data = np.transpose(self.imu_data)
                    # print(self.imu_data.shape)
                    return 
                    # return self.imu_data.T

        # return None
        self.imu_data = None


    def detect_start_of_move2(self, imu_data):

        ## TEST
        x_thresh = 19300
        y_thresh = 13000
        z_thresh = 18000   

        np_imu_data = np.array(imu_data)

        # compare each data point in window to threshold
        abs_acc_vals = np.abs(np_imu_data[:, :3])
        mask = (abs_acc_vals > [x_thresh, y_thresh, z_thresh]).any(axis=1)
        idx = np.argmax(mask)
        if mask[idx]:
            # potential start of move action identified
            # check next few data points to confirm start of move action
            k = min(idx+4, np_imu_data.shape[0])

            # Try the below two lines for mask and see if either one is correct
            mask = (abs_acc_vals[idx+1:k] > [x_thresh, y_thresh, z_thresh]).any(axis=1)

            # mask = (np.abs(np_imu_data[idx+1:k, :3]) > [x_thresh, y_thresh, z_thresh]).any(axis=1)
            if not mask.any():
                # confirmed start of move action
                # np_imu_data = np_imu_data[idx:]
                return np_imu_data.T

        return None
    

    def detect_start_of_move3(self):
        x_thresh = 19300
        y_thresh = 13000
        z_thresh = 18000   

        np_imu_data = np.array(self.imu_data)

        # Sliding window approach with window size of 5
        window_size = 5
        for j in range(0, np_imu_data.shape[0] - window_size + 1, window_size):
            acc_vals = np_imu_data[j:j+window_size, :3]
            
            # Check if any of the values in the window exceed the threshold
            if (np.abs(acc_vals) > [x_thresh, y_thresh, z_thresh]).any():
                # potential start of move action identified
                # Check next few windows to confirm start of move action
                for k in range(j+window_size, j+window_size*4, window_size):
                    next_acc_vals = np_imu_data[k:k+window_size, :3]
                    if not (np.abs(next_acc_vals) > [x_thresh, y_thresh, z_thresh]).any():
                        # not the start of move action, move to next window
                        break
                else:
                    # confirmed start of move action
                    np_imu_data = np_imu_data[j:]
                    return np_imu_data.T

        return None



    def AI_actual(self):
        global prediction_array, NUM_INPUT

        # parsed_imu_data = self.detect_start_of_move2(imu_data)

        # parsed_imu_data = self.detect_start_of_move3(imu_data)
        
        # parsed_imu_data = self.detect_start_of_move()
        self.detect_start_of_move()

        # if parsed_imu_data is None:
        #     print("No move detected")
        #     return None
        if self.imu_data is None:
            # print("No move detected")
            return None

        mapping = {0: 'logout', 1: 'shield', 2: 'reload', 3: 'grenade', 4: 'idle'}
        self.extract_features()
        # features = self.extract_features(parsed_imu_data)

        for i in range(NUM_INPUT):
            self.input_buffer[i] = self.features[i]

        run = True

        while run:
            try:
                # aiflag.clear()
                self.dma.sendchannel.transfer(self.input_buffer)
                self.dma.recvchannel.transfer(self.output_buffer)
                self.dma.sendchannel.wait()
                self.dma.recvchannel.wait()

                action = self.output_buffer[0]

                # prediction_array.append(action)
                print('Predicted class:', self.player, action, mapping[action])
                
                run = False
                if not mapping[action] == 'idle':
                    if self.player == 'p1':
                        if evalServerConnected.is_set():
                            action_p1_queue.put(mapping[action])
                    else:
                        if evalServerConnected.is_set():
                            action_p2_queue.put(mapping[action])

                # aiflag.set()
            except RuntimeError as e:
                print(e)
                # print("Error config: ", self.dma.register_map)

# MQTT Client to send data to AWS IOT Core
class MQTT_Client(Process):
    def __init__(self, pub_topic, sub_topic, client_id, group) -> None:
        super().__init__()
        self.pub_topic = pub_topic
        self.sub_topic = sub_topic
        self.client_id = client_id
        self.group = group
        self.client = paho.Client(client_id, protocol=paho.MQTTv311)
        # self.client = paho.Client(client_id)
        self.client.tls_set(tls_version=mqtt.client.ssl.PROTOCOL_TLSv1_2)
        self.client.username_pw_set(MQTT_USERNAME, MQTT_PASSWORD)
        self.client.connect("e56e6e3e03d54e70bf9cc69a2761fe4c.s1.eu.hivemq.cloud", 8883)
        print('MQTT Client started on', self.client_id)
        self.client.subscribe(self.sub_topic)
        self.client.on_message = self.receive
    
    def run(self):
        try:
            self.client.loop_start()
            while True:
                type, data = viz_queue.get()
                # print("[PUBLISH]", data)
                self.publish(type, json.loads(data))
        except Exception as e:
            print(e)
            self.client.loop_stop()        

    def publish(self, type, data):
        try:
            data = str(data)
            message = str(len(data)) + '_' + type + '_' + data
            self.client.publish(self.pub_topic, message)
            print('====================================')
            print('[MQTT] Published message to visualiser at', self.pub_topic, message)
            print('====================================')
        except:
            print("Error: could not publish message")
    def receive(self, client, userdata, message):
        try:
            # msg  = message.payload.decode("utf-8")
            # # msg = message.payload	
            # length = int(msg.split('_')[0])
            # check = msg.split('_')[1]
            # data = msg.split('_')[2]
            # print('====================================')
            # print("\n [MQTT] Received message from", message.topic, message.payload)
            # print('====================================')
            # if check == 'CHECK':
            #     # to update grenade damage for player 2
            #     if data == 'Visible':
            #         print("[MQTT] Player 2 is in grenade range")
            #         action_queue.put('grenade_p2_hits')
            #     else: 
            #         print("[MQTT] Player 2 is not in grenade range")
            #         action_queue.put('grenade_p2_misses')
            # print("[MQTT] " + str(message.payload))
            print("[MQTT] " + message.payload.decode("utf-8"))
            msg = message.payload.decode("utf-8")
            
            if msg == "14_CHECK_grenade_p2_hit":
                # to update grenade damage for player 2
                print("[MQTT] Player 2 is in grenade range")
                # grenadeP1Check.set()
                grenadeP2Hit.set()
                # action_p1_queue.put('grenade_p2_hits') 
                # isPlayerOneGrenadeActivated.clear()
            elif msg == '15_CHECK_grenade_p2_miss':
                print("[MQTT] Player 2 is not in grenade range")     
                grenadeP2Miss.set()
                # grenadeP2Hit.clear()
                # action_p1_queue.put('grenade_p2_misses') 
                # isPlayerOneGrenadeActivated.clear()
                # action_queue.put('grenade_p2_misses')
            elif msg == '14_CHECK_grenade_p1_hit':
                print("[MQTT] Player 1 is in grenade range")
                # grenadeP2Check.set()
                grenadeP1Hit.set()
                # action_p2_queue.put('grenade_p1_hits')
                # isPlayerTwoGrenadeActivated.clear()
            elif msg == '15_CHECK_grenade_p1_miss':
                print("[MQTT] Player 1 is not in grenade range")
                grenadeP1Miss.set()
                # grenadeP1Hit.clear()      
                # action_p2_queue.put('grenade_p1_misses')
                # isPlayerTwoGrenadeActivated.clear() 
            elif msg == '6_CHECK_update':
                pass
                # player_state_copy = deepcopy(player_state)
                # player_state_copy['p1']['action'] = 'none'
                # player_state_copy['p2']['action'] = 'none'
                # viz_queue.put(('STATE', json.dumps(player_state_copy)))
        except Exception as e:
            print('Error: message not in correct format')
            print(message.payload)
            print(e)
        
# Client to send data to the Evaluation Server
class Evaluation_Client(Process):
    
    IV = b'PLSPLSPLSPLSWORK'
    KEY = b'PLSPLSPLSPLSWORK'

    def __init__(self, ip, port, group) -> None:
        super().__init__()
        self.eval_ip = gethostbyname(ip)
        self.eval_port = port
        self.group = group
        
        try:
            self.clientSocket = socket(AF_INET, SOCK_STREAM)
            self.clientSocket.connect((self.eval_ip, self.eval_port))
            evalServerConnected.set()
            print('Connected to Evaluation Server', self.eval_ip, self.eval_port)
        except:
            print('Failed to connect to Evaluation Server', self.eval_ip, self.eval_port)
            self.clientSocket = None
    

    def run(self):
        try:
            while True:
                data = eval_queue.get()
                # print("[EVAL CLIENT]", player_state)
                self.player_state = json.loads(data)
                self.send(data)
                self.receive()
        except Exception as e:
            print('Failed to send message to Evaluation Server', self.eval_ip, self.eval_port)
            print(e)
            self.close()


    # Initialise AES Cipher
    @staticmethod
    def AES_Cipher():
        return AES.new(Evaluation_Client.KEY, AES.MODE_CBC, Evaluation_Client.IV)

    def send(self, message):
        if self.clientSocket is not None:
            try:
                encryted_message = self.encrypt_AES(message)
                len_info = str(len(encryted_message)) + "_"
                # send len_
                self.clientSocket.send(len_info.encode("utf-8"))
                self.clientSocket.send(encryted_message)
                print('=====================================')
                print('[EVAL CLIENT] Sent message to Evaluation Server', self.eval_ip, self.eval_port, message)
                print('=====================================')
            except Exception as e:
                print('[EVAL CLIENT] Failed to send message to Evaluation Server', self.eval_ip, self.eval_port, message)
                print(e)
                self.close()
    
    def receive(self):
        if self.clientSocket is not None:
            # global player_state
            try:
                # recv length followed by '_' followed by cypher
                data = b''
                while not data.endswith(b'_'):
                    _d = self.clientSocket.recv(1)
                    if not _d:
                        data = b''
                        break
                    data += _d
                if len(data) == 0:
                    print('no more data from the client')
                    self.stop()

                data = data.decode("utf-8")
                length = int(data[:-1])

                data = b''
                while len(data) < length:
                    _d = self.clientSocket.recv(length - len(data))
                    if not _d:
                        data = b''
                        break
                    data += _d
                if len(data) == 0:
                    print('no more data from the client')
                    self.stop()
                recv_dict = data.decode("utf8")  # D1ode raw bytes to UTF-8
                # recv_dict = literal_eval(msg)
                recv_dict = json.loads(recv_dict)
                player_state_intcomms['p1']['action'] = recv_dict['p1']['action']
                player_state_intcomms['p2']['action'] = recv_dict['p2']['action']
                player_state_intcomms['p1']['hp'] = recv_dict['p1']['hp']
                player_state_intcomms['p2']['hp'] = recv_dict['p2']['hp']
                player_state_intcomms['p1']['bullets'] = recv_dict['p1']['bullets']
                player_state_intcomms['p2']['bullets'] = recv_dict['p2']['bullets']
                # player_state = recv_dict
                action_p1 = recv_dict['p1']['action']
                action_p2 = recv_dict['p2']['action']
                if action_p1 != "logout" and action_p2 != "logout":
                    recv_dict['p1']['action'] = 'none'
                    recv_dict['p2']['action'] = 'none'
                if action_p1 == "shield" and self.player_state['p1']['action'] != "shield":
                    recv_dict['p1']['action'] = 'shield'
                if action_p2 == "shield" and self.player_state['p2']['action'] != "shield":
                    recv_dict['p2']['action'] = 'shield'
                viz_queue.put(('STATE', json.dumps(recv_dict)))
                # if recv_dict['p1']['action'] != 'shoot' and recv_dict['p2']['action'] != 'shoot' and recv_dict['p1']['action'] != 'grenade' and recv_dict['p2']['action'] != 'grenade':
                # ### TODO CHECK THIS PLACE IN CASE OF ERRORS
                #     viz_queue.put(('STATE', json.dumps(recv_dict)))
                # else:
                #     recv_dict['p1']['action'] = 'none'
                #     recv_dict['p2']['action'] = 'none'
                #     viz_queue.put(('STATE', json.dumps(recv_dict)))
                # ### UPDATE INT COMMS STATE

                intcomms_queue.put(json.dumps(player_state_intcomms))

                print('=====================================')
                print("[EVAL SERVER] Received message from Evaluation Server", recv_dict)
                print('=====================================')

                ### purge action queues
                # try:
                #     while True:
                #         eval_queue.get_nowait()
                # except queues.Empty:
                #     pass
                try:
                    while True:
                        action_p1_queue.get_nowait()
                except queues.Empty:
                    pass
                try:
                    while True:
                        action_p2_queue.get_nowait()
                except queues.Empty:
                    pass
                # sync internal state
                recv_dict['p1']['action'] = action_p1
                recv_dict['p2']['action'] = action_p2
                if action_p1 == "reload":
                    reloadSendRelayP1.set()
                if action_p2 == "reload":
                    reloadSendRelayP2.set()
                recv_queue.put(recv_dict)

            except:
                print('Failed to receive message from Evaluation Server', self.eval_ip, self.eval_port)
                self.close()


    def close(self):
        if self.clientSocket is not None:
            self.clientSocket.close()
            print('Closed connection to Evaluation Server', self.eval_ip, self.eval_port)
    
    def encrypt_AES(self, string):    
        msg = pad(string.encode("utf-8"), AES.block_size)
        encrypted_text = Evaluation_Client.AES_Cipher().encrypt(msg)
        ciphertext = base64.b64encode(self.IV + encrypted_text)
        return ciphertext


def main():
    # eval_client = Evaluation_Client('137.132.92.184', 8888, 2)
    eval_client = Evaluation_Client('localhost', 11001, 2)
    eval_client.start()

    # ai_thread1 = AI_Thread_1()
    ai_thread1 = AI_Process(imu_queue_p1)
    ai_thread1.start()

    # ai_thread2 = AI_Thread_2()
    ai_thread2 = AI_Process(imu_queue_p2)
    ai_thread2.start()

    game_engine = Game_Engine() 
    game_engine.start()

    mqtt = MQTT_Client('cg4002/gamestate', 'cg4002/visualizer', 'ultra96', 2)
    mqtt.start()

    # HOST, PORT = "192.168.95.235", 11000
    HOST, PORT = "localhost", 11000    
    server = Relay_Server(HOST, PORT)
    server.start()
    eval_client.join()
    ai_thread1.join()
    ai_thread2.join()
    game_engine.join()
    mqtt.join()
    server.join()


if __name__ == "__main__":
    main()