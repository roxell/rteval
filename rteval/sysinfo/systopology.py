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

import os, sys
import os.path
import glob

def _sysread(path, obj):
    fp = open(os.path.join(path,obj), "r")
    return fp.readline().strip()

#
# class to provide access to a list of cpus
#

class CpuList(object):
    "Object that represents a group of system cpus"

    cpupath = '/sys/devices/system/cpu'

    def __init__(self, cpulist):
        if type(cpulist) is list:
            self.cpulist = cpulist
        elif type(cpulist) is str:
            self.cpulist = self.__expand_cpulist(cpulist)
        self.cpulist.sort()

    def __str__(self):
        return self.__collapse_cpulist(self.cpulist)

    def __contains__(self, cpu):
        return cpu in self.cpulist

    def __len__(self):
        return len(self.cpulist)


    # return the index of the last element of a sequence
    # that steps by one
    def __longest_sequence(self, cpulist):
        lim = len(cpulist)
        for idx,val in enumerate(cpulist):
            if idx+1 == lim:
                break
            if int(cpulist[idx+1]) != (int(cpulist[idx])+1):
                return idx
        return lim - 1


    #
    # collapse a list of cpu numbers into a string range
    # of cpus (e.g. 0-5, 7, 9)
    #
    def __collapse_cpulist(self, cpulist):
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

    # expand a string range into a list
    # don't error check against online cpus
    def __expand_cpulist(self, cpulist):
        '''expand a range string into an array of cpu numbers'''
        result = []
        for part in cpulist.split(','):
            if '-' in part:
                a, b = part.split('-')
                a, b = int(a), int(b)
                result.extend(range(a, b + 1))
            else:
                a = int(part)
                result.append(a)
        return [ int(i) for i in list(set(result)) ]

    # returns the list of cpus tracked
    def getcpulist(self):
        return self.cpulist

    # check whether cpu n is online
    def isonline(self, n):
        if n not in self.cpulist:
            raise RuntimeError, "invalid cpu number %d" % n
        if n == 0:
            return True
        path = os.path.join(CpuList.cpupath,'cpu%d' % n)
        if os.path.exists(path):
            return _sysread(path, "online") == 1
        return False

#
# class to abstract access to NUMA nodes in /sys filesystem
#

class NumaNode(object):
    "class representing a system NUMA node"

    # constructor argument is the full path to the /sys node file
    # e.g. /sys/devices/system/node/node0
    def __init__(self, path):
        self.path = path
        self.nodeid = int(os.path.basename(path)[4:].strip())
        self.cpus = CpuList(_sysread(self.path, "cpulist"))
        self.getmeminfo()

    # function for the 'in' operator
    def __contains__(self, cpu):
        return cpu in self.cpus

    # allow the 'len' builtin
    def __len__(self):
        return len(self.cpus)

    # string representation of the cpus for this node
    def __str__(self):
        return self.getcpustr()

    # read info about memory attached to this node
    def getmeminfo(self):
        self.meminfo = {}
        for l in open(os.path.join(self.path, "meminfo"), "r"):
            elements = l.split()
            key=elements[2][0:-1]
            val=int(elements[3])
            if len(elements) == 5 and elements[4] == "kB":
                val *= 1024
            self.meminfo[key] = val

    # return list of cpus for this node as a string
    def getcpustr(self):
        return str(self.cpus)

    # return list of cpus for this node
    def getcpulist(self):
        return self.cpus.getcpulist()

#
# Class to abstract the system topology of numa nodes and cpus
#
class SysTopology(object):
    "Object that represents the system's NUMA-node/cpu topology"

    cpupath = '/sys/devices/system/cpu'
    nodepath = '/sys/devices/system/node'

    def __init__(self):
        self.nodes = {}
        self.getinfo()

    def __len__(self):
        return len(self.nodes.keys())

    def __str__(self):
        s = "%d node system" % len(self.nodes.keys())
        s += " (%d cores per node)" % (len(self.nodes[self.nodes.keys()[0]]))
        return s

    # inplement the 'in' function
    def __contains__(self, node):
        for n in self.nodes:
            if self.nodes[n].nodeid == node:
                return True
        return False

    # allow indexing for the nodes
    def __getitem__(self, key):
        return self.nodes[key]

    # allow iteration over the cpus for the node
    def __iter__(self):
        self.current = 0
        return self

    # iterator function
    def next(self):
        if self.current >= len(self.nodes):
            raise StopIteration
        n = self.nodes[self.current]
        self.current += 1
        return n

    def getinfo(self):
        nodes = glob.glob(os.path.join(SysTopology.nodepath, 'node[0-9]*'))
        if not nodes:
            raise RuntimeError, "No valid nodes found in %s!" % SysTopology.nodepath
        nodes.sort()
        for n in nodes:
            node = int(os.path.basename(n)[4:])
            self.nodes[node] = NumaNode(n)

    def getnodes(self):
        return self.nodes.keys()

    def getcpus(self, node):
        return self.nodes[node]



if __name__ == "__main__":

    def unit_test():
        s = SysTopology()
        print s
        print "number of nodes: %d" % len(s)
        for n in s:
            print "node[%d]: %s" % (n.nodeid, n)
        print "system has numa node 0: %s" % (0 in s)
        print "system has numa node 2: %s" % (2 in s)
        print "system has numa node 24: %s" % (24 in s)

    unit_test()
