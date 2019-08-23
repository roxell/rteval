#!/usr/bin/python3 -tt
#
# Copyright (C) 2015 Clark Williams <clark.williams@gmail.com>
# Copyright (C) 2015 Red Hat, Inc.
#
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; version 2 of the License.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program; if not, write to the Free Software
# Foundation, Inc., 675 Mass Ave, Cambridge, MA 02139, USA.


import os
import glob

# expand a string range into a list
# don't error check against online cpus
def expand_cpulist(cpulist):
    '''expand a range string into an array of cpu numbers'''
    result = []
    for part in cpulist.split(','):
        if '-' in part:
            a, b = part.split('-')
            a, b = int(a), int(b)
            result.extend(list(range(a, b + 1)))
        else:
            a = int(part)
            result.append(a)
    return [ str(i) for i in list(set(result)) ]

def online_cpus():
    return [ str(c.replace('/sys/devices/system/cpu/cpu', ''))  for c in glob.glob('/sys/devices/system/cpu/cpu[0-9]*') ]

def invert_cpulist(cpulist):
    return [ c for c in online_cpus() if c not in cpulist]

def compress_cpulist(cpulist):
    if type(cpulist[0]) == int:
        return ",".join(str(e) for e in cpulist)
    else:
        return ",".join(cpulist)

def cpuinfo():
    core = -1
    info = {}
    for l in open('/proc/cpuinfo'):
        l = l.strip()
        if not l: continue
        key,val = [ i.strip() for i in l.split(':')]
        if key == 'processor':
            core = val
            info[core] = {}
            continue
        info[core][key] = val
    return info

if __name__ == "__main__":

    info = cpuinfo()
    idx = list(info.keys())
    idx.sort()
    for i in idx:
        print("%s: %s" % (i, info[i]))

    print("0: %s" % (info['0']['model name']))
