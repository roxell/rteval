#
#   Copyright 2009 - 2013   Clark Williams <williams@redhat.com>
#   Copyright 2009 - 2013   David Sommerseth <davids@redhat.com>
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

"""
Copyright (c) 2008-2016  Red Hat Inc.

Realtime verification utility
"""
__author__ = "Clark Williams <williams@redhat.com>, David Sommerseth <davids@redhat.com>"
__license__ = "GPLv2 License"

import os
import signal
import sys
import threading
import time
from datetime import datetime
from distutils import sysconfig
from rteval.modules.loads import LoadModules
from rteval.modules.measurement import MeasurementModules, MeasurementProfile
from rteval.rtevalReport import rtevalReport
from rteval.rtevalXMLRPC import rtevalXMLRPC
from rteval.Log import Log
from rteval import rtevalConfig
from rteval import rtevalMailer
from rteval import version

RTEVAL_VERSION = version.RTEVAL_VERSION

earlystop = False

stopsig_received = False
def sig_handler(signum, frame):
    """ Handle SIGINT (CTRL + C) or SIGTERM (Termination signal) """
    if signum in (signal.SIGINT, signal.SIGTERM):
        global stopsig_received
        stopsig_received = True
        print("*** stop signal received - stopping rteval run ***")
    else:
        raise RuntimeError("SIGNAL received! (%d)" % signum)

class RtEval(rtevalReport):
    def __init__(self, config, loadmods, measuremods, logger):
        self.__version = RTEVAL_VERSION

        if not isinstance(config, rtevalConfig.rtevalConfig):
            raise TypeError("config variable is not an rtevalConfig object")

        if not isinstance(loadmods, LoadModules):
            raise TypeError("loadmods variable is not a LoadModules object")

        if not isinstance(measuremods, MeasurementModules):
            raise TypeError("measuremods variable is not a MeasurementModules object")

        if not isinstance(logger, Log):
            raise TypeError("logger variable is not an Log object")

        self.__cfg = config
        self.__logger = logger
        self._loadmods = loadmods
        self._measuremods = measuremods

        self.__rtevcfg = self.__cfg.GetSection('rteval')
        self.__reportdir = None

        # Import SystemInfo here, to avoid DMI warnings if RtEval() is not used
        from .sysinfo import SystemInfo
        self._sysinfo = SystemInfo(self.__rtevcfg, logger=self.__logger)

        # prepare a mailer, if that's configured
        if self.__cfg.HasSection('smtp'):
            self.__mailer = rtevalMailer.rtevalMailer(self.__cfg.GetSection('smtp'))
        else:
            self.__mailer = None

        if not os.path.exists(self.__rtevcfg.xslt_report):
            raise RuntimeError("can't find XSL template (%s)!" % self.__rtevcfg.xslt_report)

        # Add rteval directory into module search path
        sys.path.insert(0, '%s/rteval' % sysconfig.get_python_lib())

        # Initialise the report module
        rtevalReport.__init__(self, self.__version,
                              self.__rtevcfg.installdir, self.__rtevcfg.annotate)

        # If --xmlrpc-submit is given, check that we can access the server
        if self.__rtevcfg.xmlrpc:
            self.__xmlrpc = rtevalXMLRPC(self.__rtevcfg.xmlrpc, self.__logger, self.__mailer)
            if not self.__xmlrpc.Ping():
                if not self.__rtevcfg.xmlrpc_noabort:
                    print("ERROR: Could not reach XML-RPC server '%s'.  Aborting." % \
                        self.__rtevcfg.xmlrpc)
                    sys.exit(2)
                else:
                    print("WARNING: Could not ping the XML-RPC server.  Will continue anyway.")
        else:
            self.__xmlrpc = None


    @staticmethod
    def __show_remaining_time(remaining):
        secs = int(remaining)
        days = int(secs / 86400)
        if days:
            secs = secs - (days * 86400)
        hours = int(secs / 3600)
        if hours:
            secs = secs - (hours * 3600)
        minutes = int(secs / 60)
        if minutes:
            secs = secs - (minutes * 60)
        print(f'rteval time remaining: {days}, {hours}, {minutes}, {secs}')


    def Prepare(self, onlyload=False):
        builddir = os.path.join(self.__rtevcfg.workdir, 'rteval-build')
        if not os.path.isdir(builddir):
            os.mkdir(builddir)

        # create our report directory
        try:
            # Only create a report dir if we're doing measurements
            # or the loads logging is enabled
            if not onlyload or self.__rtevcfg.logging:
                self.__reportdir = self._make_report_dir(self.__rtevcfg.workdir, "summary.xml")
        except Exception as err:
            raise RuntimeError(f"Cannot create report directory (NFS with rootsquash on?) [{err}]]")

        self.__logger.log(Log.INFO, "Preparing load modules")
        params = {'workdir':self.__rtevcfg.workdir,
                  'reportdir':self.__reportdir and self.__reportdir or "",
                  'builddir':builddir,
                  'srcdir':self.__rtevcfg.srcdir,
                  'verbose': self.__rtevcfg.verbose,
                  'debugging': self.__rtevcfg.debugging,
                  'numcores':self._sysinfo.cpu_getCores(True),
                  'logging':self.__rtevcfg.logging,
                  'memsize':self._sysinfo.mem_get_size(),
                  'numanodes':self._sysinfo.mem_get_numa_nodes(),
                  'duration': float(self.__rtevcfg.duration),
                  }
        self._loadmods.Setup(params)

        self.__logger.log(Log.INFO, "Preparing measurement modules")
        self._measuremods.Setup(params)


    def __RunMeasurementProfile(self, measure_profile):
        global earlystop
        if not isinstance(measure_profile, MeasurementProfile):
            raise Exception("measure_profile is not an MeasurementProfile object")

        measure_start = None
        (with_loads, run_parallel) = measure_profile.GetProfile()
        self.__logger.log(Log.INFO, "Using measurement profile [loads: %s  parallel: %s]" % (
            with_loads, run_parallel))
        try:
            nthreads = 0

            # start the loads
            if with_loads:
                self._loadmods.Start()

            print("rteval run on %s started at %s" % (os.uname()[2], time.asctime()))
            onlinecpus = self._sysinfo.cpu_getCores(True)
            cpulist = self._loadmods._cfg.GetSection("loads").cpulist
            if cpulist:
                print("started %d loads on cores %s" % (self._loadmods.ModulesLoaded(), cpulist), end=' ')
            else:
                print("started %d loads on %d cores" % (self._loadmods.ModulesLoaded(), onlinecpus), end=' ')
            if self._sysinfo.mem_get_numa_nodes() > 1:
                print(" with %d numa nodes" % self._sysinfo.mem_get_numa_nodes())
            else:
                print("")
            cpulist = self._measuremods._MeasurementModules__cfg.GetSection("measurement").cpulist
            if cpulist:
                print("started measurement threads on cores %s" % cpulist)
            else:
                print("started measurement threads on %d cores" % onlinecpus)
            print("Run duration: %s seconds" % str(self.__rtevcfg.duration))

            # start the cyclictest thread
            measure_profile.Start()

            # Unleash the loads and measurement threads
            report_interval = int(self.__rtevcfg.report_interval)
            if with_loads:
                self._loadmods.Unleash()
                nthreads = len(threading.enumerate())
            else:
                nthreads = None
            self.__logger.log(Log.INFO, "Waiting 30 seconds to let load modules settle down")
            time.sleep(30)
            measure_profile.Unleash()
            measure_start = datetime.now()

            # wait for time to expire or thread to die
            signal.signal(signal.SIGINT, sig_handler)
            signal.signal(signal.SIGTERM, sig_handler)
            self.__logger.log(Log.INFO, "waiting for duration (%s)" % str(self.__rtevcfg.duration))
            stoptime = (time.time() + float(self.__rtevcfg.duration))
            currtime = time.time()
            rpttime = currtime + report_interval
            load_avg_checked = 5
            while (currtime <= stoptime) and not stopsig_received:
                time.sleep(60.0)
                if not measure_profile.isAlive():
                    stoptime = currtime
                    earlystop = True
                    self.__logger.log(Log.WARN,
                                      "Measurement threads did not use the full time slot. Doing a controlled stop.")

                if with_loads:
                    if len(threading.enumerate()) < nthreads:
                        raise RuntimeError("load thread died!")

                if not load_avg_checked:
                    self._loadmods.SaveLoadAvg()
                    load_avg_checked = 5
                else:
                    load_avg_checked -= 1

                if currtime >= rpttime:
                    left_to_run = stoptime - currtime
                    self.__show_remaining_time(left_to_run)
                    rpttime = currtime + report_interval
                    print("load average: %.2f" % self._loadmods.GetLoadAvg())
                currtime = time.time()

            self.__logger.log(Log.DEBUG, "out of measurement loop")
            signal.signal(signal.SIGINT, signal.SIG_DFL)
            signal.signal(signal.SIGTERM, signal.SIG_DFL)

        except RuntimeError as err:
            if not stopsig_received:
                raise RuntimeError(f"appeared during measurement: {err}")

        finally:
            # stop measurement threads
            measure_profile.Stop()

            # stop the loads
            if with_loads:
                self._loadmods.Stop()

        print("stopping run at %s" % time.asctime())

        # wait for measurement modules to finish calculating stats
        measure_profile.WaitForCompletion()

        return measure_start


    def Measure(self):
        """ Run the full measurement suite with reports """
        global earlystop
        rtevalres = 0
        measure_start = None
        for meas_prf in self._measuremods:
            mstart = self.__RunMeasurementProfile(meas_prf)
            if measure_start is None:
                measure_start = mstart

        self._report(measure_start, self.__rtevcfg.xslt_report)
        if self.__rtevcfg.sysreport:
            self._sysinfo.run_sysreport(self.__reportdir)

        # if --xmlrpc-submit | -X was given, send our report to the given host
        if self.__xmlrpc:
            rtevalres = self.__xmlrpc.SendReport(self.GetXMLreport())

        if earlystop:
            rtevalres = 1
        self._sysinfo.copy_dmesg(self.__reportdir)
        self._tar_results()
        return rtevalres
