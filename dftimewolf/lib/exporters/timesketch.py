# -*- coding: utf-8 -*-
"""Export processing results to Timesketch.
Threaded version of existing Timesketch module."""

import re
import time
from typing import Optional, List, Type

from timesketch_import_client import importer
from timesketch_api_client import sketch as ts_sketch
from timesketch_api_client import client as ts_client  # pylint: disable=unused-import,line-too-long  # used for typing

from dftimewolf.lib import module, timesketch_utils
from dftimewolf.lib.containers import containers, interface
from dftimewolf.lib.modules import manager as modules_manager
from dftimewolf.lib.state import DFTimewolfState


class TimesketchExporter(module.ThreadAwareModule):
  """Exports a given set of plaso or CSV files to Timesketch. This is a
  threaded version of an equivalent module.

  input: A list of paths to plaso or CSV files.
  output: A URL to the generated timeline.

  Attributes:
    incident_id (str): Incident ID or reference. Used in sketch description.
    sketch_id (int): Sketch ID to add the resulting timeline to. If not
        provided, a new sketch is created.
    timesketch_api (TimesketchApiClient): Timesketch API client.
  """

  # The name of a ticket attribute that contains the URL to a sketch.
  _SKETCH_ATTRIBUTE_NAME = 'Timesketch URL'

  def __init__(self,
               state: DFTimewolfState,
               name: Optional[str]=None,
               critical: bool=False) -> None:
    super(TimesketchExporter, self).__init__(
        state, name=name, critical=critical)
    self.incident_id = None
    self.sketch_id = 0
    self.timesketch_api = None  # type: ts_client.TimesketchApi
    self._analyzers = []  # type: List[str]
    self.wait_for_timelines = False
    self.host_url = None
    self.sketch = None  #type: ts_sketch

  def SetUp(self,  # pylint: disable=arguments-differ
            incident_id: None=None,
            sketch_id: int=0,
            analyzers: None=None,
            token_password: str='',
            wait_for_timelines: bool=False) -> None:
    """Setup a connection to a Timesketch server and create a sketch if needed.

    Args:
      incident_id (Optional[str]): Incident ID or reference. Used in sketch
          description.
      sketch_id (Optional[str]): Sketch ID to add the resulting timeline to.
          If not provided, a new sketch is created.
      analyzers (Optional[List[str]): If provided a list of analyzer names
          to run on the sketch after they've been imported to Timesketch.
      token_password (str): optional password used to decrypt the
          Timesketch credential storage. Defaults to an empty string since
          the upstream library expects a string value. An empty string means
          a password will be generated by the upstream library.
      wait_for_timelines (bool): Whether to wait until timelines are processed
          in the Timesketch server or not.
    """
    self.wait_for_timelines = wait_for_timelines

    self.timesketch_api = timesketch_utils.GetApiClient(
        self.state, token_password=token_password)
    if not self.timesketch_api:
      self.ModuleError(
          'Unable to get a Timesketch API client, try deleting the files '
          '~/.timesketchrc and ~/.timesketch.token', critical=True)
    self.incident_id = incident_id
    self.sketch_id = int(sketch_id) if sketch_id else 0
    self.sketch = None

    # Check that we have a timesketch session.
    if not (self.timesketch_api or self.timesketch_api.session):
      message = 'Could not connect to Timesketch server'
      self.ModuleError(message, critical=True)

    # If no sketch ID is provided through the CLI, attempt to get it from
    # attributes
    if not self.sketch_id:
      self.sketch_id = self._GetSketchIDFromAttributes()

    # If we have a sketch ID, check that we can write to it and cache it.
    if self.sketch_id:
      self.sketch = self.timesketch_api.get_sketch(self.sketch_id)
      if 'write' not in self.sketch.my_acl:
        self.ModuleError(
            'No write access to sketch ID {0:d}, aborting'.format(
                self.sketch_id),
            critical=True)
      self.state.AddToCache('timesketch_sketch', self.sketch)
      self.sketch_id = self.sketch.id

    if analyzers:
      self._analyzers = [x.strip() for x in analyzers.split(',')]

  def _CreateSketch(self, incident_id: Optional[str]=None) -> ts_sketch.Sketch:
    """Creates a new Timesketch sketch.

    Args:
      incident_id (str): Incident ID to use sketch description.

    Returns:
      timesketch_api_client.Sketch: An instance of the sketch object.
    """
    if incident_id:
      sketch_name = 'Sketch for incident ID: ' + incident_id
    else:
      sketch_name = 'Untitled sketch'
    sketch_description = 'Sketch generated by dfTimewolf'

    sketch = self.timesketch_api.create_sketch(
        sketch_name, sketch_description)
    self.sketch_id = sketch.id
    if incident_id:
      sketch.add_attribute(
          'incident_id', incident_id, ontology='text')
    self.state.AddToCache('timesketch_sketch', sketch)

    return sketch

  def _WaitForTimelines(self) -> None:
    """Waits for all timelines in a sketch to be processed."""
    time.sleep(5)  # Give Timesketch time to populate recently added timelines.
    sketch = self.timesketch_api.get_sketch(self.sketch_id)
    timelines = sketch.list_timelines()
    while True:
      if all(tl.status in ['fail', 'ready', 'timeout', 'archived']
             for tl in timelines):
        break
      time.sleep(10)

  def _GetSketchIDFromAttributes(self) -> int:
    """Attempts to retrieve a Timesketch ID from ticket attributes.

    Returns:
      int: the sketch idenifier, or 0 if one was not available.
    """
    attributes = self.state.GetContainers(containers.TicketAttribute)
    for attribute in attributes:
      if attribute.name == self._SKETCH_ATTRIBUTE_NAME:
        sketch_match = re.search(r'sketch/(\d+)/', attribute.value)
        if sketch_match:
          sketch_id = int(sketch_match.group(1), 10)
          return sketch_id
    return 0

  def Process(self, container: containers.File) -> None:
    """Executes a Timesketch export.

    Args:
      container (containers.File): A container holding a File to import."""

    recipe_name = self.state.recipe.get('name', 'no_recipe')

    description = container.name
    if description:
      name = description.rpartition('.')[0]
      name = name if name else description
      name = name.replace(' ', '_').replace('-', '_')
      timeline_name = '{0:s}_{1:s}'.format(
          recipe_name, name)
    else:
      timeline_name = recipe_name

    self.logger.info('Uploading {0:s}...'.format(timeline_name))

    with importer.ImportStreamer() as streamer:
      streamer.set_sketch(self.sketch)
      streamer.set_timeline_name(timeline_name)

      path = container.path
      streamer.add_file(path)
      if streamer.response and container.description:
        streamer.timeline.description = container.description

    if self.wait_for_timelines:
      self.logger.info('Waiting for timeline {0:s} to finish processing...'\
          .format(timeline_name))
      self._WaitForTimelines()

    for analyzer in self._analyzers:
      self.logger.info("Running analyzer {0:s} on timeline {1:s}".format(
          analyzer, timeline_name))
      results = self.sketch.run_analyzer(
          analyzer_name=analyzer, timeline_name=timeline_name)

      if not results:
        self.logger.info('Analyzer [{0:s}] not able to run on {1:s}'.format(
            analyzer, timeline_name))
        continue

      # Unknown why, but we get a list of 2 identical result objects
      results = results[0]
      session_id = results._session_id # pylint: disable=protected-access
      if not session_id:
        self.logger.info(
            'Analyzer [{0:s}] didn\'t provide any session data'.format(
                analyzer))
        continue
      self.logger.info('Analyzer: {0:s} is running, session ID: {1:d}'.format(
          analyzer, session_id))
      self.logger.info(results.status_string)

  @staticmethod
  def GetThreadOnContainerType() -> Type[interface.AttributeContainer]:
    return containers.File

  def GetThreadPoolSize(self) -> int:
    return 5

  def PreSetUp(self) -> None:
    pass

  def PostSetUp(self) -> None:
    pass

  def PreProcess(self) -> None:
    """Get the sketch, creating it if it doesn't yet exist."""
    if not self.timesketch_api:
      message = 'Could not connect to Timesketch server'
      self.ModuleError(message, critical=True)

    self.sketch = self.state.GetFromCache('timesketch_sketch')
    if not self.sketch and self.sketch_id:
      self.logger.info('Using exiting sketch: {0:d}'.format(self.sketch_id))
      self.sketch = self.timesketch_api.get_sketch(self.sketch_id)

    # Create the sketch if no sketch was stored in the cache.
    if not self.sketch:
      self.sketch = self._CreateSketch(incident_id=self.incident_id)
      self.sketch_id = self.sketch.id
      self.logger.info('New sketch created: {0:d}'.format(self.sketch_id))

  def PostProcess(self) -> None:
    api_root = self.sketch.api.api_root
    host_url = api_root.partition('api/v1')[0]
    sketch_url = '{0:s}sketches/{1:d}/'.format(host_url, self.sketch.id)
    message = 'Your Timesketch URL is: {0:s}'.format(sketch_url)
    self.logger.success(message)

    report_container = containers.Report(
        module_name='TimesketchExporter',
        text=message,
        text_format='markdown')
    self.state.StoreContainer(report_container)


modules_manager.ModulesManager.RegisterModule(TimesketchExporter)
