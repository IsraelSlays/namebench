#
#  controller.py
#  namebench
#
#  Created by Thomas Stromberg on 9/10/09.
#  Copyright (c) 2009 __MyCompanyName__. All rights reserved.
#

from objc import YES, NO, IBAction, IBOutlet
from Foundation import *
from AppKit import *
import datetime
import operator
import urllib
import time
import webbrowser
import tempfile
import sys
import os
import re

# TODO(tstromberg): Research best practices for bundling cocoa frontends.
NB_SOURCE = os.getcwd()[0:os.getcwd().index('/cocoa/')]
sys.path.append(NB_SOURCE)
from lib import config
from lib import nameserver_list
from lib import third_party
from lib import benchmark
from lib import util
from lib import history_parser

class controller(NSWindowController):
  nameserver_form = IBOutlet()
  include_global = IBOutlet()
  include_regional = IBOutlet()
  data_source = IBOutlet()
  selection_mode = IBOutlet()
  num_tests = IBOutlet()
  num_runs = IBOutlet()

  status = IBOutlet()
  spinner = IBOutlet()

  def awakeFromNib(self):
    """Initializes our class."""
    conf_file = os.path.join(NB_SOURCE, 'namebench.cfg')
    (self.options, self.primary, self.secondary) = config.GetConfiguration(filename=conf_file)
    # TODO(tstromberg): Consider moving this into a thread for faster loading.
    self.imported_records = None
    self.updateStatus('Discovering sources')
    self.discoverSources()
    self.updateStatus('Populating Form...')
    self.setFormDefaults()
    self.updateStatus('Ready')

  @IBAction
  def startJob_(self, sender):
    """Trigger for the 'Start Benchmark' button, starts benchmark thread."""
    self.ProcessForm()
    self.updateStatus('Starting benchmark thread')
    t = NSThread.alloc().initWithTarget_selector_object_(self, self.benchmarkThread, None)
    t.start()

  def updateStatus(self, message, count=None, total=None):
    """Update the status message at the bottom of the window."""
  
    if total and count:
      state = '%s [%s/%s]' % (message, count, total)
    elif count:
      state = '%s%s' % (message, '.' * count)
    else:
      state = message

    NSLog(state)
    self.status.setStringValue_(state)

  def ProcessForm(self):
    """Parse the form fields and populate class variables."""
    self.updateStatus('Processing form inputs')
    if not int(self.include_global.stringValue()):
      self.updateStatus('Not using primary')
      self.primary = []
    if not int(self.include_regional.stringValue()):
      self.updateStatus('Not using secondary')
      self.secondary = []
      
    self.select_mode = self.selection_mode.titleOfSelectedItem().lower()
    input_choice = self.data_source.titleOfSelectedItem()
    for source in self.sources:
      if self.sourceToTitle(source) == input_choice:
        src_type = source[0]
        self.updateStatus('Parsed source type to %s' % src_type)
        if src_type:
          self.imported_records = self.imported_sources[source[0]]
        
    for ns in re.split('[, ]+', self.nameserver_form.stringValue()):
      self.primary.append((ns,ns))

    self.options.test_count = int(self.num_tests.stringValue())
    self.options.run_count = int(self.num_runs.stringValue())
    self.updateStatus("%s tests, %s runs" % (self.options.test_count, self.options.run_count))

    self.updateStatus('Building nameserver objects')
    self.nameservers = nameserver_list.NameServers(
        self.primary,
        self.secondary,
        num_servers=self.options.num_servers,
        timeout=self.options.timeout,
        health_timeout=self.options.health_timeout,
        status_callback=self.updateStatus
    )
    self.nameservers.cache_dir = tempfile.gettempdir()
    if len(self.nameservers) > 1:
      self.nameservers.thread_count = int(self.options.thread_count)
      self.nameservers.cache_dir = tempfile.gettempdir()

  def benchmarkThread(self):
    """Run the benchmarks, designed to be run in a thread."""
    pool = NSAutoreleasePool.alloc().init()
    self.spinner.startAnimation_(self)
    self.updateStatus('Preparing benchmark')
    self.nameservers.FindAndRemoveUndesirables()
    bmark = benchmark.Benchmark(self.nameservers, test_count=self.options.test_count, run_count=self.options.run_count,
                                status_callback=self.updateStatus)
    bmark.updateStatus = self.updateStatus
    self.updateStatus('Creating test records using %s' % self.select_mode)
    if self.imported_records:
      bmark.CreateTests(self.imported_records, select_mode=self.select_mode)
    else:
      bmark.CreateTestsFromFile('%s/data/alexa-top-10000-global.txt' % NB_SOURCE,
                                select_mode=self.select_mode)

    self.updateStatus('Running...')
    bmark.Run()
    output_dir = os.path.join(os.getenv('HOME'), 'Desktop')
    output_base = 'namebench_%s' % datetime.datetime.strftime(datetime.datetime.now(), '%Y-%m-%d %H%m')
    report_path = os.path.join(output_dir, '%s.html' % output_base)
    self.updateStatus('Saving report to %s' % report_path)
    f = open(report_path, 'w')
    bmark.CreateReport(format='html', output_fp=f)
    f.close()
    csv_path = os.path.join(output_dir, '%s.csv' % output_base)
    self.updateStatus('Saving detailed results to %s' % csv_path)
    bmark.SaveResultsToCsv(csv_path)
    self.updateStatus('Creating report URL for %s' % report_path)
    url = 'file://' + urllib.quote(report_path)
    success = webbrowser.open(url)
    if not success:
      self.displayError("Unable to open web-browser", "Please open %s manually." % report_path)

    self.spinner.stopAnimation_(self)
    best = bmark.BestOverallNameServer()
    self.updateStatus('Complete! %s [%s] is the best.' % (best.name, best.ip))
    pool.release()

  def displayError(self, msg, details):
    """Display an alert drop-down message"""
    alert = NSAlert.alloc().init()
    alert.setMessageText_(msg)
    alert.setInformativeText_(details)
    buttonPressed = alert.runModal()


  def discoverSources(self):
    """Seek out and create a list of valid data sources."""
    self.updateStatus('Searching for usable data sources')
    h = history_parser.HistoryParser()
    source_desc = h.GetTypes()
    self.imported_sources = h.ParseAllTypes()
    self.sources = []
    for src_type in self.imported_sources:
      self.sources.append(
        (src_type, source_desc[src_type], len(self.imported_sources[src_type]))
      )

    self.sources.sort(key=operator.itemgetter(2), reverse=True)
    # TODO(tstromberg): Don't hardcode input types.
    self.sources.append((None, 'Alexa Top Global Domains', 10000))
    
  def sourceToTitle(self, source):
    """Convert a source tuple to a title."""
    (short_name, full_name, num_hosts) = source
    return '%s (%s)' % (full_name, num_hosts)

  def setFormDefaults(self):
    """Set up the form with sane initial values."""
    nameservers_string = ', '.join(util.InternalNameServers())
    self.nameserver_form.setStringValue_(nameservers_string)
    self.num_tests.setStringValue_(self.options.test_count)
    self.num_runs.setStringValue_(self.options.run_count)
    self.selection_mode.removeAllItems()
    self.selection_mode.addItemsWithTitles_(['Weighted', 'Random', 'Chunk'])
    self.data_source.removeAllItems()
    for source in self.sources:
      self.data_source.addItemWithTitle_(self.sourceToTitle(source))

