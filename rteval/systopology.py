# -*- coding: utf-8 -*-
#
#   Copyright 2016 - Clark Williams <williams@redhat.com>
#
#   This program is free software; you can redistribute it and/or modify
#   it under the terms of the GNU General Public License as published by
#   the Free Software Foundation; either version 2 of the License, or
#   (at your option) any later version.
#
#   This program is distributed in the hope that it will be useful,
#   but WITHOUT ANY WARRANTY; without even the implied warranty of
#   MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#   GNU General Public License for more details.
#
#   You should have received a copy of the GNU General Public License along
#   with this program; if not, write to the Free Software Foundation, Inc.,
#   51 Franklin Street, Fifth Floor, Boston, MA 02110-1301 USA.
#
#   For the avoidance of doubt the "preferred form" of this code is one which
#   is in an open unpatent encumbered format. Where cryptographic key signing
#   forms part of the process of creating an executable the information
#   including keys needed to generate an equivalently functional executable
#   are deemed to be part of the source code.
#

import os
import os.path
import glob

def sysread(path, obj):
    """ Helper function for reading system files """
    fp = open(os.path.join(path, obj), "r")
    return fp.readline().strip()

#
# class to provide access to a list of cpus
#

class CpuList:
    "Object that represents a group of system cpus"

    cpupath = '/sys/devices/system/cpu'

    def __init__(self, cpulist):
        if isinstance(cpulist, list):
            self.cpulist = cpulist
        elif isinstance(cpulist, str):
            self.cpulist = self.__expand_cpulist(cpulist)
        self.cpulist = self.online_cpulist(self.cpulist)
        self.cpulist.sort()

    def __str__(self):
        return self.__collapse_cpulist(self.cpulist)

    def __contains__(self, cpu):
        return cpu in self.cpulist

    def __len__(self):
        return len(self.cpulist)

    @staticmethod
    def online_file_exists():
        """ Check whether machine / kernel is configured with online file """
        if os.path.exists('/sys/devices/system/cpu/cpu1/online'):
            return True
        return False

    @staticmethod
    def __longest_sequence(cpulist):
        """ return index of last element of a sequence that steps by one """
        lim = len(cpulist)
        for idx, _ in enumerate(cpulist):
            if idx+1 == lim:
                break
            if int(cpulist[idx+1]) != (int(cpulist[idx])+1):
                return idx
        return lim - 1

    def __collapse_cpulist(self, cpulist):
        """ Collapse a list of cpu numbers into a string range
        of cpus (e.g. 0-5, 7, 9)
        """
        if len(cpulist) == 0:
            return ""
        idx = self.__longest_sequence(cpulist)
        if idx == 0:
            seq = str(cpulist[0])
        else:
            if idx == 1:
                seq = "%d,%d" % (cpulist[0], cpulist[idx])
            else:
                seq = "%d-%d" % (cpulist[0], cpulist[idx])

        rest = self.__collapse_cpulist(cpulist[idx+1:])
        if rest == "":
            return seq
        return ",".join((seq, rest))

    @staticmethod
    def __expand_cpulist(cpulist):
        """ expand a range string into an array of cpu numbers
        don't error check against online cpus
        """
        result = []
        for part in cpulist.split(','):
            if '-' in part:
                a, b = part.split('-')
                a, b = int(a), int(b)
                result.extend(list(range(a, b + 1)))
            else:
                a = int(part)
                result.append(a)
        return [int(i) for i in list(set(result))]

    def getcpulist(self):
        """ return the list of cpus tracked """
        return self.cpulist

    def is_online(self, n):
        """ check whether cpu n is online """
        if n not in self.cpulist:
            raise RuntimeError("invalid cpu number %d" % n)
        path = os.path.join(CpuList.cpupath, 'cpu%d' % n)

        # Some hardware doesn't allow cpu0 to be turned off
        if not os.path.exists(path + '/online') and n == 0:
            return True

        return sysread(path, "online") == "1"

    def online_cpulist(self, cpulist):
        """ Given a cpulist, return a cpulist of online cpus """
        # This only works if the sys online files exist
        if not self.online_file_exists():
            return cpulist
        newlist = []
        for cpu in cpulist:
            if not self.online_file_exists() and cpu == '0':
                newlist.append(cpu)
            elif self.is_online(int(cpu)):
                newlist.append(cpu)
        return newlist

#
# class to abstract access to NUMA nodes in /sys filesystem
#

class NumaNode:
    "class representing a system NUMA node"

    def __init__(self, path):
        """ constructor argument is the full path to the /sys node file
        e.g. /sys/devices/system/node/node0
        """
        self.path = path
        self.nodeid = int(os.path.basename(path)[4:].strip())
        self.cpus = CpuList(sysread(self.path, "cpulist"))
        self.getmeminfo()

    def __contains__(self, cpu):
        """ function for the 'in' operator """
        return cpu in self.cpus

    def __len__(self):
        """ allow the 'len' builtin """
        return len(self.cpus)

    def __str__(self):
        """ string representation of the cpus for this node """
        return self.getcpustr()

    def __int__(self):
        return self.nodeid

    def getmeminfo(self):
        """ read info about memory attached to this node """
        self.meminfo = {}
        for l in open(os.path.join(self.path, "meminfo"), "r"):
            elements = l.split()
            key = elements[2][0:-1]
            val = int(elements[3])
            if len(elements) == 5 and elements[4] == "kB":
                val *= 1024
            self.meminfo[key] = val

    def getcpustr(self):
        """ return list of cpus for this node as a string """
        return str(self.cpus)

    def getcpulist(self):
        """ return list of cpus for this node """
        return self.cpus.getcpulist()

#
# Class to abstract the system topology of numa nodes and cpus
#
class SysTopology:
    "Object that represents the system's NUMA-node/cpu topology"

    cpupath = '/sys/devices/system/cpu'
    nodepath = '/sys/devices/system/node'

    def __init__(self):
        self.nodes = {}
        self.getinfo()
        self.current = 0

    def __len__(self):
        return len(list(self.nodes.keys()))

    def __str__(self):
        s = "%d node system" % len(list(self.nodes.keys()))
        s += " (%d cores per node)" % (len(self.nodes[list(self.nodes.keys())[0]]))
        return s

    def __contains__(self, node):
        """ inplement the 'in' function """
        for n in self.nodes:
            if self.nodes[n].nodeid == node:
                return True
        return False

    def __getitem__(self, key):
        """ allow indexing for the nodes """
        return self.nodes[key]

    def __iter__(self):
        """ allow iteration over the cpus for the node """
        return self

    def __next__(self):
        """ iterator function """
        if self.current >= len(self.nodes):
            raise StopIteration
        n = self.nodes[self.current]
        self.current += 1
        return n

    def getinfo(self):
        nodes = glob.glob(os.path.join(SysTopology.nodepath, 'node[0-9]*'))
        if not nodes:
            raise RuntimeError("No valid nodes found in %s!" % SysTopology.nodepath)
        nodes.sort()
        for n in nodes:
            node = int(os.path.basename(n)[4:])
            self.nodes[node] = NumaNode(n)

    def getnodes(self):
        return list(self.nodes.keys())

    def getcpus(self, node):
        return self.nodes[node].getcpulist()


if __name__ == "__main__":

    def unit_test():
        s = SysTopology()
        print(s)
        print("number of nodes: %d" % len(s))
        for n in s:
            print("node[%d]: %s" % (n.nodeid, n))
        print("system has numa node 0: %s" % (0 in s))
        print("system has numa node 2: %s" % (2 in s))
        print("system has numa node 24: %s" % (24 in s))

        cpus = {}
        for node in s.getnodes():
            cpus[node] = s.getcpus(int(node))
        print(f'cpus = {cpus}')

    unit_test()
