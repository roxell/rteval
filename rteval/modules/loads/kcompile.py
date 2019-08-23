#
#   Copyright 2009 - 2013   Clark Williams <williams@redhat.com>
#   Copyright 2012 - 2013   David Sommerseth <davids@redhat.com>
#   Copyright 2014 - 2017   Clark Williams <williams@redhat.com>
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

import sys, os, os.path, glob, subprocess
from signal import SIGTERM
from rteval.modules import rtevalRuntimeError
from rteval.modules.loads import CommandLineLoad
from rteval.Log import Log
from rteval.misc import expand_cpulist,compress_cpulist
from rteval.systopology import SysTopology

kernel_prefix="linux-5.1"

class KBuildJob(object):
    '''Class to manage a build job bound to a particular node'''

    def __init__(self, node, kdir, logger=None, cpulist=None):
        self.kdir = kdir
        self.jobid = None
        self.node = node
        self.logger = logger
        self.builddir = os.path.dirname(kdir)
        self.objdir = "%s/node%d" % (self.builddir, int(node))
        if not os.path.isdir(self.objdir):
            os.mkdir(self.objdir)
        if os.path.exists('/usr/bin/numactl') and not cpulist:
            self.binder = 'numactl --cpunodebind %d' % int(self.node)
        else:
            self.binder = 'taskset -c %s' % compress_cpulist(cpulist)
        if cpulist:
            self.jobs = self.calc_jobs_per_cpu() * len(cpulist)
        else:
            self.jobs = self.calc_jobs_per_cpu() * len(self.node)
        self.log(Log.DEBUG, "node %d: jobs == %d" % (int(node), self.jobs))
        self.runcmd = "%s make O=%s -C %s -j%d bzImage modules" % (self.binder, self.objdir, self.kdir, self.jobs)
        self.cleancmd = "%s make O=%s -C %s clean allmodconfig" % (self.binder, self.objdir, self.kdir)
        self.log(Log.DEBUG, "node%d kcompile command: %s" % (int(node), self.runcmd))

    def __str__(self):
        return self.runcmd

    def log(self, logtype, msg):
        if self.logger:
            self.logger.log(logtype, "[kcompile node%d] %s" % (int(self.node), msg))

    def calc_jobs_per_cpu(self):
        mult = 2
        self.log(Log.DEBUG, "calulating jobs for node %d" % int(self.node))
        # get memory total in gigabytes
        mem = int(self.node.meminfo['MemTotal']) / 1024.0 / 1024.0 / 1024.0
        # ratio of gigabytes to #cores
        ratio = float(mem) / float(len(self.node))
        if ratio < 1.0:
            ratio = 1.0
        if ratio < 1.0 or ratio > 2.0:
            mult = 1
        self.log(Log.DEBUG, "memory/cores ratio on node %d: %f" % (int(self.node), ratio))
        self.log(Log.DEBUG, "returning jobs/core value of: %d" % int(ratio) * mult)
        return int(int(ratio) * int(mult))

    def clean(self, sin=None, sout=None, serr=None):
        self.log(Log.DEBUG, "cleaning objdir %s" % self.objdir)
        subprocess.call(self.cleancmd, shell=True,
                        stdin=sin, stdout=sout, stderr=serr)

    def run(self, sin=None, sout=None, serr=None):
        self.log(Log.INFO, "starting workload on node %d" % int(self.node))
        self.log(Log.DEBUG, "running on node %d: %s" % (int(self.node), self.runcmd))
        self.jobid = subprocess.Popen(self.runcmd, shell=True,
                                      stdin=sin, stdout=sout, stderr=serr)

    def isrunning(self):
        if self.jobid == None:
            return False
        return (self.jobid.poll() == None)

    def stop(self):
        if not self.jobid:
            return True
        return self.jobid.terminate()


class Kcompile(CommandLineLoad):
    def __init__(self, config, logger):
        self.buildjobs = {}
        self.config = config
        self.topology = SysTopology()
        self.cpulist = config.cpulist
        CommandLineLoad.__init__(self, "kcompile", config, logger)
        self.logger = logger

    def _extract_tarball(self):
        if self.source == None:
            raise rtevalRuntimeError(self, " no source tarball specified!")
        self._log(Log.DEBUG, "unpacking kernel tarball")
        tarargs = ['tar', '-C', self.builddir, '-x']
        if self.source.endswith(".bz2"):
            tarargs.append("-j")
        elif self.source.endswith(".gz"):
            tarargs.append("-z")
        tarargs.append("-f")
        tarargs.append(self.source)
        try:
            subprocess.call(tarargs)
        except:
            self._log(Log.DEBUG, "untar'ing kernel self.source failed!")
            sys.exit(-1)

    def _remove_build_dirs(self):
        if not os.path.isdir(self.builddir):
            return
        self._log(Log.DEBUG, "removing kcompile directories in %s" % self.builddir)
        null = os.open("/dev/null", os.O_RDWR)
        cmd=["rm",  "-rf", os.path.join(self.builddir, "kernel*"), os.path.join(self.builddir, "node*")]
        ret = subprocess.call(cmd,stdin=null, stdout=null, stderr=null)
        if ret:
            raise rtevalRuntimeError(self, "error removing builddir (%s) (ret=%d)" % (self.builddir, ret))

    def _WorkloadSetup(self):
        # find our source tarball
        if 'tarball' in self._cfg:
            tarfile = os.path.join(self.srcdir, self._cfg.tarfile)
            if not os.path.exists(tarfile):
                raise rtevalRuntimeError(self, " tarfile %s does not exist!" % tarfile)
            self.source = tarfile
        else:
            tarfiles = glob.glob(os.path.join(self.srcdir, "%s*" % kernel_prefix))
            if len(tarfiles):
                self.source = tarfiles[0]
            else:
                raise rtevalRuntimeError(self, " no kernel tarballs found in %s" % self.srcdir)

        # check for existing directory
        kdir=None
        names=os.listdir(self.builddir)
        for d in names:
            if d.startswith(kernel_prefix):
                kdir=d
                break
        if kdir == None:
            self._extract_tarball()
            names = os.listdir(self.builddir)
            for d in names:
                self._log(Log.DEBUG, "checking %s" % d)
                if d.startswith(kernel_prefix):
                    kdir=d
                    break
        if kdir == None:
            raise rtevalRuntimeError(self, "Can't find kernel directory!")
        self.mydir = os.path.join(self.builddir, kdir)
        self._log(Log.DEBUG, "mydir = %s" % self.mydir)
        self._log(Log.DEBUG, "systopology: %s" % self.topology)
        self.jobs = len(self.topology)
        self.args = []

        # get the cpus for each node
        self.cpus = {}
        self.nodes = self.topology.getnodes()
        for n in self.nodes:
            self.cpus[n] = [ int(c.split('/')[-1][3:]) for c in glob.glob('/sys/devices/system/node/node%s/cpu[0-9]*' % n) ]
            self.cpus[n].sort()

            # if a cpulist was specified, only allow cpus in that list on the node
            if self.cpulist:
                self.cpus[n] = [ c for c in self.cpus[n] if str(c) in expand_cpulist(self.cpulist) ]

        # remove nodes with no cpus available for running
        for node,cpus in self.cpus.items():
            if not cpus:
                self.nodes.remove(node)
                self._log(Log.DEBUG, "node %s has no available cpus, removing" % node)

        for n in self.nodes:
            self._log(Log.DEBUG, "Configuring build job for node %d" % int(n))
            self.buildjobs[n] = KBuildJob(self.topology[n], self.mydir, self.logger, self.cpus[n] if self.cpulist else None)
            self.args.append(str(self.buildjobs[n])+";")


    def _WorkloadBuild(self):
        null = os.open("/dev/null", os.O_RDWR)
        if self._logging:
            out = self.open_logfile("kcompile-build.stdout")
            err = self.open_logfile("kcompile-build.stderr")
        else:
            out = err = null

        # clean up any damage from previous runs
        try:
            cmd = ["make", "-C", self.mydir, "mrproper"]
            ret = subprocess.call(cmd, stdin=null, stdout=out, stderr=err)
            if ret:
                # if the above make failed, remove and reinstall the source tree
                self._log(Log.DEBUG, "Invalid state in kernel build tree, reloading")
                self._remove_build_dirs()
                self._extract_tarball()
                ret = subprocess.call(cmd, stdin=null, stdout=out, stderr=err)
                if ret:
                    # give up
                    raise rtevalRuntimeError(self, "kcompile setup failed: %d" % ret)
        except KeyboardInterrupt as m:
            self._log(Log.DEBUG, "keyboard interrupt, aborting")
            return
        self._log(Log.DEBUG, "ready to run")
        if self._logging:
            os.close(out)
            os.close(err)
        # clean up object dirs and make sure each has a config file
        for n in self.nodes:
            self.buildjobs[n].clean(sin=null,sout=null,serr=null)
        os.close(null)
        self._setReady()

    def _WorkloadPrepare(self):
        self.__nullfd = os.open("/dev/null", os.O_RDWR)
        if self._logging:
            self.__outfd = self.open_logfile("kcompile.stdout")
            self.__errfd = self.open_logfile("kcompile.stderr")
        else:
            self.__outfd = self.__errfd = self.__nullfd

        if 'cpulist' in self._cfg and self._cfg.cpulist:
            cpulist = self._cfg.cpulist
            self.num_cpus = len(expand_cpulist(cpulist))
        else:
            cpulist = ""

    def _WorkloadTask(self):
        for n in self.nodes:
            if not self.buildjobs[n]:
                raise RuntimeError("Build job not set up for node %d" % int(n))
            if self.buildjobs[n].jobid is None or self.buildjobs[n].jobid.poll() is not None:
                # A jobs was started, but now it finished. Check return code.
                # -2 is returned when user forced stop of execution (CTRL-C).
                if self.buildjobs[n].jobid is not None:
                    if self.buildjobs[n].jobid.returncode != 0 and self.buildjobs[n].jobid.returncode != -2:
                        raise RuntimeError("kcompile module failed to run (returned %d), please check logs for more detail"
                                % self.buildjobs[n].jobid.returncode)
                self._log(Log.INFO, "Starting load on node %d" % n)
                self.buildjobs[n].run(self.__nullfd, self.__outfd, self.__errfd)

    def WorkloadAlive(self):
        # if any of the jobs has stopped, return False
        for n in self.nodes:
            if self.buildjobs[n].jobid.poll() is not None:
                # Check return code (see above).
                if self.buildjobs[n].jobid.returncode != 0 and self.buildjobs[n].jobid.returncode != -2:
                    raise RuntimeError("kcompile module failed to run (returned %d), please check logs for more detail"
                            % self.buildjobs[n].jobid.returncode)
                return False

        return True


    def _WorkloadCleanup(self):
        self._log(Log.DEBUG, "out of stopevent loop")
        for n in self.buildjobs:
            if self.buildjobs[n].jobid.poll() == None:
                self._log(Log.DEBUG, "stopping job on node %d" % int(n))
                self.buildjobs[n].jobid.terminate()
                self.buildjobs[n].jobid.wait()
                del self.buildjobs[n].jobid
        os.close(self.__nullfd)
        del self.__nullfd
        if self._logging:
            os.close(self.__outfd)
            del self.__outfd
            os.close(self.__errfd)
            del self.__errfd
        self._setFinished()


def ModuleParameters():
    return {"source":   {"descr": "Source tar ball",
                         "default": "linux-5.1.tar.xz",
                         "metavar": "TARBALL"},
            "jobspercore": {"descr": "Number of working threads per core",
                            "default": 2,
                            "metavar": "NUM"},
            }



def create(config, logger):
    return Kcompile(config, logger)
