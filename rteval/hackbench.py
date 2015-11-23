#
#   hackbench.py - class to manage an instance of hackbench load
#
#   Copyright 2009,2010   Clark Williams <williams@redhat.com>
#   Copyright 2009,2010   David Sommerseth <davids@redhat.com>
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
#   You should have received a copy of the GNU General Public License
#   along with this program; if not, write to the Free Software
#   Foundation, Inc., 59 Temple Place, Suite 330, Boston, MA  02111-1307 USA
#
#   For the avoidance of doubt the "preferred form" of this code is one which
#   is in an open unpatent encumbered format. Where cryptographic key signing
#   forms part of the process of creating an executable the information
#   including keys needed to generate an equivalently functional executable
#   are deemed to be part of the source code.
#

import sys
import os
import time
import glob
import subprocess
import errno
from signal import SIGTERM
from signal import SIGKILL
sys.pathconf = "."
import load

class Hackbench(load.Load):
    def __init__(self, params={}):
        load.Load.__init__(self, "hackbench", params)

    def __del__(self):
        null = open("/dev/null", "w")
        subprocess.call(['killall', '-9', 'hackbench'],
                        stdout=null, stderr=null)
        os.close(null)

    def setup(self):
        # figure out how many nodes we have
        self.nodes = [ n.split('/')[-1][4:] for n in glob.glob('/sys/devices/system/node/node*') ]

        # get the cpus for each node
        self.cpus = {}
        biggest = 0
        for n in self.nodes:
            self.cpus[n] = [ int(c.split('/')[-1][3:]) for c in glob.glob('/sys/devices/system/node/node%s/cpu[0-9]*' % n) ]
            self.cpus[n].sort()
            if len(self.cpus[n]) > biggest:
                biggest = len(self.cpus[n])

        # setup jobs based on the number of cores available per node
        self.jobs = biggest * 3

        # figure out if we can use numactl or have to use taskset
        self.__usenumactl = False
        self.__multinodes = False
        if len(self.nodes) > 1:
            self.__multinodes = True
            print "hackbench: running with multiple nodes (%d)" % len(self.nodes)
            if os.path.exists('/usr/bin/numactl'):
                self.__usenumactl = True
                print "hackbench: using numactl for thread affinity"

        self.args = ['hackbench',  '-P',
                     '-g', str(self.jobs),
                     '-l', str(self.params.setdefault('loops', '1000')),
                     '-s', str(self.params.setdefault('datasize', '1000'))
                     ]
        self.err_sleep = 5.0
        self.tasks = {}

    def build(self):
        self.ready = True

    def __starton(self, node):
        if self.__multinodes:
            if self.__usenumactl:
                args = [ 'numactl', '--cpunodebind', node ] + self.args
            else:
                cpulist = ",".join([ str(n) for n in self.cpus[node] ])
                args = ['taskset', '-c', cpulist ] + self.args
        else:
            args = self.args

        self.debug("hackbench starting: %s" % " ".join(args))

        return subprocess.Popen(args,
                                stdin=self.null,
                                stdout=self.out,
                                stderr=self.err)

    def runload(self):
        # if we don't have any jobs just wait for the stop event and return
        if self.jobs == 0:
            self.stopevent.wait()
            return
        self.null = os.open("/dev/null", os.O_RDWR)
        if self.logging:
            self.out = self.open_logfile("hackbench.stdout")
            self.err = self.open_logfile("hackbench.stderr")
        else:
            self.out = self.err = self.null
        self.debug("starting loop (jobs: %d)" % self.jobs)

        for n in self.nodes:
            self.tasks[n] = self.__starton(n)

        while not self.stopevent.isSet():
            for n in self.nodes:
                try:
                    # if poll() returns an exit status, restart
                    if self.tasks[n].poll() != None:
                        self.tasks[n].wait()
                        self.tasks[n] = self.__starton(n)
                except OSError, e:
                    if e.errno != errno.ENOMEM:
                        raise
                    # Catch out-of-memory errors and wait a bit to (hopefully)
                    # ease memory pressure
                    print "hackbench: %s, sleeping for %f seconds" % (e.strerror, self.err_sleep)
                    time.sleep(self.err_sleep)
                    if self.err_sleep < 60.0:
                        self.err_sleep *= 2.0
                    if self.err_sleep > 60.0:
                        self.err_sleep = 60.0

        self.debug("stopping")
        for n in self.nodes:
            if self.tasks[n].poll() == None:
                os.kill(self.tasks[n].pid, SIGKILL)
            self.tasks[n].wait()

        self.debug("returning from runload()")
        os.close(self.null)
        if self.logging:
            os.close(self.out)
            os.close(self.err)

    def genxml(self, x):
        x.taggedvalue('command_line', self.jobs and ' '.join(self.args) or None,
                      {'name':'hackbench', 'run': self.jobs and '1' or '0'})

def create(params = {}):
    return Hackbench(params)


if __name__ == '__main__':
    h = Hackbench(params={'debugging':True, 'verbose':True})
    h.run()
