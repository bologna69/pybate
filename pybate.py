#!/usr/bin/env python3
#     Copyright (C) 2017 pybate
#
#     This program is free software: you can redistribute it and/or modify
#     it under the terms of the GNU General Public License as published by
#     the Free Software Foundation, either version 3 of the License, or
#     (at your option) any later version.
#
#     This program is distributed in the hope that it will be useful,
#     but WITHOUT ANY WARRANTY; without even the implied warranty of
#     MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#     GNU General Public License for more details.
#
#     You should have received a copy of the GNU General Public License
#     along with this program. If not, see <http://www.gnu.org/licenses/>.
########################################################################################################################
#################################################### Configuration #####################################################
########################################################################################################################

# Service username/password (only needed if CONFIG_LISTING is set to/contains 'followed'; set to None otherwise).
CONFIG_USERNAME = None
CONFIG_PASSWORD = None

# Service model stream listing (can be a list, ex: ['female', 'trans']. See LIST_TYPES for possible values).
CONFIG_LISTING = 'followed'

# Custom filter function to be applied when attempting to record a stream (setting to None will disable this feature).
# Example 1: Only record HD cams
CONFIG_FILTER = lambda m: m.hd()
# Example 2: Only record models with name in whitelist.
# WHITELIST = ['favorite_gurlxxx', 'cherrybunny']
# CONFIG_FILTER = lambda m: m in WHITELIST

# Stream recoding application
CONFIG_STREAMER = 'streamlink'
# CONFIG_STREAMER = 'C:\\Program Files\\Python36\\Scripts\\streamlink'

# Stream re-muxer application
CONFIG_REMUXER = 'ffmpeg'

# User-agent to be used when connecting to Service.
CONFIG_USERAGENT = 'pybate'

########################################################################################################################
########################################################################################################################
########################################################################################################################

from bs4 import BeautifulSoup
import requests
import urllib3

import base64
import copy
import os
import random
import ssl
import subprocess
import sys
import time
import traceback

ENCODED_STR = base64.b64decode('Y2hhdHVyYmF0ZQ==').decode("utf-8")
BASE_URL = 'https://' + ENCODED_STR + '.com/'
USER_AGENT = CONFIG_USERAGENT
LOGIN_URL = BASE_URL + 'auth/login/'
LIST_URL = BASE_URL + '%s-cams/?page=%d'
LIST_TYPES = ['followed', 'female', 'couple', 'trans', 'male']
CONNECT_TIMEOUT_SEC = 6
READ_TIMEOUT_SEC = 30
LIST_URL_WAIT_MS = 200.0
MODEL_LIST_REFRESH_RATE_SEC = 120
ERROR_SLEEP_SEC = 300
SESSION_EXPIRE_TIME_SEC = 43200
MAX_ERRORS = 3
LIVESTREAMER = CONFIG_STREAMER
REMUXER = CONFIG_REMUXER

class ClientAdapter(requests.adapters.HTTPAdapter):
    def init_poolmanager(self, connections, maxsize, block=False, **pool_kwargs):
        self.poolmanager = urllib3.poolmanager.PoolManager(num_pools=connections, maxsize=maxsize, block=block, ssl_version=ssl.PROTOCOL_TLSv1_2)


class Client:
    def __init__(self, username=None, password=None, login_url=LOGIN_URL, list_url=LIST_URL, user_agent=USER_AGENT, connect_timeout=CONNECT_TIMEOUT_SEC, read_timeout=READ_TIMEOUT_SEC):
        self.__login_url = login_url
        self.__list_url = list_url
        self.__username = username
        self.__password = password
        self.__token = None
        self.__user_agent = user_agent
        self.__session = requests.session()
        self.__session.mount('https://', ClientAdapter())
        self.__timeout = (connect_timeout, read_timeout)

    def login(self):
        if self.__username is None or self.__password is None:
            raise Exception('Could not login: Invalid username/password')
        r = self.__session.get(self.__login_url, timeout=self.__timeout)
        if r.status_code is not requests.codes.ok:
            raise Exception('Could not retrieve csrf token: HTTP status %d' % (r.status_code))
        self.__token = r.cookies['csrftoken']
        login_data = dict(username=self.__username, password=self.__password, csrfmiddlewaretoken=self.__token, next='/')
        r = self.__session.post(self.__login_url, data=login_data, headers=dict(Referer=self.__login_url), timeout=self.__timeout)
        if r.status_code is not requests.codes.ok:
            raise Exception('Could not login: HTTP status %d' % (r.status_code))
        if r.url == self.__login_url:
            raise Exception('Could not login: Invalid username/password')

    def models(self, types=LIST_TYPES, filter=None):
        def get_list(type):
            online = []
            current_page = 1
            last_page = 99
            while current_page <= last_page:
                url = self.__list_url % (type, current_page)
                r = self.__session.get(url, timeout=self.__timeout)
                if r.status_code is not requests.codes.ok:
                    raise Exception('Could not retrieve model list (%s): HTTP status %d' % (type, r.status_code))
                if r.url == self.__login_url:
                    raise Exception('Session lost!')

                soup = BeautifulSoup(r.text, 'html.parser')
                if last_page == 99:
                    try:
                        last_page = int(soup.findAll('a', {'class': 'endless_page_link'})[-2].string)
                    except IndexError:
                        last_page = 1
                try:
                    parsed_page = int(soup.findAll('li', {'class': 'active'})[1].string)
                except IndexError:
                    parsed_page = 1

                if parsed_page == current_page:
                    li_list = soup.findAll('li', class_="cams")
                    for n in li_list:
                        if n.text != "offline":
                            span_age_list = n.parent.parent.find('span', class_="age")
                            div_thumbnail_label = n.parent.parent.parent.find('div', class_="thumbnail_label")
                            if n.parent.parent.parent.div.text == "IN PRIVATE":
                                continue
                            genders = {
                                'genderf': 'female',
                                'genderm': 'male',
                                'genderc': 'couple',
                                'genders': 'trans'
                            }
                            name = n.parent.parent.a.text[1:]
                            gender = ''
                            age = 0
                            hd = False
                            if len(span_age_list) and len(span_age_list.attrs['class']) > 1:
                                gender = genders.get(span_age_list.attrs['class'][1], 'unknown')
                                age = int(span_age_list.text)
                            if div_thumbnail_label is not None:
                                hd = div_thumbnail_label.text == 'HD'
                            model = Model(name=name, gender=gender, age=age, hd=hd)
                            if filter is not None:
                                if filter(model):
                                    online.append(model)
                            else:
                                online.append(model)
                current_page += 1
                time.sleep((LIST_URL_WAIT_MS + random.randrange(int(LIST_URL_WAIT_MS / 10))) / 1000.0)
            return online

        if isinstance(types, list):
            models = []
            for type in types:
                models += get_list(type)
            return models
        else:
            return get_list(types)


class Model:
    def __init__(self, name, gender, age, hd, hls_threads=2, hls_live_edge=16, hls_segment_attempts=6, ringbuffer_size='32M'):
        self.__name = name
        self.__gender = gender
        self.__age = age
        self.__hd = hd
        self.__downloader_process = None
        self.__remuxer_process = None
        self.__hls_threads = hls_threads
        self.__hls_live_edge = hls_live_edge
        self.__hls_segment_attempts = hls_segment_attempts
        self.__ringbuffer_size = ringbuffer_size
        self.__filename = None
        self.__filename_remux = None

    def __str__(self):
        return '%s (gender: %s, age: %d, HD: %s)' % (self.__name, self.__gender, self.__age, self.__hd)

    def __repr__(self):
        return self.__name

    def __eq__(self, other):
        return self.__name == other.__name

    def name(self):
        return self.__name

    def gender(self):
        return self.__gender

    def age(self):
        return self.__age

    def hd(self):
        return self.__hd

    def url(self):
        return BASE_URL + self.__name

    def remove_original(self):
        try:
            os.remove(self.__filename)
        except:
            pass

    def open_downloader_process(self):
        timestamp = time.strftime("%Y.%m.%d-%H.%M.%S")
        self.__filename = '%s_-_%s.ts' % (self.name(), timestamp)
        self.__downloader_process = subprocess.Popen([LIVESTREAMER,
                                                      '-Q',
                                                      '--hls-segment-threads', str(self.__hls_threads),
                                                      '--hls-live-edge', str(self.__hls_live_edge),
                                                      '--hls-segment-attempts', str(self.__hls_segment_attempts),
                                                      '--ringbuffer-size', self.__ringbuffer_size,
                                                      '-o', self.__filename,
                                                      self.url(),
                                                      'best'
                                                      ], stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT, shell=False)

    def open_remuxer_process(self):
        self.__filename_remux = self.__filename[:-2] + 'mp4'
        self.__remuxer_process = subprocess.Popen([REMUXER,
                                                   '-i', self.__filename,
                                                   '-acodec', 'copy',
                                                   '-vcodec', 'copy',
                                                   '-bsf:a', 'aac_adtstoasc',
                                                   self.__filename_remux
                                                   ], stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT, shell=False)

    def check_downloader_process(self):
        if self.__downloader_process is not None:
            return self.__downloader_process.poll() is not None
        return False

    def check_remuxer_process(self):
        if self.__remuxer_process is not None:
            return self.__remuxer_process.poll() is not None
        return False

    def close_downloader_process(self):
        if self.__downloader_process is not None:
            self.__downloader_process.terminate()
            time.sleep(2)
            if self.check_downloader_process():
                self.__downloader_process.kill()
            self.__downloader_process = None

    def close_remuxer_process(self):
        if self.__remuxer_process is not None:
            self.__remuxer_process.terminate()
            time.sleep(2)
            if self.check_remuxer_process():
                self.__remuxer_process.kill()
            self.__remuxer_process = None


def log(s):
    timestamp = time.strftime("%Y.%m.%d %H:%M:%S")
    print('[%s] %s' % (timestamp, s))


def login():
    log('Logging in...')
    client = Client(CONFIG_USERNAME, CONFIG_PASSWORD)
    client.login()
    return client, int(time.time())


def record_loop(client, recording, remuxing):
    for model in client.models(CONFIG_LISTING):
        if model.name() not in recording:
            log('Starting recording for \'%s\'' % (model.name()))
            recording[model.name()] = model
            recording[model.name()].open_downloader_process()
    for rec_model_name in list(recording.keys()):
        if recording[rec_model_name].check_downloader_process():
            log('Stopping recording for \'%s\'' % (recording[rec_model_name].name()))
            recording[recording[rec_model_name].name()].close_downloader_process()
            log('Starting re-muxing for \'%s\'' % (recording[rec_model_name].name()))
            remuxing[rec_model_name] = copy.deepcopy(recording[rec_model_name])
            remuxing[rec_model_name].open_remuxer_process()
            del recording[rec_model_name]
    for rec_model_name in list(remuxing.keys()):
        if remuxing[rec_model_name].check_remuxer_process():
            log('Stopping re-muxing for \'%s\'' % (remuxing[rec_model_name].name()))
            remuxing[rec_model_name].close_remuxer_process()
            remuxing[rec_model_name].remove_original()
            del remuxing[rec_model_name]
    log('Currently recording: %s' % (list(recording.keys())))
    log('Currently re-muxing: %s' % (list(remuxing.keys())))
    return recording, remuxing


def main():
    recording = {}
    remuxing = {}
    errors = 0
    client = None
    login_time = 0
    while errors <= MAX_ERRORS:
        try:
            current_time = int(time.time())
            if client is None or (current_time - login_time) > SESSION_EXPIRE_TIME_SEC:
                client, login_time = login()
            recording, remuxing = record_loop(client, recording, remuxing)
            errors = 0
            time.sleep(MODEL_LIST_REFRESH_RATE_SEC + random.randrange(int(MODEL_LIST_REFRESH_RATE_SEC / 10)))
        except Exception as e:
            log(e)
            log(traceback.format_exc())
            errors += 1
            time.sleep(ERROR_SLEEP_SEC + random.randrange(int(ERROR_SLEEP_SEC / 10)))
    return 0


if __name__ == '__main__':
    sys.exit(main())
