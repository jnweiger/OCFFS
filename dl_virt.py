#! /usr/bin/env python3
#
# 
# cmd="DOWNLOAD_VIRTUAL_FILE:/home/testy/testpilotcloud2/ownCloud Manual.pdf.testpilotcloud_virtual"
# echo "$cmd" | socat - UNIX-CONNECT:/run/user/1000/testpilotcloud/socket

import os, socket, sys

path = sys.argv[1]
# /home/testy/testpilotcloud2/ownCloud Manual.pdf.testpilotcloud_virtual"

self_client_uid = 1000
self_client_executable_shortname = "testpilotcloud"
sock_file = '/run/user/'+str(self_client_uid)+'/'+self_client_executable_shortname+'/socket'
sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
cmd = "DOWNLOAD_VIRTUAL_FILE:"+os.path.realpath(path)+"\n"
try:
  sock.connect(sock_file)
  sock.send(cmd.encode('utf-8'))
except Exception as e:
  print("_convert_v2p: send failed: " + str(e), file=sys.stderr)
sock.settimeout(0.2)
seen = sock.recv(1024)
seen = seen[:seen.rfind(b'\n')].decode('utf-8').split('\n')
print("_convert_v2p: received: " + str(seen), file=sys.stderr)
sock.close()

