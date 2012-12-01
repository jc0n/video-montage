"""
VideoMontager is a simple class which provides a wrapper around ffmpeg and
imagemagic using them to create a montage of frames from specified video files.
"""

import logging
import os
import os.path
import re
import shutil
import subprocess
import sys
import tempfile

from collections import namedtuple
from datetime import timedelta
from multiprocessing.pool import ThreadPool

from progressbar import ProgressBar, SimpleProgress, Bar
from which import which, CommandNotFoundException

__author__ = 'John O\'Connor'
__version__ = '0.1.5'

__all__ = ('VideoMontager', )

log = logging.getLogger(__name__)

def command(cmd):
    which(cmd)
    def wrapper(argstr, **kwargs):
        fullcmd = cmd + ' %s' % argstr
        log.debug('Executing shell command: %s' % fullcmd)
        return subprocess.Popen(fullcmd, shell=True, **kwargs)
    return wrapper

FFMPEG = command('ffmpeg')
FFPROBE = command('ffprobe')
MONTAGE = command('montage')
CONVERT = command('convert')

VIDEO_EXTENSIONS = frozenset(('avi', 'flv', 'mkv', 'mng', 'mov',
                              'movie', 'mp4', 'mpe', 'mpeg',
                              'mpg', 'mpv', 'ogv', 'ts', 'wmv'))

VIDEO_RE = re.compile(r'''
    Duration:\s+(?P<hours>\d{2}):
                (?P<minutes>\d{2}):
                (?P<seconds>\d{2})\.\d{2},
    .+
    Video:\s+(?P<codec>[^,]+),[^,]+,\s+(?P<resolution>\d+x\d+)
    .+
    (?P<fps>\d+)\s+tbr,
    ''', re.VERBOSE | re.DOTALL | re.MULTILINE)

FRAME_RE = re.compile(b'frame=\s*(\d+)', re.MULTILINE)


Video = namedtuple('Video', 'filename basename resolution codec duration fps')


class InvalidArgumentException(Exception):
    """
    Raised when command line argument is invalid.
    """
    pass


class InvalidVideoException(Exception):
    """
    Raised when video file contains invalid data.
    """
    pass


class VideoMontager(object):
    """
    VideoMontager Class

    Provides a simple wrapper around ffmpeg and imagemagic tools and uses
    them to process video files and directories with video files into a
    montage of screenshots from various intervals in each video file.
    """
    def __init__(self, video_files, background_color='black', format='jpg',
                 label_color='white', outdir=None, overwrite=False, progress=False,
                 recursive=False, start_seconds=120, tempdir=None, thumbnails=25, thumbsize=435,
                 ffmpeg_options='', *args, **kwargs):
        self.background_color = background_color
        self.format = format
        self.label_color = label_color
        self.outdir = outdir
        self.overwrite = overwrite
        self.progress = progress
        self.recursive = recursive
        self.start_seconds = start_seconds
        self.tempdir = tempdir
        self.thumbnails = thumbnails
        self.thumbsize = thumbsize
        self.video_files = video_files
        self.ffmpeg_options = ffmpeg_options
        self._pool = ThreadPool()

    def process_videos(self):
        "Start processing video files."
        if not self.tempdir:
            tempdir = tempfile.mkdtemp()
            cleanup = True
            log.info("Created temp directory: %s" % tempdir)
        else:
            tempdir = self.tempdir
            cleanup = False
            log.info("Using specified temp directory: %s" % tempdir)

        try:
            for video_file in self._get_video_files():
                try:
                    video = self._video(video_file)
                except InvalidVideoException:
                    continue

                tempprefix = os.path.join(tempdir, video.basename)
                self._process_video(video, tempprefix)
        except KeyboardInterrupt:
            pass

        if cleanup:
            log.info("Removing temp directory: %s" % tempdir)
            shutil.rmtree(tempdir)

    def _video(self, video_file):
        ffprobe = FFPROBE('"%s"' % video_file,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT)
        stdout, stderr = ffprobe.communicate()
        m = VIDEO_RE.search(stdout)
        if not m:
            log.error("ffprobe failed for file %s" % video_file)
            raise InvalidVideoException(video_file)
        v = m.groupdict()
        return Video(filename=video_file,
                     basename=os.path.basename(video_file),
                     codec=v['codec'],
                     resolution=v['resolution'],
                     fps=int(v['fps']),
                     duration=timedelta(
                              hours=int(v['hours']),
                              minutes=int(v['minutes']),
                              seconds=int(v['seconds'])))


    def _get_video_files(self):
        """
        Generator producing all video files from specified files and directories.
        """
        def is_video(filepath):
            if not os.path.exists(filepath):
                return False
            if not os.path.isfile(filepath):
                return False
            if not os.path.getsize(filepath):
                return False
            name, ext = os.path.splitext(filepath)
            return ext[1:] in VIDEO_EXTENSIONS

        for video_file in self.video_files:
            if os.path.isdir(video_file):
                if self.recursive:
                    for root, dirs, files in os.walk(video_file):
                        for filename in sorted(files):
                            filepath = os.path.join(root, filename)
                            if is_video(filepath):
                                    yield filepath
                else:
                    for filename in sorted(os.listdir(video_file)):
                        filepath = os.path.join(video_file, filename)
                        if is_video(filepath):
                            yield filepath
            elif is_video(video_file):
                yield video_file
            else:
                log.warning("Invalid video file specified: %s" % video_file)
                raise InvalidArgumentException(video_file)

    def _process_video(self, video, tempprefix):
        """
        Process individual Video object.
        """
        outdir = self.outdir or os.path.dirname(video.filename)
        outprefix = os.path.join(outdir, video.basename)
        montage_file = "%s.%s" % (outprefix, self.format)
        if os.path.exists(montage_file):
            if not self.overwrite:
                log.warning("Found existing montage file %s, skipping." % montage_file)
                return
            os.remove(montage_file)

        log.info("Creating thumbnails for %s" % video.basename)
        thumbnails = self._create_thumbnails(video, tempprefix)

        log.info("Resizing thumbnails")
        self._pool.map(self._resize_thumbnail, thumbnails)

        log.info("Creating montage %s" % montage_file)
        self._create_montage(montage_file, thumbnails)

        log.info("Applying label for %s" % montage_file)
        self._apply_label(montage_file, video)

        log.info("Cleaning up thumbnails")
        for thumbnail in thumbnails:
            if os.path.exists(thumbnail):
                os.remove(thumbnail)

    def _create_montage(self, montage_file, thumbnails):
        montage = MONTAGE('-background %s -borderwidth 0 -geometry "+1+1" "%s" "%s"' % (
                          self.background_color, '" "'.join(thumbnails[1:]), montage_file))
        montage.wait()

    def _apply_label(self, montage_file, video):
        label = 'File: %s | Codec: %s | Resolution: %s | Length %s' % (
                    video.basename, video.codec, video.resolution, str(video.duration))

        convert = CONVERT('-gravity North -splice 0x28 -background %s '
                          '-fill %s -pointsize 12 -annotate +0+6 '
                          '"%s" "%s" "%s"' % (
                          self.background_color, self.label_color, label, montage_file, montage_file))
        convert.wait()

    def _resize_thumbnail(self, thumbnail):
        convert = CONVERT('-quality 100 -resize "%d" "%s" "%s"' % (
                        self.thumbsize, thumbnail, thumbnail))
        convert.wait()

    def _create_thumbnails(self, video, outprefix):
        vframes = self.thumbnails + 1
        interval = (video.duration.total_seconds() - self.start_seconds) / self.thumbnails
        args = '-y -i "%s" -ss %d -r "1/%d" -vframes %d -bt 100000000 "%s_%%03d.%s" %s' % (
               video.filename, self.start_seconds, interval, vframes, outprefix,
               self.format, self.ffmpeg_options)
        ffmpeg = FFMPEG(args, stderr=subprocess.PIPE, bufsize=1)
        if self.progress:
            progress = ProgressBar(maxval=vframes, widgets=[SimpleProgress(), Bar()])
            progress.start()
            b = bytearray(80)
            while True:
                chunk = ffmpeg.stderr.read(80)
                if chunk == b'':
                    break
                b.extend(chunk)
                m = FRAME_RE.search(b)
                if m:
                    progress.update(int(m.group(1)))
                    b[:] = b''
            progress.finish()

        ffmpeg.wait()
        return ["%s_%03d.%s" % (outprefix, i, self.format)
                    for i in range(1, vframes + 1)]
