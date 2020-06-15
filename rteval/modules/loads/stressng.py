""" Module containing class Stressng to manage stress-ng as an rteval load """
import os
import os.path
import time
import subprocess
import signal
from rteval.modules.loads import CommandLineLoad
from rteval.Log import Log
from rteval.misc import expand_cpulist
from rteval.systopology import SysTopology

class Stressng(CommandLineLoad):
    " This class creates a load module that runs stress-ng "
    def __init__(self, config, logger):
        CommandLineLoad.__init__(self, "stressng", config, logger)
        self.logger = logger
        self.started = False
        self.process = None
        self.cfg = config
        self.__in = None
        self.__out = None
        self.__err = None
        self.__nullfp = None
        self.cmd = None
        " Only run this module if the user specifies an option "
        if self.cfg.option is not None:
            self._donotrun = False
        else:
            self._donotrun = True

    def _WorkloadSetup(self):
        " Since there is nothing to build, we don't need to do anything here "
        return

    def _WorkloadBuild(self):
        " Nothing to build, so we are ready "
        self._setReady()

    def _WorkloadPrepare(self):
        " Set-up logging "
        self.__nullfp = os.open("/dev/null", os.O_RDWR)
        self.__in = self.__nullfp
        if self._logging:
            self.__out = self.open_logfile("stressng.stdout")
            self.__err = self.open_logfile("stressng.stderr")
        else:
            self.__out = self.__err = self.__nullfp

        # stress-ng is only run if the user specifies an option
        self.cmd = ['stress-ng']
        self.cmd.append('--%s' % str(self.cfg.option))
        if self.cfg.arg is not None:
            self.cmd.append(self.cfg.arg)
        if self.cfg.timeout is not None:
            self.cmd.append('--timeout %s' % str(self.cfg.timeout))

        systop = SysTopology()
        # get the number of nodes
        nodes = systop.getnodes()

        # get the cpus for each node
        cpus = {}
        for n in nodes:
            cpus[n] = systop.getcpus(int(n))
            # if a cpulist was specified, only allow cpus in that list on the node
            if self.cpulist:
                cpus[n] = [c for c in cpus[n] if str(c) in expand_cpulist(self.cpulist)]

        # remove nodes with no cpus available for running
        for node, cpu in list(cpus.items()):
            if not cpu:
                nodes.remove(node)
                self._log(Log.DEBUG, "node %s has no available cpus, removing" % node)
        if self.cpulist:
            for node in nodes:
                cpulist = ",".join([str(n) for n in cpus[node]])
                self.cmd.append('--taskset %s' % cpulist)

    def _WorkloadTask(self):
        """ Kick of the workload here """
        if self.started:
            # Only start the task once
            return

        self._log(Log.DEBUG, "starting with %s" % " ".join(self.cmd))
        try:
            self.process = subprocess.Popen(self.cmd,
                                            stdout=self.__out,
                                            stderr=self.__err,
                                            stdin=self.__in)
            self.started = True
            self._log(Log.DEBUG, "running")
        except OSError:
            self._log(Log.DEBUG, "Failed to run")
            self.started = False
        return

    def WorkloadAlive(self):
        " Return true if stress-ng workload is alive "
        if self.started:
            return self.process.poll() is None
        return False

    def _WorkloadCleanup(self):
        " Makesure to kill stress-ng before rteval ends "
        if not self.started:
            return
        # poll() returns None if the process is still running
        while self.process.poll() is None:
            self._log(Log.DEBUG, "Sending SIGINT")
            self.process.send_signal(signal.SIGINT)
            time.sleep(2)
        return


def create(config, logger):
    """ Create an instance of the Stressng class in stressng module """
    return Stressng(config, logger)

def ModuleParameters():
    """ Commandline options for Stress-ng """
    return {
        "option": {
            "descr": "stressor specific option",
            "metavar": "OPTION"
        },
        "arg": {
            "descr": "stressor specific arg",
            "metavar" : "ARG"
        },
        "timeout": {
            "descr": "timeout after T seconds",
            "metavar" : "T"
        },
        }
