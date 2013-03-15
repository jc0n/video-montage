"""
VideoMontager is a simple class which provides a wrapper around ffmpeg and
imagemagic using them to create a montage of frames from specified video files.
"""

import logging
import os
import platform
import re
import shutil
import subprocess
import tempfile

from collections import namedtuple
from datetime import timedelta

from progressbar import ProgressBar, SimpleProgress, Bar
from which import which

__author__ = 'John O\'Connor'
__version__ = '0.1.5'

__all__ = ('VideoMontager', )

log = logging.getLogger(__name__)

def command(cmd, executor=subprocess.check_call):
    which(cmd)
    def wrapper(argstr, **kwargs):
        fullcmd = cmd + ' %s' % argstr
        log.debug('Executing shell command: %s' % fullcmd)
        return executor(fullcmd, shell=True, **kwargs)
    return wrapper

FFMPEG = command('ffmpeg', subprocess.Popen)
FFPROBE = command('ffprobe', subprocess.Popen)
MONTAGE = command('montage')

if platform.system() == "Windows":
    # C:\Windows\System32\convert.EXE will usually match
    # first unless we look elsewhere.
    montage_path = os.path.dirname(which('montage.exe'))
    CONVERT = command(os.path.join(montage_path, 'convert.exe'))
else:
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

FFMPEG_STDIO_READ_BUFSIZE = 80

Video = namedtuple('Video', 'filename basename resolution codec duration fps')


class InvalidVideoFileException(Exception):
    """
    Raised when video file contains invalid data.
    """
    pass


class VideoProcessingException(Exception):
    """
    Raised when an error occurs processing a video file
    """
    pass


class VideoMontager(object):
    """
    VideoMontager Class

    Provides a simple wrapper around ffmpeg and imagemagic tools and uses
    them to process video files and directories with video files into a
    montage of screenshots from various intervals in each video.
    """
    def __init__(self, video_files, background_color='black', format='jpg',
                 label_color='white', outdir=None, overwrite=False, progress=False,
                 recursive=False, start_seconds=120, thumbnail_count=25, resolution=435,
                 ffmpeg_options='', *args, **kwargs):
        self.background_color = background_color
        self.format = format
        self.label_color = label_color
        self.outdir = outdir
        self.overwrite = overwrite
        self.progress = progress
        self.recursive = recursive
        self.start_seconds = start_seconds
        self.thumbnail_count = thumbnail_count
        self.resolution = resolution
        self.video_files = video_files
        self.ffmpeg_options = ffmpeg_options

    def process_videos(self):
        "Begin processing video files."
        self.tempdir = tempfile.mkdtemp()
        log.debug("Created temp directory: %s" % self.tempdir)
        try:
            for video_file in self._get_video_files():
                try:
                    self._process_video_file(video_file)
                except InvalidVideoFileException:
                    continue
        except KeyboardInterrupt: # mostly for ctrl-c
            pass
        finally:
            log.debug("Removing temp directory: %s" % self.tempdir)
            shutil.rmtree(self.tempdir)

    def _make_video(self, video_file):
        ffprobe = FFPROBE('"%s"' % video_file,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT)
        stdout, stderr = ffprobe.communicate()
        m = VIDEO_RE.search(stdout)
        if not m:
            log.error("ffprobe failed for file %s" % video_file)
            raise InvalidVideoFileException(video_file)
        v = m.groupdict()
        duration = timedelta(hours=int(v['hours']),
                             minutes=int(v['minutes']),
                             seconds=int(v['seconds']))
        return Video._make((video_file,
                            os.path.basename(video_file),
                            v['resolution'],
                            v['codec'],
                            duration,
                            int(v['fps'])))


    def _get_video_files(self):
        """
        A generator which produces all video files to process based on
        specified input files and directories.
        """
        def is_video(filepath):
            if not os.path.exists(filepath):
                return False
            if not os.path.isfile(filepath):
                return False
            if not os.path.getsize(filepath):
                return False
            name, ext = os.path.splitext(filepath)
            return ext[1:].lower() in VIDEO_EXTENSIONS

        for video_file in self.video_files:
            if os.path.isdir(video_file):
                if self.recursive:
                    for root, dirs, files in os.walk(video_file, topdown=True):
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
                raise InvalidVideoFileException(video_file)

    def _process_video_file(self, video_file):
        "Process an individual `Video` object."
        outdir = self.outdir or os.path.dirname(video_file)
        outprefix = os.path.join(outdir, os.path.basename(video_file))
        montage_file = "%s.%s" % (outprefix, self.format)
        if os.path.exists(montage_file):
            if not self.overwrite:
                log.info("Found existing montage file %s, skipping." % montage_file)
                return
            os.remove(montage_file)

        video = self._make_video(video_file)
        tempprefix = os.path.join(self.tempdir, video.basename)
        thumbnails = self._create_thumbnails(video, tempprefix)

        log.info("Creating montage %s" % montage_file)
        MONTAGE('-background %s -borderwidth 0 -geometry "+1+1" "%s" "%s"' % (
                self.background_color, '" "'.join(thumbnails[1:]), montage_file))
        CONVERT('-resize "%s" "%s" "%s"' % (self.resolution, montage_file, montage_file))
        log.debug("Applying label for %s" % montage_file)
        label = '%s | Codec: %s | Resolution: %s | Length %s' % (
                    video.basename, video.codec, video.resolution, str(video.duration))
        CONVERT('-gravity North -splice 0x28 -background %s '
                '-fill %s -pointsize 12 -annotate +0+6 '
                '"%s" "%s" "%s"' % (
                self.background_color, self.label_color, label,
                montage_file, montage_file))


    def _create_thumbnails(self, video, outprefix):
        log.info("Creating thumbnails for %s" % video.basename)

        vframes = self.thumbnail_count + 1
        interval = (video.duration.total_seconds() - self.start_seconds) / self.thumbnail_count
        args = '-y -i "%s" -ss %d -r "1/%d" -vframes %d -bt 100000000 "%s_%%03d.%s" %s' % (
               video.filename, self.start_seconds, interval, vframes, outprefix,
               self.format, self.ffmpeg_options)

        ffmpeg = FFMPEG(args, stderr=subprocess.STDOUT, stdout=subprocess.PIPE)

        # whether or not to show a progress bar
        if self.progress:
            progress = ProgressBar(maxval=vframes, widgets=[SimpleProgress(), Bar()])
            progress.start()

        # consume stdout output from ffmpeg and extract progress information
        b = bytearray(FFMPEG_STDIO_READ_BUFSIZE)
        index, next_index = 0, 0
        thumbnails = []
        while True:
            chunk = ffmpeg.stdout.read(FFMPEG_STDIO_READ_BUFSIZE)
            if not chunk:
                break
            b += chunk
            m = FRAME_RE.search(b)
            if not m:
                continue
            next_index = int(m.group(1))
            if next_index <= index:
                b[:] = b''
                continue
            index = next_index
            if index > 1: # skip the first thumbnail
                thumbnail_file = "%s_%03d.%s" % (outprefix, index, self.format)
                if not os.path.exists(thumbnail_file):
                    raise VideoProcessingException(
                            "Unable to create thumbnail image %d." % index)
                thumbnails.append(thumbnail_file)
            if self.progress:
                progress.update(index)

        if self.progress:
            progress.finish()

        ffmpeg.wait()
        if ffmpeg.returncode != 0:
            raise subprocess.CalledProcessError('ffmpeg', ffmpeg.returncode)

        assert len(thumbnails) == self.thumbnail_count
        return thumbnails
